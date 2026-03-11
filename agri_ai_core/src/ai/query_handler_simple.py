# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 쿼리 핸들러 (Tool Use 방식)
# LLM이 필요한 도구를 자율적으로 선택하고 실행하여 사용자 질문 처리
# --->
# _dedupe_list: 공통 헬퍼 함수
# _build_default_tool_args: 도구별 기본 인자 생성
# _load_hybrid_context: 하이브리드 대화 컨텍스트: 직전 N턴 + VectorDB 관련 대화 검색
#   - _CONVERSATION_MAX_DISTANCE: VectorDB 거리 임계값 (3.0, 환경변수 CONV_VECTOR_MAX_DISTANCE)
#   - VectorDB 검색 결과 중복 제거 (_seen_queries 셋으로 동일 질문 필터링)
# _search_related_conversations: VectorDB conversation_collection에서 관련 과거 대화를 검색
# _save_conversation_turn_hybrid: 대화 턴 저장: PostgreSQL(동기) + VectorDB(비동기/동기 선택)
#   - SYNC_VECTORDB_SAVE=true 환경변수로 동기 저장 전환 가능
# _async_vectordb_save: 백그라운드: Q+A 쌍을 VectorDB에 임베딩 저장 + 수명 관리
#   - 저장 실패 시 warning 레벨 로그 출력
# _prune_old_conversations: farm_id별 대화 기록을 최대 N건으로 유지
# _call_llm_with_timeout: LLM 호출 (타임아웃 포함)
# _unpack_llm_result: LLM 결과를 (response_text, sources, tools_used, response_type) 튜플로 언패킹
# query_llm_simple: 질의 처리 (Tool Use 방식)
# _split_for_streaming: SSE 스트리밍 질의 처리
# query_llm_simple_stream: SSE 스트리밍 질의 처리 (비동기 제너레이터)
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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

_LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SECONDS", "600"))
_STREAM_HEARTBEAT_SECONDS = max(3, int(os.getenv("STREAM_HEARTBEAT_SECONDS", "5")))


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 공통 헬퍼 함수
# 공통 중복 제거 헬퍼
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ============================================================
# 도구별 기본 인자 생성
# ============================================================
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


def _build_default_tool_args(user_query, farm_id, house_id):
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

    return {
        "search_web": {"query": user_query},
        "search_farm_knowledge": {
            "query": user_query,
            "n_results": 5,
            "file_name": detected_file_name,
            "farm_id": str(farm_id) if farm_id is not None else None,
            "house_id": str(house_id) if house_id is not None else None,
        },
        "get_farm_realtime_data": {
            "farm_id": str(farm_id) if farm_id is not None else None,
            "house_id": str(house_id) if house_id is not None else None,
            "data_type": "all",
        },
    }


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 하이브리드 대화 컨텍스트 (VectorDB + 최근 턴)
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
_HYBRID_RECENT_TURNS = int(os.getenv("HYBRID_RECENT_TURNS", "2"))
_HYBRID_RELATED_RESULTS = int(os.getenv("HYBRID_RELATED_RESULTS", "5"))
_HYBRID_MAX_RECORDS_PER_FARM = int(os.getenv("HYBRID_MAX_RECORDS", "30"))
# VectorDB 관련 대화 검색 거리 임계값 (기존 16.0 → 3.0: 무관한 과거 대화 컨텍스트 유입 방지)
_CONVERSATION_MAX_DISTANCE = float(os.getenv("CONV_VECTOR_MAX_DISTANCE", "3.0"))


# ============================================================
# 하이브리드 대화 컨텍스트: 직전 N턴 + VectorDB 관련 대화 검색
# ============================================================
def _load_hybrid_context(session_id, user_query, farm_id, label=""):
    if not session_id:
        return None

    store = get_conversation_store()

    # [1] 직전 2턴 (즉시 맥락: "이거", "아까 그거" 참조 보장)
    recent_turns = store.get_recent_turns(session_id, n_turns=_HYBRID_RECENT_TURNS)

    # [2] VectorDB에서 관련 과거 대화 검색
    related_context = _search_related_conversations(user_query, farm_id)

    # [3] 하이브리드 컨텍스트 조합
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


