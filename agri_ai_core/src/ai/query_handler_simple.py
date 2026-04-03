"""LLM 쿼리 핸들러 — Tool Use 방식으로 사용자 질문 처리 및 SSE 스트리밍."""
import hashlib
import json
import os
import re
import asyncio
import threading
import time
import traceback
from datetime import datetime

from agri_ai_core.logs import setup_logger, setup_web_logger
from agri_ai_core.src.ai.llm_client import get_llm_response_with_tools
from agri_ai_core.src.ai.file_processor import process_uploaded_files
from agri_ai_core.src.ai.conversation_store import get_conversation_store
from agri_ai_core.src.ai.utils import GREETING_RE as _GREETING_RE_HYBRID

logger = setup_logger(__name__)
web_logger = setup_web_logger("chat")

# 시스템/가상 농장 ID (관리자 선택 시 전체 대화 검색, 일반 사용자는 자기 농장 + 시스템 농장 대화 검색)
_SYSTEM_FARM_ID = "0"

_LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SECONDS", "600"))
_STREAM_HEARTBEAT_SECONDS = max(1, int(os.getenv("STREAM_HEARTBEAT_SECONDS", "3")))


# ════════════════════════════════════════════════════════════
# 대화 주제 분류 (규칙 기반, LLM 호출 불필요)
# VectorDB 저장 시 topic 메타데이터로 추가하여 검색 정확도 향상
# ════════════════════════════════════════════════════════════
_TOPIC_PATTERNS = [
    (re.compile(r'센서|온도|습도|CO2|수온|릴레이|재배사|생육|균사'), "farm_data"),
    (re.compile(r'날씨|기온|비|바람|강수|예보|기상'), "weather"),
    (re.compile(r'제어|켜|끄|가동|중지|작동|히터|팬|밸브'), "control"),
    (re.compile(r'검색|찾아|알려|추천|알아|맛집|관광|주유'), "search"),
]


def _classify_topic(query: str) -> str:
    """사용자 질문을 주제별로 분류한다 (규칙 기반). LLM 호출 없음."""
    if not query:
        return "general"
    for pattern, topic in _TOPIC_PATTERNS:
        if pattern.search(query):
            return topic
    return "general"


# ════════════════════════════════════════════════════════════
# 공통 중복 제거 헬퍼
# ════════════════════════════════════════════════════════════
def _dedupe_list(items, type_check, key_fn, value_fn=None):
    deduped, seen = [], set()
    for item in items or []:
        if not isinstance(item, type_check):
            continue
        key = key_fn(item)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(value_fn(item) if value_fn else item)
    return deduped


# ════════════════════════════════════════════════════════════
# 도구별 기본 인자 생성
# ════════════════════════════════════════════════════════════
# 파일명 패턴: UUID prefix + 파일명.확장자 또는 단순 파일명.확장자
# 확장자는 알파벳만 허용 (소수점 숫자 오탐 방지: 2528.92000 등)
# 단순 파일명은 최소 1개 문자(한글/영문) 포함 필수
_FILE_NAME_RE = re.compile(
    r'[\'"]?'
    r'('
    r'[a-f0-9]{6,}_[\w\-가-힣.]+\.[a-zA-Z]{2,5}'
    r'|'
    r'(?=.*[a-zA-Z가-힣])[\w\-가-힣.]+\.[a-zA-Z]{2,5}'
    r')'
    r'[\'"]?'
)


def _build_default_tool_args(user_query, farm_id, house_id, auth_farm_id=None):
    # 질문에서 파일명 패턴 감지
    detected_file_name = None
    match = _FILE_NAME_RE.search(user_query or "")
    if match:
        detected_file_name = match.group(1)
        # UUID 접두사(8자리hex_) 제거하여 원본 파일명으로 정규화
        _fn_m = re.match(r'^[0-9a-f]{8}_(.+)$', detected_file_name)
        if _fn_m:
            detected_file_name = _fn_m.group(1)
        logger.info(f"[기본인자] 파일명 감지: {detected_file_name}")

    # auth_farm_id: RAG 파일 검색/목록 권한 결정용
    # 시스템관리자(auth_farm_id=None) → 전체 농장 접근, 농장사용자 → 자기 농장만
    _auth_fid = str(auth_farm_id) if auth_farm_id is not None else None
    # session_farm_id: 현재 UI에서 선택된 농장 (삭제 시 기준)
    # 시스템관리자도 선택된 농장 기준으로 삭제 (전체 삭제 방지)
    _session_fid = str(farm_id) if farm_id is not None else _auth_fid

    return {
        "search_web": {"query": user_query},
        "search_farm_knowledge": {
            "query": user_query,
            "n_results": 5,
            "file_name": detected_file_name,
            "farm_id": _session_fid,
            "house_id": str(house_id) if house_id is not None else None,
        },
        "delete_farm_knowledge": {
            "farm_id": _session_fid,
        },
        "get_farm_realtime_data": {
            "farm_id": str(farm_id) if farm_id is not None else None,
            "house_id": str(house_id) if house_id is not None else None,
            "data_type": "all",
        },
    }


