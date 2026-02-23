# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 대화 히스토리 저장소
# session_id별 최근 N턴 대화를 메모리에 저장하여 멀티턴 대화를 지원한다.
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import threading
import time
from typing import Dict, List, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

# 기본 설정
MAX_TURNS = 10          # session당 최대 저장 턴 수
TTL_SECONDS = 30 * 60   # 30분 비활성 시 자동 삭제


class _SessionData:
    __slots__ = ("turns", "last_access")

    def __init__(self):
        self.turns: List[Dict[str, str]] = []
        self.last_access: float = time.time()


class ConversationStore:
    def __init__(self, max_turns: int = MAX_TURNS, ttl_seconds: int = TTL_SECONDS):
        self._store: Dict[str, _SessionData] = {}
        self._lock = threading.Lock()
        self._max_turns = max_turns
        self._ttl = ttl_seconds

    def add_turn(self, session_id: str, role: str, content: str) -> None:
        """대화 턴을 추가한다. role은 'user' 또는 'assistant'."""
        with self._lock:
            self._evict_expired()
            if session_id not in self._store:
                self._store[session_id] = _SessionData()
                logger.info(f"[대화저장소] 새 세션 생성: {session_id[:12]}...")

            session = self._store[session_id]
            session.turns.append({"role": role, "content": content})
            session.last_access = time.time()

            # 최대 턴 수 초과 시 오래된 턴 제거 (user+assistant 쌍 단위로)
            if len(session.turns) > self._max_turns * 2:
                overflow = len(session.turns) - self._max_turns * 2
                # 쌍 단위로 삭제 (홀수면 +1)
                if overflow % 2 != 0:
                    overflow += 1
                session.turns = session.turns[overflow:]
                logger.debug(f"[대화저장소] 세션 {session_id[:12]}: 오래된 {overflow}개 턴 삭제")

    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        """세션의 대화 히스토리를 반환한다. 없으면 빈 리스트."""
        with self._lock:
            session = self._store.get(session_id)
            if session is None:
                return []
            session.last_access = time.time()
            return list(session.turns)

    def clear_session(self, session_id: str) -> None:
        """특정 세션을 삭제한다."""
        with self._lock:
            if session_id in self._store:
                del self._store[session_id]
                logger.info(f"[대화저장소] 세션 삭제: {session_id[:12]}...")

    def session_count(self) -> int:
        """활성 세션 수를 반환한다."""
        with self._lock:
            self._evict_expired()
            return len(self._store)

    def _evict_expired(self) -> None:
        """TTL 초과된 세션을 제거한다. _lock 안에서 호출."""
        now = time.time()
        expired = [
            sid for sid, data in self._store.items()
            if now - data.last_access > self._ttl
        ]
        for sid in expired:
            del self._store[sid]
        if expired:
            logger.info(f"[대화저장소] 만료 세션 {len(expired)}개 삭제 (TTL={self._ttl}s)")


# 글로벌 싱글톤 인스턴스
_global_store: Optional[ConversationStore] = None
_store_lock = threading.Lock()


def get_conversation_store() -> ConversationStore:
    """글로벌 ConversationStore 싱글톤을 반환한다."""
    global _global_store
    if _global_store is None:
        with _store_lock:
            if _global_store is None:
                _global_store = ConversationStore()
                logger.info(f"[대화저장소] 초기화 완료 (max_turns={MAX_TURNS}, ttl={TTL_SECONDS}s)")
    return _global_store