# ============================================================
# VectorDB conversation_collection에서 관련 과거 대화를 검색
# ============================================================
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

        # farm_id 기반 필터
        if farm_id:
            where_filter = {
                "$and": [
                    {"farm_id": {"$eq": str(farm_id)}},
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
        lines = []
        _seen_queries: set = set()
        for idx, doc in enumerate(documents):
            dist = distances[idx] if idx < len(distances) else None
            if dist is not None and dist > _CONVERSATION_MAX_DISTANCE:
                continue
            meta = metadatas[idx] if idx < len(metadatas) else {}
            record_dt = (meta or {}).get("record_datetime", "")[:10]
            # 과거 답변을 포함하면 LLM이 도구 호출 없이 복사하므로 질문만 추출
            query_preview = (meta or {}).get("query_preview", "")
            if not query_preview:
                raw = (doc or "")
                if raw.startswith("질문:"):
                    query_preview = raw.split("\n답변:")[0].replace("질문:", "").strip()[:200]
                else:
                    query_preview = raw[:200]
            if query_preview:
                # 중복 질문 제거
                _preview_key = query_preview.strip()[:50]
                if _preview_key in _seen_queries:
                    continue
                _seen_queries.add(_preview_key)
                lines.append(f"- ({record_dt}) 질문: {query_preview}")

        if not lines:
            return None

        logger.info(f"[하이브리드] 관련 대화 {len(lines)}건 검색됨 (farm={farm_id})")
        return "\n".join(lines[:_HYBRID_RELATED_RESULTS])

    except Exception as e:
        logger.debug(f"[하이브리드] 관련 대화 검색 실패: {e}")
        return None


# ============================================================
# 대화 턴 저장: PostgreSQL(동기) + VectorDB(비동기)
# ============================================================
def _save_conversation_turn_hybrid(session_id, user_query, response_text, farm_id=None, label=""):
    if not session_id:
        return

    # [1] PostgreSQL 저장 (기존 동기 방식)
    store = get_conversation_store()
    store.add_turn(session_id, "user", user_query, farm_id)
    store.add_turn(session_id, "assistant", response_text, farm_id)
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


# ============================================================
# 백그라운드: Q+A 쌍을 VectorDB에 임베딩 저장 + 수명 관리
# ============================================================
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

        doc_id_hash = hashlib.md5(
            f"{farm_id}_{session_id}_{time.time()}".encode()
        ).hexdigest()[:16]
        doc_id = f"conv_turn_{doc_id_hash}"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        docs = [{
            "doc_id": doc_id,
            "text": combined_text,
            "metadata": {
                "farm_id": str(farm_id) if farm_id else "",
                "session_id": session_id,
                "data_kind": "conversation_turn",
                "record_datetime": now_str,
                "query_preview": user_query[:100],
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


# ============================================================
# farm_id별 대화 기록을 최대 N건으로 유지
# LLM 호출 + 타임아웃 처리
# ============================================================
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


# ============================================================
# LLM 결과를 (response_text, sources, tools_used, response_type) 튜플로 언패킹
# ============================================================
def _unpack_llm_result(result):
    if isinstance(result, dict):
        return (
            result.get("response", ""),
            result.get("sources", []),
            result.get("tools_used", []),
            result.get("response_type", "general"),
        )
    return (str(result), [], [], "general")


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 질의 처리 (Tool Use 방식)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def query_llm_simple(user_query, file_paths=None, farm_id=None, house_id=None,

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Tool Use를 사용한 질의 처리
# LLM이 필요한 도구를 자율적으로 선택하고 호출하여 답변 생성
# Args: user_query: 사용자 질의
#       file_paths: 첨부 파일 경로
#       farm_id: 농장 ID
#       house_id: 재배사 ID
#       farm_name: 농장명
#       house_name: 재배사명
#       session_id: 대화 세션 ID (멀티턴 대화용)
#       speech_style: 대화체 (male/female)
# Returns: dict: 구조화된 응답 {response, sources, tools_used, response_type}
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
                           farm_name=None, house_name=None, session_id=None, speech_style=None):
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

        default_tool_args = _build_default_tool_args(user_query, farm_id, house_id)

        # [PERF:대화] 하이브리드 컨텍스트 로드 시간 측정
        _t_ctx = time.time()
        conversation_history = _load_hybrid_context(session_id, user_query, farm_id)
        _ctx_ms = (time.time() - _t_ctx) * 1000
        logger.debug(f"[PERF:대화] 하이브리드컨텍스트로드={_ctx_ms:.0f}ms (session={session_id[:12] if session_id else '-'})")

        # [2/3] LLM 답변 생성 (LLM이 도구 자율 선택)
        llm_start = datetime.now()
        logger.info("[LLM시작] 모드=Tool Use (LLM 자율 도구 선택)")
        try:
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# SSE 스트리밍 질의 처리
# 도구 실행 중 status 이벤트, 답변 텍스트 token 이벤트, 완료 done 이벤트를 yield
# 텍스트를 스트리밍 전송에 적합한 작은 청크로 분할
# SSE 스트리밍 질의 처리.
# yield 이벤트 형식:
# {"type": "status",  "content": "상태 메시지"}
# {"type": "token",   "content": "텍스트 청크"}
# {"type": "done",    "session_id": "...", "sources": [...], "tools_used": [...], "response_type": "..."}
# {"type": "error",   "content": "에러 메시지"}
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

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
                                   farm_name=None, house_name=None, session_id=None, speech_style=None):
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
        default_tool_args = _build_default_tool_args(user_query, farm_id, house_id)

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
                    yield {
                        "type": "status",
                        "content": f"{_last_progress_msg} ({elapsed_wait}초 경과)",
                        "phase": latest.get("phase", "processing"),
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

    except Exception as e:
        logger.error(f"스트리밍 질의 처리 중 오류: {e}")
        logger.error(traceback.format_exc())
        yield {"type": "error", "content": f"질의 처리 중 문제가 발생했습니다. ({str(e)})"}