# ════════════════════════════════════════════════════════════
# 하이브리드 대화 컨텍스트 (VectorDB + 최근 턴)
# ════════════════════════════════════════════════════════════
_HYBRID_RECENT_TURNS = int(os.getenv("HYBRID_RECENT_TURNS", "2"))
_HYBRID_RELATED_RESULTS = int(os.getenv("HYBRID_RELATED_RESULTS", "5"))
_HYBRID_MAX_RECORDS_PER_FARM = int(os.getenv("HYBRID_MAX_RECORDS", "30"))
# VectorDB 관련 대화 검색 거리 임계값 (기존 16.0 → 3.0: 무관한 과거 대화 컨텍스트 유입 방지)
_CONVERSATION_MAX_DISTANCE = float(os.getenv("CONV_VECTOR_MAX_DISTANCE", "3.0"))


# ════════════════════════════════════════════════════════════
# 하이브리드 대화 컨텍스트: 직전 N턴 + VectorDB 관련 대화 검색
# ════════════════════════════════════════════════════════════
def _load_hybrid_context(session_id, user_query, farm_id, label=""):
    if not session_id:
        return None

    store = get_conversation_store()

    # [1] 직전 2턴 (즉시 맥락: "이거", "아까 그거" 참조 보장)
    recent_turns = store.get_recent_turns(session_id, n_turns=_HYBRID_RECENT_TURNS)

    # [2] VectorDB에서 관련 과거 대화 검색
    related_context = _search_related_conversations(user_query, farm_id)

    # [3] 하이브리드 컨텍스트 조합
    # [FIX] VectorDB 주제와 직전 대화 교차 중복 제거: 직전 대화에 이미 있는 질문은 VectorDB 주제에서 제외
    if related_context and recent_turns:
        _recent_user_queries = set()
        for t in recent_turns:
            if t.get("role") == "user":
                _recent_user_queries.add(t.get("content", "").strip()[:60])
        if _recent_user_queries:
            _filtered_lines = []
            for line in related_context.split("\n"):
                # "- (2026-03-12) 질문: ..." 형식에서 질문 부분 추출
                _q_start = line.find("질문: ")
                if _q_start >= 0:
                    _q_text = line[_q_start + 4:].strip()[:60]
                    # 직전 대화의 user 질문과 유사한지 비교
                    _is_dup = False
                    for _rq in _recent_user_queries:
                        if _q_text and _rq:
                            _common = sum(1 for a, b in zip(_q_text, _rq) if a == b)
                            _max_len = max(len(_q_text), len(_rq))
                            if _max_len > 0 and _common / _max_len > 0.7:
                                _is_dup = True
                                break
                    if _is_dup:
                        continue
                _filtered_lines.append(line)
            _dedup_removed = related_context.count("\n") + 1 - len(_filtered_lines)
            if _dedup_removed > 0:
                logger.info(f"[{label}하이브리드] VectorDB↔직전대화 교차 중복 {_dedup_removed}건 제거")
            related_context = "\n".join(_filtered_lines) if _filtered_lines else None

    history = []
    if related_context:
        history.append({
            "role": "system",
            "content": (
                f"[관련 과거 대화 주제 (참고만 하세요. 반드시 도구를 사용하여 최신 데이터를 확인한 후 답변하세요.)]\n"
                f"{related_context}"
            ),
        })
    if recent_turns:
        history.extend(recent_turns)

    if history:
        logger.info(
            f"[{label}하이브리드] session={session_id[:12]}... "
            f"최근={len(recent_turns)}턴, 관련대화={'있음' if related_context else '없음'}"
        )
    return history if history else None


