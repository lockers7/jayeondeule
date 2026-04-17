# ════════════════════════════════════════════════════════════════════════════════
# 하이브리드 대화 컨텍스트 관리 — VectorDB 검색 + 최근 턴 조합
# query_handler_simple.py에서 분리된 L5 계층 모듈.
# --->
# _classify_topic: 사용자 질문을 주제별로 분류한다 (규칙 기반)
# load_hybrid_context: 직전 N턴 + VectorDB 관련 대화 검색
# _search_related_conversations: VectorDB conversation_collection에서 관련 과거 대화 검색
# save_conversation_turn_hybrid: Q+A 쌍을 PostgreSQL + VectorDB에 저장
# _async_vectordb_save: 백그라운드 VectorDB 임베딩 저장 + 수명 관리
# _prune_old_conversations: farm_id별 최대 N건으로 수명 관리
# ════════════════════════════════════════════════════════════════════════════════
import hashlib
import os
import re
import threading
import time
from datetime import datetime

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.conversation_store import get_conversation_store
from agri_ai_core.src.ai.utils import GREETING_RE as _GREETING_RE_HYBRID

logger = setup_logger(__name__)

# 시스템/가상 농장 ID (관리자 선택 시 전체 대화 검색, 일반 사용자는 자기 농장 + 시스템 농장 대화 검색)
_SYSTEM_FARM_ID = "0"

_HYBRID_RECENT_TURNS = int(os.getenv("HYBRID_RECENT_TURNS", "2"))
_HYBRID_RELATED_RESULTS = int(os.getenv("HYBRID_RELATED_RESULTS", "5"))
_HYBRID_MAX_RECORDS_PER_FARM = int(os.getenv("HYBRID_MAX_RECORDS", "30"))
# VectorDB 관련 대화 검색 거리 임계값 (무관한 과거 대화 컨텍스트 유입 방지)
_CONVERSATION_MAX_DISTANCE = float(os.getenv("CONV_VECTOR_MAX_DISTANCE", "3.0"))


# ═════════════════════════════════════════════════════════════
# 대화 주제 분류 (규칙 기반, LLM 호출 불필요)
# VectorDB 저장 시 topic 메타데이터로 추가하여 검색 정확도 향상
# ═════════════════════════════════════════════════════════════
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
# 하이브리드 대화 컨텍스트: 직전 N턴 + VectorDB 관련 대화 검색
# ════════════════════════════════════════════════════════════
def load_hybrid_context(session_id, user_query, farm_id, label=""):
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


# ══════════════════════════════════════════════════════════
# VectorDB conversation_collection에서 관련 과거 대화를 검색
# ══════════════════════════════════════════════════════════
def _search_related_conversations(user_query, farm_id):
    try:
        from agri_ai_core.src.ai.embedder import embed_text
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


# ═════════════════════════════════════════════════
# 대화 턴 저장: PostgreSQL(동기) + VectorDB(비동기)
# ═════════════════════════════════════════════════
def save_conversation_turn_hybrid(session_id, user_query, response_text, farm_id=None, label=""):
    if not session_id:
        return

    # [1] PostgreSQL 저장 (기존 동기 방식)
    # DB 저장 전 SPECIAL 내부 마커 제거 (오염 방지)
    _clean_response = re.sub(r'<SPECIAL_\d+>.*?(?=\n|$)', '', response_text or '', flags=re.DOTALL | re.IGNORECASE)
    _clean_response = re.sub(r'</?SPECIAL[^>]*>', '', _clean_response, flags=re.IGNORECASE).strip()
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


# ═══════════════════════════════════════════════════════
# 백그라운드: Q+A 쌍을 VectorDB에 임베딩 저장 + 수명 관리
# ═══════════════════════════════════════════════════════
def _async_vectordb_save(session_id, user_query, response_text, farm_id):
    try:
        from agri_ai_core.src.ai.embedder import embed_text
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


# ═══════════════════════════════════════
# farm_id별 대화 기록을 최대 N건으로 유지
# ═══════════════════════════════════════
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
