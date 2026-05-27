# ══════════════════════════════════════════════════════════════════════════════
# 제어 중재(Arbitration) — agent 우선 · 스케줄 30분 failover
# agent 릴레이 제어를 기본으로 하고, agent 가 유예시간(기본 30분) 이상 제어하지
# 않을 때만 스케줄 LLM 제어를 주기(기본 10분)로 failover 실행한다. agent 가
# 개입하면(set_relay 실행) 다음 tick 부터 스케줄 제어는 즉시 재차 비활성된다.
#
# 저장(control_arbitration_state, 재배사별):
#   last_agent_ctrl_stt/end_dttm  : agent 제어 시작 / 종료(=idle 판정 기준)
#   last_sched_ctrl_stt/end_dttm  : 스케줄 제어 시작(=throttle 기준) / 종료
#   active_controller             : 'agent' | 'schedule' | 'none'
# 파라미터(control_arbitration_config, 단일행): 유예분·주기분 — DB 실시간 조정.
#
# 호출 룰:
#   • postgresql(queries/connection) 만 의존 — 동급 control 모듈 import 금지.
#   • 테이블 부재 시 자동 생성(IF NOT EXISTS). 매 호출 DB read (TTL 캐시 금지).
# --->
# ensure_table            : 상태·설정 테이블 생성(idempotent)
# get_params              : (유예분, 주기분) 실시간 조회 — 실패 시 기본 30/10
# get_state               : 재배사 중재 상태 dict(경과초 포함) — 없으면 None
# should_run_schedule     : 스케줄 제어 실행 허용 여부 → (allow: bool, reason: str)
# agent_end_changed       : 게이트 이후 agent 종료시각 변화(개입) 여부
# stamp_agent_start/end   : agent 제어 시작 / 종료 시각 기록
# stamp_schedule_start/end: 스케줄 제어 시작 / 종료 시각 기록
# ══════════════════════════════════════════════════════════════════════════════
import threading
import os
from typing import Any, Dict, Optional, Tuple

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
import agri_ai_core.src.postgresql.queries as dbQry

logger = setup_logger(__name__)

_DEFAULT_FAILOVER_MIN = 30
_DEFAULT_INTERVAL_MIN = 10
_MONOPOLY_HARDCAP_MULT = int(os.getenv('AGENT_MONOPOLY_HARDCAP_MULT', '3'))  # 독점 하드캡 = 유예분×이 값
_table_ready_lock = threading.Lock()
_table_ready = False


# ────────────────────────────────────────────────────────────────────
# 상태·설정 테이블 생성 시도(idempotent). 한 프로세스에서 1회만 실제 SQL 실행.
# ────────────────────────────────────────────────────────────────────
def ensure_table() -> bool:
    global _table_ready
    if _table_ready:
        return True
    with _table_ready_lock:
        if _table_ready:
            return True
        try:
            with db_session() as database:
                database.execute_query(dbQry.CREATE_CONTROL_ARBITRATION_TABLE, ())
            _table_ready = True
            logger.info("[제어중재] control_arbitration 테이블 보장 완료(IF NOT EXISTS)")
            return True
        except Exception as e:
            logger.warning(f"[제어중재] 테이블 보장 실패: {e}")
            return False


# ────────────────────────────────────────────────────────────────────
# (유예분, 주기분) 실시간 조회. 조회 실패 시 기본 30/10 반환.
# ────────────────────────────────────────────────────────────────────
def get_params() -> Tuple[int, int]:
    if not ensure_table():
        return _DEFAULT_FAILOVER_MIN, _DEFAULT_INTERVAL_MIN
    try:
        with db_session() as database:
            row = database.fetch_one(dbQry.GET_ARBITRATION_CONFIG, ())
        if row:
            fmin = int(row.get('agent_idle_failover_min') or _DEFAULT_FAILOVER_MIN)
            imin = int(row.get('sched_failover_interval_min') or _DEFAULT_INTERVAL_MIN)
            return max(1, fmin), max(1, imin)
    except Exception as e:
        logger.warning(f"[제어중재] 파라미터 조회 실패 — 기본 30/10 적용: {e}")
    return _DEFAULT_FAILOVER_MIN, _DEFAULT_INTERVAL_MIN