# ════════════════════════════════════════════════════════════
# VectorDB conversation_collection에서 관련 과거 대화를 검색
# ════════════════════════════════════════════════════════════
def _search_related_conversations(user_query, farm_id):
    try:
        from agri_ai_core.src.ai.rag.embedder import embed_text
        from agri_ai_core.src.chroma.collections import conversation_collection
        from agri_ai_core.src.chroma.operations import query_documents

        _t0 = time.time()
        collection_name = conversation_collection()
        if not collection_name:
            return None

        _t1 = time.time()
        query_embedding = embed_text(user_query)
        _embed_ms = (time.time() - _t1) * 1000
        logger.debug(f"[PERF:대화] 관련대화-임베딩={_embed_ms:.0f}ms")
        if not query_embedding:
            return None

        # farm_id 기반 필터: 시스템 농장(0)은 전체 검색, 일반 농장은 자기 농장 + 시스템 농장 대화 검색
        if farm_id and str(farm_id) == _SYSTEM_FARM_ID:
            # 시스템 농장 선택 (관리자): 모든 농장 대화 검색
            where_filter = {"data_kind": {"$eq": "conversation_turn"}}
        elif farm_id:
            # 일반 농장: 자기 농장 + 시스템 농장 대화 검색
            where_filter = {
                "$and": [
                    {"$or": [
                        {"farm_id": {"$eq": str(farm_id)}},
                        {"farm_id": {"$eq": _SYSTEM_FARM_ID}},
                    ]},
                    {"data_kind": {"$eq": "conversation_turn"}},
                ]
            }
        else:
            where_filter = {"data_kind": {"$eq": "conversation_turn"}}

        _t2 = time.time()
        results = query_documents(
            collection_name=collection_name,
            query_embeddings=[query_embedding],
            n_results=_HYBRID_RELATED_RESULTS,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )
        _query_ms = (time.time() - _t2) * 1000
        _total_ms = (time.time() - _t0) * 1000
        logger.debug(f"[PERF:대화] 관련대화-VectorDB검색={_query_ms:.0f}ms, 관련대화-전체={_total_ms:.0f}ms")

        if "error" in results:
            logger.debug(f"[하이브리드] VectorDB 검색 실패: {results['error']}")
            return None

        documents = results.get("documents", []) or []
        metadatas = results.get("metadatas", []) or []
        distances = results.get("distances", []) or []

        # 거리 임계값 필터 + 포맷 (질문만 추출, 과거 답변은 포함하지 않음)
        # 동일 질문 중복 제거: query_preview 기준으로 중복 검색 결과 1건만 유지
        # 동일 주제(topic) 우선 정렬: 현재 질문과 같은 주제의 과거 대화를 먼저 배치
        current_topic = _classify_topic(user_query)
        lines_same_topic = []
        lines_other_topic = []
        _seen_queries: set = set()
        for idx, doc in enumerate(documents):
            dist = distances[idx] if idx < len(distances) else None
            if dist is not None and dist > _CONVERSATION_MAX_DISTANCE:
                continue
            meta = metadatas[idx] if idx < len(metadatas) else {}
            record_dt = (meta or {}).get("record_datetime", "")[:10]
            doc_topic = (meta or {}).get("topic", "general")
            # 과거 답변을 포함하면 LLM이 도구 호출 없이 복사하므로 질문만 추출
            query_preview = (meta or {}).get("query_preview", "")
            if not query_preview:
                raw = (doc or "")
                if raw.startswith("질문:"):
                    query_preview = raw.split("\n답변:")[0].replace("질문:", "").strip()[:200]
                else:
                    query_preview = raw[:200]
            if query_preview:
                # 중복 질문 제거 (100자까지 비교하여 유사 질문도 걸러냄)
                _preview_key = query_preview.strip()[:100]
                if _preview_key in _seen_queries:
                    continue
                # [FIX] 유사 질문 추가 필터: 기존 질문과 앞 60자 80% 이상 겹치면 중복으로 판정
                _is_similar = False
                _key_prefix = _preview_key[:60]
                for existing in _seen_queries:
                    _existing_prefix = existing[:60]
                    if _key_prefix and _existing_prefix:
                        _common = sum(1 for a, b in zip(_key_prefix, _existing_prefix) if a == b)
                        _max_len = max(len(_key_prefix), len(_existing_prefix))
                        if _max_len > 0 and _common / _max_len > 0.8:
                            _is_similar = True
                            break
                if _is_similar:
                    continue
                _seen_queries.add(_preview_key)
                line = f"- ({record_dt}) 질문: {query_preview}"
                # 동일 주제 우선
                if doc_topic == current_topic and current_topic != "general":
                    lines_same_topic.append(line)
                else:
                    lines_other_topic.append(line)

        lines = lines_same_topic + lines_other_topic
        if not lines:
            return None

        logger.info(f"[하이브리드] 관련 대화 {len(lines)}건 검색됨 (farm={farm_id}, topic={current_topic}, 동일주제={len(lines_same_topic)}건)")
        return "\n".join(lines[:_HYBRID_RELATED_RESULTS])

    except Exception as e:
        logger.debug(f"[하이브리드] 관련 대화 검색 실패: {e}")
        return None


