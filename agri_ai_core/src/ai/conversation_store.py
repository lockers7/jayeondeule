# ════════════════════════════════════════════════════════════════════
# 대화 히스토리 저장소 — PostgreSQL 영속 + 인메모리 폴백 멀티턴 지원.
# MAX_TURNS 초과 시 오래된 턴 LLM 요약 → conversation_collection 영속화.
# --->
# _SessionData             : 인메모리 폴백용 세션 데이터 (turns, last_access)
# ConversationStore        : 대화 저장 메인 클래스
#   __init__               : 초기화 + DB 가용성 탐지
#   _init_db               : PostgreSQL 테이블/인덱스 생성 + TTL 정리
#   add_turn               : 대화 턴 추가 (DB 우선, 실패 시 메모리)
#   get_history            : 세션의 전체 히스토리 반환 (요약 처리 포함)
#   get_recent_turns       : 최근 N턴(Q+A 쌍)만 반환 (하이브리드 컨텍스트용)
#   _db_get_recent_turns   : DB 경로 최근 턴 조회
#   _memory_get_recent_turns : 메모리 폴백 최근 턴 조회
#   _db_add_turn           : DB 경로 INSERT
#   _db_get_history        : DB 경로 전체 조회 + 오버플로우 요약 처리
#   _summarize_old_turns   : 오래된 턴 LLM 요약 (qwen3 + 태그 정제)
#   _delete_old_turns      : 오래된 턴 N개 PostgreSQL 삭제 (무한 누적 방지)
#   _store_summary_to_vectordb : 요약을 conversation_collection 에 임베딩 저장
#   _memory_add_turn       : 메모리 경로 add (TTL eviction 포함)
#   _memory_get_history    : 메모리 경로 전체 조회
#   _evict_expired         : TTL 초과 인메모리 세션 제거
# get_conversation_store   : 글로벌 ConversationStore 싱글톤 반환
# ════════════════════════════════════════════════════════════════════
import os
import re
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

# 기본 설정
MAX_TURNS = int(os.getenv("CONVERSATION_MAX_TURNS", "10"))
TTL_DAYS = int(os.getenv("CONVERSATION_TTL_DAYS", "7"))
MEMORY_TTL_SECONDS = 30 * 60  # 인메모리 폴백용 TTL (30분)

from agri_ai_core.src.ai.utils import RE_THINK_TAG as _RE_THINK_TAG


# ═══════════════════════════
# 인메모리 폴백용 세션 데이터
# ═══════════════════════════
class _SessionData:
    __slots__ = ("turns", "last_access")

    # ────────────────────────────────────────────────────────────────
    # 인메모리 세션 1건 — 빈 turns 리스트 + 현재 시각 last_access.
    # ────────────────────────────────────────────────────────────────
    def __init__(self):
        self.turns: List[Dict[str, str]] = []
        self.last_access: float = time.time()


