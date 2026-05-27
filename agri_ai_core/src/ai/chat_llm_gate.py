# ══════════════════════════════════════════════════════════════════════════════
# 대화(채팅) LLM 우선순위 게이트
# 농장제어(control) · agent 의 LLM 연속 가동이 절대 기본 — 대화는 항상 양보한다.
# 실제 Ollama 호출 시점의 상호배제는 llm_transport._ollama_chat 의
# llm_call_lock("chat", ...) 이 담당(인프라 재사용). 본 모듈은 그 앞단에서:
#   · 제어/agent 가동 중이면 대화 시작을 잠시 미루고(양보) 사용자에게 안내
#   · 티어(admin/user) 별 대기슬롯 1개만 유지 — 새 요청 도착 시 이전 대기요청
#     은 취소하고 사용자에게 취소 사실을 알림("최근 1건만 유지")
#   · 관리자(auth_farm_id=None) 강제지시는 일반 사용자 대화보다 우선 처리
#
# 단일 FastAPI 프로세스(uvicorn 단일 워커) 전제 — 프로세스 내 메모리 상태로 충분.
# --->
# is_admin_tier   : auth_farm_id 로 admin/user 티어 판정
# is_control_busy : 제어/agent 가 현재 LLM 슬롯을 점유 중인지 (양보 여부 판단)
# register        : 티어별 대기슬롯 점유 — 기존 대기요청 있으면 대체(evict)
# release         : 대기슬롯 반납(차례를 얻어 실제 파이프라인 진입 시 즉시 호출)
# wait_turn       : 제어/agent(및 admin 우선) 에 양보하며 차례 대기
# BUSY_WAIT_MESSAGE / CANCELLED_MESSAGE : 사용자 안내 문구
# ══════════════════════════════════════════════════════════════════════════════
import asyncio
import os
import time
from typing import Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.llm_runtime_guard import is_llm_busy

logger = setup_logger(__name__)

POLL_INTERVAL_SEC = float(os.getenv("CHAT_GATE_POLL_SEC", "1.5"))
MAX_WAIT_SEC = int(os.getenv("CHAT_GATE_MAX_WAIT_SEC", os.getenv("LLM_TIMEOUT_SECONDS", "600")))

# 농장명은 세션 기준 동적 치환 (멀티팜 — 고흥 세션이면 자동으로 고흥뜰에 표시).
def busy_wait_message(farm_name: str = None) -> str:
    who = f"{farm_name} 농장 관리 AI" if farm_name else "농장 관리 AI"
    return f"🌱 {who}가 작업 중입니다. 완료되는 대로 답변을 준비할게요. 잠시만 기다려 주세요."


BUSY_WAIT_MESSAGE = busy_wait_message()
CANCELLED_MESSAGE = (
    "새로운 질문이 접수되어 이전 요청 처리는 취소되었습니다. 잠시 후 다시 요청해 주세요."
)

_CONTROL_LABELS = {"ai_control", "agent"}

# 티어별 대기슬롯 — 프로세스 내 최대 1건. {"admin": handle|None, "user": handle|None}
_slots = {"admin": None, "user": None}
_slots_guard = asyncio.Lock()


class ChatWaitHandle:
    __slots__ = ("tier", "evicted")

    def __init__(self, tier: str):
        self.tier = tier
        self.evicted = asyncio.Event()


def is_admin_tier(auth_farm_id) -> bool:
    # QueryRequest.auth_farm_id: 시스템관리자=None, 농장사용자=자기농장ID
    return auth_farm_id is None


def is_control_busy() -> bool:
    return is_llm_busy(labels=_CONTROL_LABELS)


async def register(tier: str) -> ChatWaitHandle:
    handle = ChatWaitHandle(tier)
    async with _slots_guard:
        prev = _slots.get(tier)
        if prev is not None:
            prev.evicted.set()
            logger.info(f"[대화중재] {tier} 대기슬롯 대체 — 이전 요청 취소 처리")
        _slots[tier] = handle
    return handle


async def release(handle: ChatWaitHandle) -> None:
    async with _slots_guard:
        if _slots.get(handle.tier) is handle:
            _slots[handle.tier] = None


async def wait_turn_step(handle: ChatWaitHandle, timeout: float) -> str:
    """게이트 대기 '1스텝'. wait_turn 을 쪼갠 것으로, 호출측(스트리밍)이 스텝 사이에
    경과시간 하트비트를 낼 수 있게 한다. 반환:
      'ready'     = 차례 획득(진행)
      'cancelled' = 새 요청에 대체됨(취소)
      'waiting'   = 아직 제어/agent 가동 중 — 계속 대기(호출측이 하트비트 후 재호출)
    """
    if handle.evicted.is_set():
        return "cancelled"
    blocked = is_control_busy()
    if not blocked and handle.tier == "user":
        blocked = _slots.get("admin") is not None
    if not blocked:
        return "ready"
    try:
        await asyncio.wait_for(handle.evicted.wait(), timeout=max(0.1, timeout))
        return "cancelled"   # 대기 중 evicted set (새 요청 대체)
    except asyncio.TimeoutError:
        return "waiting"     # timeout 동안 계속 blocked → 재호출 필요


async def wait_turn(handle: ChatWaitHandle) -> bool:
    """제어/agent(및 user 티어는 admin 대기중)에 양보하며 차례를 기다린다.
    반환: True=차례 획득(진행), False=새 요청에 대체되어 취소됨.
    """
    deadline = time.monotonic() + MAX_WAIT_SEC
    while True:
        if handle.evicted.is_set():
            return False
        blocked = is_control_busy()
        if not blocked and handle.tier == "user":
            # 관리자 강제지시가 대기/처리 중이면 일반 사용자 대화는 한 번 더 양보
            blocked = _slots.get("admin") is not None
        if not blocked:
            return True
        if time.monotonic() >= deadline:
            logger.warning(f"[대화중재] 대기 한도({MAX_WAIT_SEC}s) 초과 — 진행 시도 tier={handle.tier}")
            return True
        try:
            await asyncio.wait_for(handle.evicted.wait(), timeout=POLL_INTERVAL_SEC)
            return False  # evicted 이벤트가 대기 중 set 됨
        except asyncio.TimeoutError:
            continue