# ════════════════════════════════════════════════════════════
# 대화 턴 저장: PostgreSQL(동기) + VectorDB(비동기)
# ════════════════════════════════════════════════════════════
def _save_conversation_turn_hybrid(session_id, user_query, response_text, farm_id=None, label=""):
    if not session_id:
        return

    # [1] PostgreSQL 저장 (기존 동기 방식)
    # DB 저장 전 SPECIAL 내부 마커 제거 (오염 방지)
    import re as _re
    _clean_response = _re.sub(r'<SPECIAL_\d+>.*?(?=\n|$)', '', response_text or '', flags=_re.DOTALL | _re.IGNORECASE)
    _clean_response = _re.sub(r'</?SPECIAL[^>]*>', '', _clean_response, flags=_re.IGNORECASE).strip()
    store = get_conversation_store()
    store.add_turn(session_id, "user", user_query, farm_id)
    store.add_turn(session_id, "assistant", _clean_response, farm_id)
    logger.info(f"[{label}하이브리드] session={session_id[:12]}... PostgreSQL 저장 완료")

    # [2] VectorDB 저장 (기본: 비동기, 환경변수로 동기 전환 가능)
    # 비동기: 응답 지연 방지, 단 연속 대화 시 최신 데이터 미포함 가능
    # 동기: 저장 완료 후 반환, 연속 대화에서도 최신 데이터 보장
    _sync_vectordb = os.getenv("SYNC_VECTORDB_SAVE", "false").lower() == "true"
    if _sync_vectordb:
        _async_vectordb_save(session_id, user_query, response_text, farm_id)
    else:
        threading.Thread(
            target=_async_vectordb_save,
            args=(session_id, user_query, response_text, farm_id),
            daemon=True,
        ).start()


# ════════════════════════════════════════════════════════════
# 백그라운드: Q+A 쌍을 VectorDB에 임베딩 저장 + 수명 관리
# ════════════════════════════════════════════════════════════
def _async_vectordb_save(session_id, user_query, response_text, farm_id):
    try:
        from agri_ai_core.src.ai.rag.embedder import embed_text
        from agri_ai_core.src.chroma.collections import conversation_collection
        from agri_ai_core.src.chroma.operations import upsert_documents_with_embedding

        collection_name = conversation_collection()
        if not collection_name:
            return

        # 인사/잡담은 VectorDB에 저장하지 않음
        stripped = (user_query or "").strip()
        if len(stripped) < 10 and _GREETING_RE_HYBRID.search(stripped):
            return

        # Q+A 결합 문서
        combined_text = f"질문: {user_query}\n답변: {(response_text or '')[:500]}"

        embedding = embed_text(combined_text)
        if not embedding:
            return

        # [FIX] 동일 Q&A 중복 저장 방지: 질문+응답 내용 기반 해시 → 같은 내용이면 같은 doc_id로 upsert
        _content_hash = hashlib.md5(
            f"{farm_id}_{user_query[:200]}_{(response_text or '')[:200]}".encode()
        ).hexdigest()[:16]
        doc_id_hash = _content_hash
        doc_id = f"conv_turn_{doc_id_hash}"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        topic = _classify_topic(user_query)
        docs = [{
            "doc_id": doc_id,
            "text": combined_text,
            "metadata": {
                "farm_id": str(farm_id) if farm_id else "",
                "session_id": session_id,
                "data_kind": "conversation_turn",
                "record_datetime": now_str,
                "query_preview": user_query[:100],
                "topic": topic,
            },
            "embedding": embedding,
        }]

        result = upsert_documents_with_embedding(collection_name, docs)
        if result.get("success"):
            logger.info(f"[하이브리드] VectorDB 대화 저장 완료: {doc_id}")
        else:
            logger.warning(f"[하이브리드] VectorDB 저장 실패: {result.get('error', '')}")

        # 수명 관리: farm_id당 최대 30건
        _prune_old_conversations(collection_name, farm_id)

    except Exception as e:
        logger.warning(f"[하이브리드] VectorDB 비동기 저장 실패: {e}")


# ════════════════════════════════════════════════════════════
# farm_id별 대화 기록을 최대 N건으로 유지
# LLM 호출 + 타임아웃 처리
# ════════════════════════════════════════════════════════════
def _prune_old_conversations(collection_name, farm_id):
    try:
        from agri_ai_core.src.chroma.operations import get_documents, delete_document

        if not farm_id:
            return

        where_filter = {
            "$and": [
                {"farm_id": {"$eq": str(farm_id)}},
                {"data_kind": {"$eq": "conversation_turn"}},
            ]
        }

        result = get_documents(
            collection_name,
            where=where_filter,
            include=["metadatas"],
            limit=100,
        )

        if "error" in result:
            return

        ids = result.get("ids", []) or []
        metadatas = result.get("metadatas", []) or []

        if len(ids) <= _HYBRID_MAX_RECORDS_PER_FARM:
            return

        # record_datetime 기준 정렬, 오래된 것부터
        paired = list(zip(ids, metadatas))
        paired.sort(key=lambda p: (p[1] or {}).get("record_datetime", ""))

        to_delete = len(paired) - _HYBRID_MAX_RECORDS_PER_FARM
        if to_delete > 0:
            delete_ids = [p[0] for p in paired[:to_delete]]
            delete_document(collection_name, ids=delete_ids)
            logger.debug(f"[하이브리드] 오래된 대화 {to_delete}건 삭제 (farm={farm_id})")

    except Exception as e:
        logger.debug(f"[하이브리드] 대화 수명관리 실패: {e}")