class ConversationStore:
    # ────────────────────────────────────────────────────────────────
    # 초기화 — max_turns/ttl_days 설정 + DB 가용성 탐지 + 메모리 폴백 준비.
    # ────────────────────────────────────────────────────────────────
    def __init__(self, max_turns: int = MAX_TURNS, ttl_days: int = TTL_DAYS):
        self._max_turns = max_turns
        self._ttl_days = ttl_days
        self._db_available = False

        # 인메모리 폴백
        self._memory_store: Dict[str, _SessionData] = {}
        self._lock = threading.Lock()

        # PostgreSQL 초기화 시도
        self._init_db()

    # ────────────────────────────────────────────────────────────────
    # PostgreSQL 테이블/인덱스 생성 + TTL_DAYS 초과 데이터 정리.
    # 실패 시 _db_available=False 로 폴백 모드.
    # ────────────────────────────────────────────────────────────────
    def _init_db(self):
        try:
            from agri_ai_core.src.postgresql.connection import db_session
            from agri_ai_core.src.postgresql import queries as dbQry

            with db_session() as database:
                database.execute_query(dbQry.CREATE_AI_CONVERSATION_TABLE)
                database.execute_query(dbQry.CREATE_AI_CONVERSATION_INDEX_SESSION)
                database.execute_query(dbQry.CREATE_AI_CONVERSATION_INDEX_CREATED)

                # 오래된 대화 정리
                database.execute_query(
                    dbQry.DELETE_AI_CONVERSATION_EXPIRED,
                    (str(self._ttl_days),),
                )

            self._db_available = True
            logger.info("[대화저장소] PostgreSQL 초기화 완료")
        except Exception as e:
            self._db_available = False
            logger.warning(f"[대화저장소] PostgreSQL 초기화 실패, 인메모리 폴백 사용: {e}")

    # ────────────────────────────────────────────────────────────────
    # 대화 턴 추가 — role 은 'user' 또는 'assistant'.
    # DB 우선, 실패 시 인메모리 폴백.
    # ────────────────────────────────────────────────────────────────
    def add_turn(self, session_id: str, role: str, content: str, farm_id: str = None) -> None:
        if self._db_available:
            try:
                self._db_add_turn(session_id, role, content, farm_id)
                return
            except Exception as e:
                logger.warning(f"[대화저장소] DB 저장 실패, 인메모리 폴백: {e}")

        self._memory_add_turn(session_id, role, content)

    # ────────────────────────────────────────────────────────────────
    # 세션의 대화 히스토리 반환. 없으면 빈 리스트. DB 우선, 메모리 폴백.
    # ────────────────────────────────────────────────────────────────
    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        if self._db_available:
            try:
                return self._db_get_history(session_id)
            except Exception as e:
                logger.warning(f"[대화저장소] DB 조회 실패, 인메모리 폴백: {e}")

        return self._memory_get_history(session_id)

    # ────────────────────────────────────────────────────────────────
    # 최근 N턴(Q+A 쌍) 만 반환 — 하이브리드 컨텍스트용. DB 우선, 메모리 폴백.
    # ────────────────────────────────────────────────────────────────
    def get_recent_turns(self, session_id: str, n_turns: int = 2) -> List[Dict[str, str]]:
        if self._db_available:
            try:
                return self._db_get_recent_turns(session_id, n_turns)
            except Exception as e:
                logger.warning(f"[대화저장소] DB 최근턴 조회 실패: {e}")
        return self._memory_get_recent_turns(session_id, n_turns)

    # ────────────────────────────────────────────────────────────────
    # DB 경로 최근 턴 조회 — RECENT_TURNS SQL 사용 (n_turns*2 개 row).
    # ────────────────────────────────────────────────────────────────
    def _db_get_recent_turns(self, session_id, n_turns):
        from agri_ai_core.src.postgresql.connection import db_session
        from agri_ai_core.src.postgresql import queries as dbQry

        with db_session() as database:
            rows = database.fetch_all(
                dbQry.GET_AI_CONVERSATION_RECENT_TURNS,
                (session_id, n_turns * 2),
                as_dict=True,
            )
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    # ────────────────────────────────────────────────────────────────
    # 메모리 폴백 최근 턴 조회 — turns 의 마지막 n_turns*2 항목 반환.
    # ────────────────────────────────────────────────────────────────
    def _memory_get_recent_turns(self, session_id, n_turns):
        with self._lock:
            session = self._memory_store.get(session_id)
            if session is None:
                return []
            count = min(n_turns * 2, len(session.turns))
            return list(session.turns[-count:])

    # ────────────────────────────────────────────────────────────────
    # DB 경로 INSERT — INSERT_AI_CONVERSATION_TURN 1건 실행.
    # ────────────────────────────────────────────────────────────────
    def _db_add_turn(self, session_id, role, content, farm_id=None):
        from agri_ai_core.src.postgresql.connection import db_session
        from agri_ai_core.src.postgresql import queries as dbQry

        with db_session() as database:
            database.execute_query(
                dbQry.INSERT_AI_CONVERSATION_TURN,
                (session_id, role, content, farm_id),
            )

    # ────────────────────────────────────────────────────────────────
    # DB 경로 전체 조회 + MAX_TURNS 초과 시 오래된 턴 요약 → 삭제 → 최근만 반환.
    # 요약 실패해도 삭제는 수행 (무한 누적 방지).
    # ────────────────────────────────────────────────────────────────
    def _db_get_history(self, session_id):
        from agri_ai_core.src.postgresql.connection import db_session
        from agri_ai_core.src.postgresql import queries as dbQry

        with db_session() as database:
            rows = database.fetch_all(
                dbQry.GET_AI_CONVERSATION_HISTORY,
                (session_id,),
                as_dict=True,
            )

        # MAX_TURNS 초과 시 오래된 턴을 요약 → conversation_collection 저장
        # 요약 실패 시에도 오래된 턴을 PostgreSQL에서 삭제하여 무한 누적 방지
        if len(rows) > self._max_turns * 2:
            overflow_count = len(rows) - self._max_turns * 2
            if overflow_count % 2 != 0:
                overflow_count += 1
            old_turns = rows[:overflow_count]
            recent_rows = rows[overflow_count:]

            # 요약 시도
            summary = self._summarize_old_turns(session_id, old_turns)

            # 요약 성공/실패 무관하게 오래된 턴 PostgreSQL에서 삭제 (무한 누적 방지)
            self._delete_old_turns(session_id, overflow_count)

            if summary:
                result = [{"role": "system", "content": f"[이전 대화 요약] {summary}"}]
                result.extend({"role": r["role"], "content": r["content"]} for r in recent_rows)
                return result

            rows = recent_rows

        return [{"role": r["role"], "content": r["content"]} for r in rows]

    # ────────────────────────────────────────────────────────────────
    # 오래된 대화 턴을 LLM 으로 요약하고 conversation_collection 에 임베딩 저장.
    # 요약 규칙: 사용자 질문 주제만 보존, AI 답변의 구체적 수치(온도/가격 등) 제외.
    # 4문장 이내, num_predict=200 으로 충분한 요약 공간 확보. <think> 태그 정제.
    # ────────────────────────────────────────────────────────────────
    def _summarize_old_turns(self, session_id: str, old_turns: list) -> Optional[str]:
        try:
            from agri_ai_core.src.ai.mcp_client import mcp_http_request
            from agri_ai_core.config import settings, get_ollama_url

            # 대화 텍스트 구성
            dialogue = "\n".join(
                f"{t.get('role','?')}: {t.get('content','')[:200]}" for t in old_turns
            )
            if not dialogue.strip():
                return None

            ollama_url = get_ollama_url()
            model_name = (
                getattr(settings.model, "model_name", None)
                or os.getenv("LLM_MODEL_NAME")
                or "qwen3:32b"
            )

            # 대화 요약 프롬프트: 사용자 질문 주제만 보존, LLM 답변 수치는 제외 (시간 경과로 변함)
            prompt = (
                f"아래 대화를 4문장 이내로 요약하세요. 규칙:\n"
                f"- 사용자가 질문한 주제와 키워드를 포함하세요\n"
                f"- AI 답변의 구체적 수치(온도, 가격 등)는 제외하세요 (시간 경과로 변함)\n"
                f"- 한국어로 작성하세요\n\n"
                f"{dialogue[:2500]}\n\n"
                f"/no_think\n"
                f"요약:"
            )

            status, data, _ = mcp_http_request(
                method="POST",
                url=f"{ollama_url}/api/generate",
                json_body={
                    "model": model_name,
                    "prompt": prompt,
                    "stream": False,
                    "keep_alive": -1,  # GPU 영구 상주 보장
                    "options": {"temperature": 0, "num_predict": 200},
                },
                timeout=20,
            )

            if status != 200 or not data:
                return None

            summary = data.get("response", "").strip() if isinstance(data, dict) else ""
            if not summary:
                return None

            # <think>/<thinking> 태그 오염 제거 (qwen3 모델이 생성할 수 있음)
            summary = _RE_THINK_TAG.sub("", summary)
            summary = summary.strip()
            if not summary:
                return None

            # conversation_collection에 임베딩 저장
            self._store_summary_to_vectordb(session_id, summary)

            logger.debug(f"[대화저장소] 대화 요약 완료 ({len(old_turns)}턴→{len(summary)}자)")
            return summary

        except Exception as e:
            logger.debug(f"[대화저장소] 대화 요약 실패: {e}")
            return None

    # ────────────────────────────────────────────────────────────────
    # MAX_TURNS 초과 시 오래된 턴 N개를 PostgreSQL 에서 삭제.
    # 요약 성공/실패 무관 — 무한 누적 방지.
    # ────────────────────────────────────────────────────────────────
    def _delete_old_turns(self, session_id: str, count: int):
        try:
            from agri_ai_core.src.postgresql.connection import db_session
            from agri_ai_core.src.postgresql import queries as dbQry

            with db_session() as database:
                database.execute_query(
                    dbQry.DELETE_AI_CONVERSATION_OLD_TURNS,
                    (session_id, count),
                )
            logger.info(f"[대화저장소] 오래된 턴 {count}개 삭제 완료 (session={session_id[:12]}...)")
        except Exception as e:
            logger.warning(f"[대화저장소] 오래된 턴 삭제 실패: {e}")

    # ────────────────────────────────────────────────────────────────
    # 대화 요약을 conversation_collection 에 임베딩 저장.
    # md5 해시 기반 doc_id, summary_length 메타데이터 부착.
    # ────────────────────────────────────────────────────────────────
    def _store_summary_to_vectordb(self, session_id: str, summary: str):
        try:
            from agri_ai_core.src.ai.embedder import embed_text
            from agri_ai_core.src.chroma.collections import conversation_collection
            from agri_ai_core.src.chroma.operations import upsert_documents_with_embedding

            collection_name = conversation_collection()
            if not collection_name:
                return

            embedding = embed_text(summary)
            if not embedding:
                return

            import hashlib
            doc_id = hashlib.md5(f"{session_id}_{time.time()}".encode()).hexdigest()[:16]
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            upsert_documents_with_embedding(
                collection_name=collection_name,
                ids=[f"conv_summary_{doc_id}"],
                documents=[summary],
                embeddings=[embedding],
                metadatas=[{
                    "session_id": session_id,
                    "data_kind": "conversation_summary",
                    "record_datetime": now_str,
                    "summary_length": len(summary),
                }],
            )
            logger.debug(f"[대화저장소] 대화 요약 VectorDB 저장 완료: {doc_id}")

        except Exception as e:
            logger.debug(f"[대화저장소] 대화 요약 VectorDB 저장 실패: {e}")

    # ────────────────────────────────────────────────────────────────
    # 메모리 폴백 add — TTL 청소 후 turns 에 append, 초과분 trim.
    # ────────────────────────────────────────────────────────────────
    def _memory_add_turn(self, session_id, role, content):
        with self._lock:
            self._evict_expired()
            if session_id not in self._memory_store:
                self._memory_store[session_id] = _SessionData()
                logger.info(f"[대화저장소] 새 세션 생성 (메모리): {session_id[:12]}...")

            session = self._memory_store[session_id]
            session.turns.append({"role": role, "content": content})
            session.last_access = time.time()

            # 최대 턴 수 초과 시 오래된 턴 제거 (user+assistant 쌍 단위로)
            if len(session.turns) > self._max_turns * 2:
                overflow = len(session.turns) - self._max_turns * 2
                if overflow % 2 != 0:
                    overflow += 1
                session.turns = session.turns[overflow:]

    # ────────────────────────────────────────────────────────────────
    # 메모리 폴백 전체 조회 — last_access 갱신 후 turns 사본 반환.
    # ────────────────────────────────────────────────────────────────
    def _memory_get_history(self, session_id):
        with self._lock:
            session = self._memory_store.get(session_id)
            if session is None:
                return []
            session.last_access = time.time()
            return list(session.turns)

    # ────────────────────────────────────────────────────────────────
    # TTL 초과된 인메모리 세션 제거. _lock 안에서 호출 필요 (caller 보장).
    # ────────────────────────────────────────────────────────────────
    def _evict_expired(self):
        now = time.time()
        expired = [
            sid for sid, data in self._memory_store.items()
            if now - data.last_access > MEMORY_TTL_SECONDS
        ]
        for sid in expired:
            del self._memory_store[sid]
        if expired:
            logger.info(f"[대화저장소] 만료 메모리 세션 {len(expired)}개 삭제")


# 글로벌 싱글톤 인스턴스
_global_store: Optional[ConversationStore] = None
_store_lock = threading.Lock()


# ────────────────────────────────────────────────────────────────────
# 글로벌 ConversationStore 싱글톤 반환 (lazy init + double-checked lock).
# ────────────────────────────────────────────────────────────────────
def get_conversation_store() -> ConversationStore:
    global _global_store
    if _global_store is None:
        with _store_lock:
            if _global_store is None:
                _global_store = ConversationStore()
                logger.info(
                    f"[대화저장소] 초기화 완료 (max_turns={MAX_TURNS}, ttl_days={TTL_DAYS}, "
                    f"db={'PostgreSQL' if _global_store._db_available else '인메모리'})"
                )
    return _global_store