# ────────────────────────────────────────────────────────────────────
# 재배사 중재 상태 dict 조회(agent_idle_sec / sched_since_stt_sec 포함).
# 행이 없으면 None.
# ────────────────────────────────────────────────────────────────────
def get_state(farm_id, house_id) -> Optional[Dict[str, Any]]:
    if not ensure_table():
        return None
    try:
        with db_session() as database:
            return database.fetch_one(
                dbQry.GET_ARBITRATION_STATE, (int(farm_id), int(house_id))
            )
    except Exception as e:
        logger.warning(f"[제어중재] 상태 조회 실패 farm={farm_id} house={house_id}: {e}")
        return None


# ────────────────────────────────────────────────────────────────────
# 스케줄 제어 실행 허용 여부. (allow, reason)
#   · agent 마지막 제어가 유예분 미만 전 → 불가(agent 우선)
#   · failover 영역이나 직전 스케줄 시작이 주기분 미만 전 → 불가(throttle)
#   · 그 외 → 허용. 상태행 없으면 허용(무제어 공백 방지).
# 예외/조회 실패 시에는 제어 연속성 우선 → 허용(True).
# ────────────────────────────────────────────────────────────────────
def should_run_schedule(farm_id, house_id) -> Tuple[bool, str]:
    failover_min, interval_min = get_params()
    st = get_state(farm_id, house_id)
    if st is None:
        return True, "중재상태 없음 → failover(무제어 공백 방지)"
    # ⛔ 독점 하드캡 — agent 가 계속 제어해 AI 루프가 장시간 skip 되면(예: 재개입 루프)
    #    정합 baseline 재확립을 위해 하드캡(유예분×MULT)마다 AI 루프 1회 강제 허용.
    #    환경가드(고습→포그OFF 등)로 상태 정합이 보장되므로 짧은 재확립은 안전.
    _sched_since = st.get('sched_since_stt_sec')
    _hardcap_sec = failover_min * 60 * _MONOPOLY_HARDCAP_MULT
    if _sched_since is None or _sched_since >= _hardcap_sec:
        return True, (f"독점 하드캡 — AI루프 {(_sched_since or 0)/60:.0f}분 미실행 "
                      f"(≥ {_hardcap_sec/60:.0f}분) → baseline 재확립")
    idle = st.get('agent_idle_sec')
    if idle is not None and idle < failover_min * 60:
        return False, (f"agent 우선 — 마지막 agent제어 {idle/60:.1f}분 전 "
                       f"< 유예 {failover_min}분")
    since = st.get('sched_since_stt_sec')
    if since is not None and since < interval_min * 60:
        return False, (f"스케줄 throttle — 직전 스케줄 {since/60:.1f}분 전 "
                       f"< 주기 {interval_min}분")
    return True, f"failover 활성 — agent 무제어 {failover_min}분+"


# ────────────────────────────────────────────────────────────────────
# 게이트 통과 시점의 agent 종료시각(prev_end) 대비 변화 여부.
# 스케줄 LLM 진행 중 agent 가 개입(set_relay)했는지 판정 → True 면 적용 취소.
# ────────────────────────────────────────────────────────────────────
def agent_end_changed(farm_id, house_id, prev_end) -> bool:
    st = get_state(farm_id, house_id)
    cur_end = st.get('last_agent_ctrl_end_dttm') if st else None
    return cur_end != prev_end


# ────────────────────────────────────────────────────────────────────
# stamp 헬퍼 — 실패해도 제어 흐름 보존(로그만).
# ────────────────────────────────────────────────────────────────────
def _stamp(sql: str, farm_id, house_id, label: str) -> None:
    if not ensure_table():
        return
    try:
        with db_session() as database:
            database.execute_query(sql, (int(farm_id), int(house_id)))
    except Exception as e:
        logger.warning(f"[제어중재] {label} stamp 실패 farm={farm_id} house={house_id}: {e}")


def stamp_agent_start(farm_id, house_id) -> None:
    _stamp(dbQry.UPSERT_ARB_AGENT_START, farm_id, house_id, "agent_start")


def stamp_agent_end(farm_id, house_id) -> None:
    _stamp(dbQry.UPSERT_ARB_AGENT_END, farm_id, house_id, "agent_end")


def stamp_schedule_start(farm_id, house_id) -> None:
    _stamp(dbQry.UPSERT_ARB_SCHED_START, farm_id, house_id, "sched_start")


def stamp_schedule_end(farm_id, house_id) -> None:
    _stamp(dbQry.UPSERT_ARB_SCHED_END, farm_id, house_id, "sched_end")