async def _call_llm_with_timeout(full_query, farm_name, default_tool_args, conversation_history,
                                  speech_style=None, progress_queue=None):
    return await asyncio.wait_for(
        asyncio.to_thread(
            get_llm_response_with_tools,
            user_query=full_query,
            farm_name=farm_name,
            default_tool_args=default_tool_args,
            conversation_history=conversation_history,
            speech_style=speech_style,
            progress_queue=progress_queue,
        ),
        timeout=_LLM_TIMEOUT,
    )


# ════════════════════════════════════════════════════════════
# LLM 결과를 (response_text, sources, tools_used, response_type) 튜플로 언패킹
# ════════════════════════════════════════════════════════════
def _unpack_llm_result(result):
    if isinstance(result, dict):
        return (
            result.get("response", ""),
            result.get("sources", []),
            result.get("tools_used", []),
            result.get("response_type", "general"),
        )
    return (str(result), [], [], "general")


# ════════════════════════════════════════════════════════════
# 3단계 파이프라인 모드 설정
# USE_3STAGE_PIPELINE=true 환경변수로 활성화
# 기존 Tool Use 루프는 fallback으로 항상 보존
# ════════════════════════════════════════════════════════════
_USE_3STAGE_PIPELINE = os.getenv("USE_3STAGE_PIPELINE", "false").lower() == "true"


def _run_3stage_pipeline_sync(user_query, full_query, farm_id, house_id, farm_name,
                              default_tool_args, conversation_history, speech_style,
                              progress_queue=None):
    """
    3단계 분리형 파이프라인 실행 (동기 함수 — asyncio.to_thread()로 호출)
    1단계: 질문유형분석 → 2단계: 데이터수집+검증 → 3단계: 답변작성

    기존 Tool Use 루프를 대체하며, 실패 시 기존 루프로 fallback.
    """
    from agri_ai_core.src.ai.pipeline.question_analyzer import analyze_question
    from agri_ai_core.src.ai.pipeline.data_collector import DataCollector
    from agri_ai_core.src.ai.pipeline.answer_generator import generate_answer
    from agri_ai_core.src.ai.llm_client import _build_farm_info_text, _report_progress

    t0 = time.time()

    # 진행 상태 콜백 (스트리밍용)
    def _progress(message, phase, tool_name=None):
        _report_progress(progress_queue, message, phase, tool_name=tool_name)

    try:
        # [1단계] 질문유형분석
        _progress("질문을 분석하고 있습니다...", "analyzing")
        logger.info("[3단계파이프라인] === 1단계: 질문유형분석 시작 ===")

        # 대화 컨텍스트를 텍스트로 변환 (1단계 분석기에 전달)
        ctx_for_analyzer = conversation_history

        analysis = analyze_question(
            user_query=full_query,
            conversation_context=ctx_for_analyzer,
            farm_id=farm_id,
            house_id=house_id,
        )

        question_type = analysis.get("question_type", "general")
        logger.info(f"[3단계파이프라인] 1단계 완료: type={question_type} 도구={len(analysis.get('required_data', []))}개")

        # greeting/conversation_ref는 도구 불필요 → 2단계 스킵
        if question_type in ("greeting", "conversation_ref"):
            logger.info(f"[3단계파이프라인] 2단계 스킵 (type={question_type}, 도구 불필요)")
            collected = {"data": [], "sources": [], "tools_used": [], "sufficient": True}
        else:
            # [2단계] 데이터 수집 + 검증
            logger.info("[3단계파이프라인] === 2단계: 데이터수집 시작 ===")
            _progress("필요한 데이터를 수집하고 있습니다...", "data_collecting")

            collector = DataCollector(
                default_tool_args=default_tool_args,
                progress_callback=_progress,
            )
            collected = collector.collect(analysis)

            logger.info(
                f"[3단계파이프라인] 2단계 완료: "
                f"데이터={len(collected.get('data', []))}건 "
                f"도구={collected.get('tools_used', [])} "
                f"sufficient={collected.get('sufficient', False)}"
            )

        # [3단계] 답변 작성
        logger.info("[3단계파이프라인] === 3단계: 답변작성 시작 ===")
        _progress("수집된 데이터로 답변을 작성하고 있습니다...", "llm_generating")

        farm_info = _build_farm_info_text()

        result = generate_answer(
            user_query=full_query,
            analysis_result=analysis,
            collected_result=collected,
            conversation_history=conversation_history,
            farm_name=farm_name,
            farm_info=farm_info,
            speech_style=speech_style,
            progress_callback=_progress,
        )

        total_s = time.time() - t0
        logger.info(f"[3단계파이프라인] 전체 완료: {total_s:.1f}s type={result.get('response_type', '?')}")

        return result

    except Exception as e:
        logger.error(f"[3단계파이프라인] 파이프라인 오류, 기존 Tool Use fallback: {e}")
        logger.error(traceback.format_exc())
        # fallback: 기존 Tool Use 루프로 전환
        logger.info("[3단계파이프라인] fallback → 기존 Tool Use 루프 실행")
        return get_llm_response_with_tools(
            user_query=full_query,
            farm_name=farm_name,
            default_tool_args=default_tool_args,
            conversation_history=conversation_history,
            speech_style=speech_style,
            progress_queue=progress_queue,
        )


