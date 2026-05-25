# ══════════════════════════════════════════════════════════════════════════════
# Agent Scheduler — 30분 cron 데몬 (Phase 2) [2026-05-25 신규]
#
# 매 N분 정각마다 ai_monitor_agent.run_agent 호출 → DB 영속.
# 운영 scheduler (`agri_ai_core/scheduler.py`) 와 *완전 별개 프로세스*.
#
# 동작:
#   · 매 분 시작 시 sleep 으로 정확한 정각 도달 대기
#   · 사이클 안 LLM 호출 동안 다음 분 도달 → 그 사이클 종료 후 다음 정각 대기
#   · _is_previous_running flag — 사이클이 30분 넘어가도 중첩 실행 방지
#
# 환경변수:
#   AGENT_INTERVAL_MIN  : 사이클 주기 (기본 30분)
#   AGENT_FARM_IDS      : 모니터링 농장 ID 쉼표 구분 (기본 "1")
#   AGENT_INITIAL_DELAY : 시작 시 첫 사이클 대기 (초, 기본 60)
#   AGENT_LLM_MODEL     : LLM 모델 (ai_monitor_agent 와 공유)
#
# 사용법:
#   python -m agri_ai_core.src.control.agent_scheduler
#
# 파일 시작 함수 목록:
#   _next_interval_dt    : 다음 사이클 fire 시각 계산
#   _run_cycle           : 한 사이클 실행 (모든 농장 모니터링)
#   _build_default_task  : 기본 작업 지시문 합성
#   main                 : 무한 loop 엔트리포인트
# ══════════════════════════════════════════════════════════════════════════════
import os
import signal
import sys
import time
from datetime import datetime, timedelta
from typing import List

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.control.ai_monitor_agent import run_agent

logger = setup_logger(__name__)

AGENT_INTERVAL_MIN  = int(os.getenv("AGENT_INTERVAL_MIN", "30"))
AGENT_INITIAL_DELAY = int(os.getenv("AGENT_INITIAL_DELAY", "60"))
AGENT_FARM_IDS      = [int(x.strip()) for x in os.getenv("AGENT_FARM_IDS", "1").split(",") if x.strip()]

_STOP = False


def _on_signal(signum, frame):
    """SIGTERM/SIGINT 우아한 종료."""
    global _STOP
    logger.info(f"[Agent Scheduler] signal {signum} 수신 — 다음 cycle 후 종료")
    _STOP = True


# ────────────────────────────────────────────────────────────────────
# 다음 cycle 시각 — 정각 기준 AGENT_INTERVAL_MIN 단위로 정렬.
# 예: 현재 12:17 / 30분 주기 → 12:30. 현재 12:31 → 13:00.
# ────────────────────────────────────────────────────────────────────
def _next_interval_dt(now: datetime = None) -> datetime:
    now = now or datetime.now()
    # 현재 분을 AGENT_INTERVAL_MIN 으로 나눠 다음 boundary 찾기
    minutes = (now.minute // AGENT_INTERVAL_MIN + 1) * AGENT_INTERVAL_MIN
    if minutes >= 60:
        # 다음 시간 정각
        nxt = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        nxt = now.replace(minute=minutes, second=0, microsecond=0)
    return nxt


# ────────────────────────────────────────────────────────────────────
# 기본 작업 지시문 — Phase 2 단순화. Phase 5 에서 이벤트별 분기 가능.
# ────────────────────────────────────────────────────────────────────
def _build_default_task(farm_id: int) -> str:
    now = datetime.now().strftime("%H:%M")
    return (
        f"농장 {farm_id} 전체 호기 정기 30분 모니터링 ({now} 기준).\n"
        f"각 호기의 현재 센서 상태를 확인하고, 임계 근접·이상치·LLM 결정 패턴을 "
        f"종합 분석해 운영자가 알아야 할 위험 신호가 있는지 보고하라."
    )


# ────────────────────────────────────────────────────────────────────
# 한 cycle — 모든 농장에 대해 agent 실행. 결과는 자동 DB 영속.
# ────────────────────────────────────────────────────────────────────
def _run_cycle():
    cycle_start = time.time()
    logger.info(f"[Agent Scheduler] === cycle 시작 {datetime.now():%Y-%m-%d %H:%M:%S} ===")

    for farm_id in AGENT_FARM_IDS:
        if _STOP:
            logger.info("[Agent Scheduler] 종료 신호 — cycle 중단")
            return
        task = _build_default_task(farm_id)
        try:
            result = run_agent(task=task, farm_id=farm_id, trigger_type="schedule")
            ok = result.get("success")
            duration = result.get("duration_sec")
            log_id = result.get("log_id")
            final_preview = (result.get("final") or "")[:120]
            logger.info(
                f"[Agent Scheduler] farm={farm_id} 완료 success={ok} duration={duration}s "
                f"log_id={log_id} | {final_preview}"
            )
        except Exception as e:
            logger.warning(f"[Agent Scheduler] farm={farm_id} 예외: {e}")

    cycle_duration = time.time() - cycle_start
    logger.info(f"[Agent Scheduler] === cycle 완료 ({cycle_duration:.1f}s) ===")


# ────────────────────────────────────────────────────────────────────
# 메인 — 무한 loop. 다음 cycle 시각까지 sleep 후 _run_cycle 호출.
# ────────────────────────────────────────────────────────────────────
def main():
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT,  _on_signal)

    logger.info(
        f"[Agent Scheduler] 시작 interval={AGENT_INTERVAL_MIN}분 "
        f"farms={AGENT_FARM_IDS} initial_delay={AGENT_INITIAL_DELAY}s"
    )

    # 시작 직후 즉시 사이클 도는 것 방지 (Ollama 준비 대기)
    if AGENT_INITIAL_DELAY > 0:
        for _ in range(AGENT_INITIAL_DELAY):
            if _STOP:
                return
            time.sleep(1)

    while not _STOP:
        nxt = _next_interval_dt()
        wait_sec = max(0, (nxt - datetime.now()).total_seconds())
        logger.info(f"[Agent Scheduler] 다음 cycle: {nxt:%H:%M:%S} ({wait_sec:.0f}s 후)")

        # 1초 단위 sleep + 종료 신호 체크
        while wait_sec > 0 and not _STOP:
            chunk = min(wait_sec, 5)
            time.sleep(chunk)
            wait_sec = (nxt - datetime.now()).total_seconds()

        if _STOP:
            break

        try:
            _run_cycle()
        except Exception as e:
            logger.error(f"[Agent Scheduler] cycle 예외 — 다음 cycle 까지 대기: {e}")
            # 5초 대기 후 다음 cycle (실패 폭주 방지)
            time.sleep(5)

    logger.info("[Agent Scheduler] 정상 종료")


if __name__ == "__main__":
    sys.exit(main() or 0)