# ════════════════════════════════════════════════════════════
# 질의 처리 (Tool Use 방식)
# ════════════════════════════════════════════════════════════
async def query_llm_simple(user_query, file_paths=None, farm_id=None, house_id=None,

# (query_llm_simple 파라미터 블록 계속)
                           farm_name=None, house_name=None, session_id=None, speech_style=None,
                           auth_farm_id=None):
    start_time = datetime.now()

    try:
        # [1/3] 사용자 질문
        logger.info(f"[사용자질문] \"{(user_query or '')[:120]}\" (len={len(user_query or '')}, farm={farm_name or '-'})")

        # 웹 로그: 요청 JSON 기록
        request_json = {
            "type": "chat_request",
            "timestamp": start_time.isoformat(),
            "query": user_query,
            "farm_id": farm_id,
            "house_id": house_id,
            "farm_name": farm_name,
            "house_name": house_name,
            "files": [f.get("filename", "") for f in file_paths] if file_paths else [],
        }
        web_logger.info(
            "[Chat 요청]\n%s",
            json.dumps(request_json, ensure_ascii=False, indent=2),
        )

        # 첨부 파일 처리
        full_query = user_query
        if file_paths:
            logger.info(f"[첨부파일] {len(file_paths)}개 파일 처리")
            file_content = process_uploaded_files(file_paths)
            full_query = f"{user_query}\n\n{file_content}"

        default_tool_args = _build_default_tool_args(user_query, farm_id, house_id, auth_farm_id=auth_farm_id)

        # [PERF:대화] 하이브리드 컨텍스트 로드 시간 측정
        _t_ctx = time.time()
        conversation_history = _load_hybrid_context(session_id, user_query, farm_id)
        _ctx_ms = (time.time() - _t_ctx) * 1000
        logger.debug(f"[PERF:대화] 하이브리드컨텍스트로드={_ctx_ms:.0f}ms (session={session_id[:12] if session_id else '-'})")

        # [2/3] LLM 답변 생성
        llm_start = datetime.now()
        try:
            if _USE_3STAGE_PIPELINE:
                # 3단계 분리형 파이프라인 (to_thread로 이벤트루프 블로킹 방지)
                logger.info("[LLM시작] 모드=3단계 파이프라인 (질문분석→데이터수집→답변작성)")
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        _run_3stage_pipeline_sync,
                        user_query=user_query, full_query=full_query,
                        farm_id=farm_id, house_id=house_id, farm_name=farm_name,
                        default_tool_args=default_tool_args,
                        conversation_history=conversation_history,
                        speech_style=speech_style,
                    ),
                    timeout=_LLM_TIMEOUT,
                )
            else:
                # 기존 Tool Use 루프
                logger.info("[LLM시작] 모드=Tool Use (LLM 자율 도구 선택)")
                result = await _call_llm_with_timeout(full_query, farm_name, default_tool_args, conversation_history, speech_style=speech_style)
        except asyncio.TimeoutError:
            logger.error(f"[LLM타임아웃] {_LLM_TIMEOUT}초 초과")
            yield {
                "response": f"죄송합니다. 응답 생성 시간이 초과되었습니다. ({_LLM_TIMEOUT}초)",
                "sources": [],
                "tools_used": [],
                "response_type": "general",
            }
            return

        response_text, sources, tools_used, response_type = _unpack_llm_result(result)

        llm_elapsed = (datetime.now() - llm_start).total_seconds()
        total_elapsed = (datetime.now() - start_time).total_seconds()

        # [3/3] 최종 답변
        logger.info(f"[LLM완료] 답변생성={llm_elapsed:.1f}s type={response_type} tools={tools_used}")
        logger.debug(f"[PERF:대화] 전체파이프라인={total_elapsed:.1f}s (LLM={llm_elapsed:.1f}s, 전처리={total_elapsed - llm_elapsed:.1f}s)")
        answer_preview = (response_text or "")[:200]
        if len(response_text or "") > 200:
            answer_preview += "..."
        logger.info(f"[최종답변] len={len(response_text or '')} 총소요={total_elapsed:.1f}s")
        logger.info(f"[답변내용] {answer_preview}")

        _save_conversation_turn_hybrid(session_id, user_query, response_text, farm_id)

        # 웹 로그: 응답 JSON 기록
        response_json = {
            "type": "chat_response",
            "timestamp": datetime.now().isoformat(),
            "query": user_query,
            "response": response_text,
            "sources": sources,
            "tools_used": tools_used,
            "response_type": response_type,
            "processing_time": round(total_elapsed, 3),
            "farm_name": farm_name,
            "house_name": house_name,
            "session_id": session_id,
        }
        web_logger.info(
            "[Chat 응답]\n%s",
            json.dumps(response_json, ensure_ascii=False, indent=2),
        )

        yield {
            "response": response_text,
            "sources": sources,
            "tools_used": tools_used,
            "response_type": response_type,
        }

    except Exception as e:
        logger.error(f"Tool Use 질의 처리 중 오류 발생: {e}")
        logger.error(traceback.format_exc())
        yield {
            "response": f"에러: 질의 처리 중 문제가 발생했습니다. ({str(e)})",
            "sources": [],
            "tools_used": [],
            "response_type": "general",
        }


# ════════════════════════════════════════════════════════════
# SSE 스트리밍 질의 처리
# ════════════════════════════════════════════════════════════

def _split_for_streaming(text, target_size=30):
    if not text:
        return
    i = 0
    text_len = len(text)
    while i < text_len:
        if i + target_size >= text_len:
            yield text[i:]
            break
        end = i + target_size
        best = -1
        for delim in ['\n', '. ', '? ', '! ', ', ', ' ']:
            pos = text.rfind(delim, i + 5, end + 10)
            if pos > i:
                best = pos + len(delim)
                break
        if best > i:
            yield text[i:best]
            i = best
        else:
            yield text[i:end]
            i = end


async def query_llm_simple_stream(user_query, farm_id=None, house_id=None,
                                   farm_name=None, house_name=None, session_id=None, speech_style=None,
                                   auth_farm_id=None):
    start_time = datetime.now()

    try:
        # [1] 질문 분석
        yield {"type": "status", "content": "질문을 분석하고 있습니다..."}

        logger.info(f"[스트리밍] \"{(user_query or '')[:120]}\" (farm={farm_name or '-'})")
        web_logger.info(
            "[Chat 스트리밍 요청]\n%s",
            json.dumps({
                "type": "chat_stream_request",
                "timestamp": start_time.isoformat(),
                "query": user_query,
                "farm_id": farm_id, "house_id": house_id,
                "farm_name": farm_name, "house_name": house_name,
            }, ensure_ascii=False, indent=2),
        )

        full_query = user_query
        default_tool_args = _build_default_tool_args(user_query, farm_id, house_id, auth_farm_id=auth_farm_id)

        # [PERF:대화] 하이브리드 컨텍스트 로드 시간 측정
        _t_ctx = time.time()
        conversation_history = _load_hybrid_context(session_id, user_query, farm_id, label="스트리밍][")
        _ctx_ms = (time.time() - _t_ctx) * 1000
        logger.debug(f"[PERF:대화] 스트리밍-하이브리드컨텍스트로드={_ctx_ms:.0f}ms")

        # [3] LLM 답변 생성 (progress_queue로 상세 진행 상태 수신)
        from queue import Queue as ThreadQueue, Empty as QueueEmpty
        progress_queue = ThreadQueue()

        yield {"type": "status", "content": "답변을 생성하고 있습니다..."}

        llm_start = datetime.now()
        if _USE_3STAGE_PIPELINE:
            logger.info("[스트리밍] 모드=3단계 파이프라인")
            llm_task = asyncio.create_task(
                asyncio.to_thread(
                    _run_3stage_pipeline_sync,
                    user_query=user_query, full_query=full_query,
                    farm_id=farm_id, house_id=house_id, farm_name=farm_name,
                    default_tool_args=default_tool_args,
                    conversation_history=conversation_history,
                    speech_style=speech_style,
                    progress_queue=progress_queue,
                )
            )
        else:
            logger.info("[스트리밍] 모드=Tool Use")
            llm_task = asyncio.create_task(
                _call_llm_with_timeout(full_query, farm_name, default_tool_args, conversation_history,
                                       speech_style=speech_style, progress_queue=progress_queue)
            )
        # 진행 상태 이력 (도구 호출 정보 등)을 수집하여 대기 중 순환 표시
        _progress_history = []  # 도구/단계 메시지 이력
        _last_progress_msg = ""
        _idle_cycle = 0  # 새 이벤트 없이 반복된 횟수

        # LLM 대기 중 순환 표시할 기본 메시지
        _waiting_messages = [
            "AI가 질문을 분석하고 있습니다...",
            "최적의 답변을 준비하고 있습니다...",
            "정보를 종합하여 답변을 구성하고 있습니다...",
        ]

        while True:
            try:
                result = await asyncio.wait_for(
                    asyncio.shield(llm_task),
                    timeout=_STREAM_HEARTBEAT_SECONDS,
                )
                break
            except asyncio.TimeoutError:
                # LLM 자체 타임아웃이면 즉시 에러 반환
                if llm_task.done():
                    logger.error(f"[스트리밍][LLM타임아웃] {_LLM_TIMEOUT}초 초과")
                    yield {"type": "error", "content": f"응답 생성 시간이 초과되었습니다. ({_LLM_TIMEOUT}초)"}
                    return

                # progress_queue에서 모든 이벤트를 꺼냄
                new_events = []
                try:
                    while True:
                        new_events.append(progress_queue.get_nowait())
                except QueueEmpty:
                    pass

                elapsed_wait = int((datetime.now() - llm_start).total_seconds())

                if new_events:
                    # 새 이벤트가 있으면 최신 것을 표시하고 이력에 추가
                    _idle_cycle = 0
                    for evt in new_events:
                        msg = evt.get("message", "")
                        if msg and msg not in [h.get("message") for h in _progress_history]:
                            _progress_history.append(evt)
                    latest = new_events[-1]
                    _last_progress_msg = latest.get("message", "")
                    # 도구명 + 단계 정보 포함하여 상세 표시
                    _tool_label = ""
                    if latest.get("tool_display"):
                        _iter_str = ""
                        if latest.get("iteration") and latest.get("max_iterations"):
                            _iter_str = f" {latest['iteration']}/{latest['max_iterations']}단계"
                        _tool_label = f"[{latest['tool_display']}{_iter_str}] "
                    yield {
                        "type": "status",
                        "content": f"{_tool_label}{_last_progress_msg} ({elapsed_wait}초 경과)",
                        "phase": latest.get("phase", "processing"),
                        "tool_name": latest.get("tool_name"),
                        "tool_display": latest.get("tool_display"),
                        "iteration": latest.get("iteration"),
                        "max_iterations": latest.get("max_iterations"),
                    }
                else:
                    # 새 이벤트 없음 → 이력/기본 메시지를 순환하며 표시
                    _idle_cycle += 1
                    all_messages = [h.get("message", "") for h in _progress_history if h.get("message")]
                    all_messages.extend(_waiting_messages)
                    cycle_msg = all_messages[_idle_cycle % len(all_messages)] if all_messages else "답변 생성 중입니다..."
                    yield {"type": "status", "content": f"{cycle_msg} ({elapsed_wait}초 경과)"}

        response_text, sources, tools_used, response_type = _unpack_llm_result(result)

        llm_elapsed = (datetime.now() - llm_start).total_seconds()
        total_elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"[스트리밍][LLM완료] 답변생성={llm_elapsed:.1f}s type={response_type} tools={tools_used}")
        logger.debug(f"[PERF:대화] 스트리밍-전체파이프라인={total_elapsed:.1f}s (LLM={llm_elapsed:.1f}s, 전처리={total_elapsed - llm_elapsed:.1f}s)")

        # [4] 응답 텍스트를 청크 단위로 전송 (clean_llm_response는 llm_client 내부에서 이미 처리됨)
        for chunk in _split_for_streaming(response_text):
            yield {"type": "token", "content": chunk}

        # [5] 완료 이벤트
        yield {
            "type": "done",
            "session_id": session_id,
            "sources": sources,
            "tools_used": tools_used,
            "response_type": response_type,
            "elapsed_sec": round(total_elapsed, 1),
        }

        _save_conversation_turn_hybrid(session_id, user_query, response_text, farm_id, label="스트리밍][")

        # 통계 기록
        from agri_ai_core.src.ai.stats_collector import get_stats_collector
        get_stats_collector().record_query(
            success=True,
            processing_time=round(total_elapsed, 3),
            tools_used=tools_used,
            response_type=response_type,
        )

        # 웹 로그
        web_logger.info(
            "[Chat 스트리밍 응답]\n%s",
            json.dumps({
                "type": "chat_stream_response",
                "timestamp": datetime.now().isoformat(),
                "query": user_query,
                "response_length": len(response_text or ""),
                "sources": sources,
                "tools_used": tools_used,
                "response_type": response_type,
                "processing_time": round(total_elapsed, 3),
                "farm_name": farm_name,
                "session_id": session_id,
            }, ensure_ascii=False, indent=2),
        )

    except asyncio.CancelledError:
        logger.warning("[스트리밍] 취소됨 (클라이언트 연결 종료 또는 서버 타임아웃)")
        raise
    except Exception as e:
        logger.error(f"스트리밍 질의 처리 중 오류: {e}")
        logger.error(traceback.format_exc())
        yield {"type": "error", "content": f"질의 처리 중 문제가 발생했습니다. ({str(e)})"}
