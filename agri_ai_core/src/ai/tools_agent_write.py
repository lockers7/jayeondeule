# ══════════════════════════════════════════════════════════════════════════════
# tools_agent_write — AI agent 의 write 도구 + 안전 가드 (Phase 3) [2026-05-25]
#
# Phase 3 정책 (비상가드 disable 상태에서 agent 가 유일한 자동 대응 경로):
#   ① 모든 write 호출은 *즉시 실행하지 않고* agent_pending_actions 큐에 INSERT
#   ② 큐에 들어간 row 는 execute_at (NOW()+cancellable_seconds) 도달 시
#      별도 worker (agent_pending_worker) 가 실제 실행
#   ③ daily_limit (호기당) 초과 또는 cooldown 위반 시 즉시 거부 — 큐 진입 차단
#   ④ send_user_alert 는 안전한 알림 — cancellable_seconds=0 으로 즉시 실행
#
# 도구 4개:
#   · set_relay         (farm_id, house_id, semantic, on, reason)
#   · set_threshold     (farm_id, house_id, key, value, reason)
#   · set_growth_stage  (farm_id, house_id, stage, reason)
#   · send_user_alert   (level, message, reason="")
#
# 환경 변수:
#   AGENT_CANCELLABLE_SECONDS : 취소 가능 대기 시간 (기본 30)
#   AGENT_DAILY_LIMIT         : (호기,도구) 조합당 일일 호출 제한 (기본 10)
#   AGENT_COOLDOWN_SECONDS    : 동일 도구+호기 재호출 차단 시간 (기본 60)
#
# 파일 시작 함수 목록:
#   safety_guard        : daily_limit + cooldown 검증 데코레이터
#   _count_today        : 오늘 (호기,도구) 큐 INSERT 횟수
#   _last_call_at       : 최근 동일 (호기,도구) 큐 INSERT 시각
#   _enqueue            : agent_pending_actions INSERT 헬퍼 (commit 패턴)
#   _validate_*         : 도구별 args validation
#   set_relay           : 릴레이 변경 요청 (큐)
#   set_threshold       : 임계값 변경 요청 (큐)
#   set_growth_stage    : 생육단계 변경 요청 (큐)
#   send_user_alert     : 사용자 알림 (큐, 0초 — 즉시 실행)
#   TOOL_REGISTRY       : 이름 → 함수 dict
#   TOOL_SPECS          : LLM 시스템 프롬프트용 스키마
#   tool_specs_text     : TOOL_SPECS 텍스트 직렬화
# ══════════════════════════════════════════════════════════════════════════════
import json
import os
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

# ── 안전 가드 파라미터 — 환경 변수로 운영 조정 가능 ──
CANCELLABLE_SECONDS = int(os.getenv("AGENT_CANCELLABLE_SECONDS", "30"))
DAILY_LIMIT         = int(os.getenv("AGENT_DAILY_LIMIT",         "10"))
COOLDOWN_SECONDS    = int(os.getenv("AGENT_COOLDOWN_SECONDS",    "60"))

# ── 도구별 기본 cancellable_seconds (override 가능) ──
# send_user_alert 는 안전한 알림 → 0초 즉시 실행
TOOL_CANCELLABLE_OVERRIDE: Dict[str, int] = {
    "send_user_alert": 0,
}

# ── 도구별 daily_limit override ──
# send_user_alert 는 더 관대 (알림은 막힐 일 적음)
TOOL_DAILY_LIMIT_OVERRIDE: Dict[str, int] = {
    "send_user_alert": 50,
}

# ── 유효 인자 화이트리스트 ──
# [2026-05-25 hotfix2] 실제 pin_map (control_common.get_pin_map) 의 키와 정렬.
# 모든 호기 공통 10개 시멘틱. 임의 영문명 (water_heater 등) 사용 시 relay_manager
# 가 silent skip 하여 false success 반환하는 사고 방지.
VALID_RELAY_SEMANTICS = {
    "water_heater_flag",          # 수온 히터
    "fog_occurs_flag",             # 분무기 (가습)
    "drainage_motor_flag",         # 배수 모터
    "intake_fan_flag",             # 흡기 팬
    "exhaust_fan_flag",            # 배기 팬
    "lighting_flag",               # 조명 (LED)
    "irrigation_flag",             # 관수
    "air_circulation_valve_flag",  # 순환 밸브
    "air_exhaust_valve_flag",      # 배기 밸브
    "air_intake_valve_flag",       # 흡기 밸브
}
VALID_THRESHOLD_KEYS = {
    "tprt_min", "tprt_max", "hmdt_min", "hmdt_max",
    "co2_max", "watr_tprt_min", "watr_tprt_max",
    "bud_tprt_min", "bud_tprt_max",
}
VALID_GROWTH_STAGES = {"발아기", "생육기", "수확기", "휴지기"}
VALID_ALERT_LEVELS = {"info", "warning", "critical"}


# ────────────────────────────────────────────────────────────────────
# DB 헬퍼 — agent_pending_actions INSERT
# (db_session 비커밋 버그 회피, ai_monitor_agent._persist_agent_log 와 동일 패턴)
# ────────────────────────────────────────────────────────────────────
def _enqueue(tool_name: str, args: Dict[str, Any], reason: str,
             trigger_type: str, cancellable_seconds: int,
             agent_log_id: Optional[int] = None) -> Optional[int]:
    try:
        from agri_ai_core.src.postgresql.connection import db
        from psycopg2.extras import RealDictCursor
    except Exception as e:
        logger.error(f"[Agent Write] DB 모듈 import 실패: {e}")
        return None

    sql = (
        "INSERT INTO agent_pending_actions "
        "(execute_at, agent_log_id, trigger_type, tool_name, args, reason, status) "
        "VALUES (NOW() + (%s || ' seconds')::interval, %s, %s, %s, %s::jsonb, %s, 'pending') "
        "RETURNING id"
    )
    vals = (str(cancellable_seconds), agent_log_id, trigger_type, tool_name,
            json.dumps(args, ensure_ascii=False, default=str), reason)
    conn = db._getconn()
    if conn is None:
        logger.error("[Agent Write] DB connection 획득 실패")
        return None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, vals)
            row = cur.fetchone()
            conn.commit()
        return int(row['id']) if row and 'id' in row else None
    except Exception as e:
        logger.warning(f"[Agent Write] _enqueue 실패: {e}")
        try: conn.rollback()
        except Exception: pass
        return None
    finally:
        try: db._putconn(conn)
        except Exception: pass


# ────────────────────────────────────────────────────────────────────
# 안전 가드 — daily_limit + cooldown 검증
# ────────────────────────────────────────────────────────────────────
def _count_today(tool_name: str, farm_id: Optional[int],
                 house_id: Optional[int]) -> int:
    """오늘 (호기,도구) 큐 INSERT 횟수 — cancelled 포함."""
    try:
        from agri_ai_core.src.postgresql.connection import db_session
    except Exception:
        return 0
    try:
        # NOTE: 안전을 위해 cancelled 도 카운트 — agent 가 막 취소된 행동을 다시
        # 시도해서 daily_limit 우회하지 못하게.
        q = (
            "SELECT COUNT(*) AS c FROM agent_pending_actions "
            "WHERE tool_name=%s "
            "  AND created_at::date = CURRENT_DATE "
            "  AND (args->>'farm_id')::int IS NOT DISTINCT FROM %s "
            "  AND (args->>'house_id')::int IS NOT DISTINCT FROM %s"
        )
        with db_session() as d:
            row = d.fetch_one(query=q, vals=(tool_name, farm_id, house_id))
        return int(row["c"]) if row else 0
    except Exception as e:
        logger.warning(f"[Agent Write] _count_today 실패: {e}")
        return 0


def _last_call_at(tool_name: str, farm_id: Optional[int],
                  house_id: Optional[int]) -> Optional[datetime]:
    """최근 동일 (호기,도구) 큐 INSERT 시각 — cooldown 검증용."""
    try:
        from agri_ai_core.src.postgresql.connection import db_session
    except Exception:
        return None
    try:
        q = (
            "SELECT created_at FROM agent_pending_actions "
            "WHERE tool_name=%s "
            "  AND (args->>'farm_id')::int IS NOT DISTINCT FROM %s "
            "  AND (args->>'house_id')::int IS NOT DISTINCT FROM %s "
            "ORDER BY created_at DESC LIMIT 1"
        )
        with db_session() as d:
            row = d.fetch_one(query=q, vals=(tool_name, farm_id, house_id))
        return row["created_at"] if row else None
    except Exception as e:
        logger.warning(f"[Agent Write] _last_call_at 실패: {e}")
        return None


def safety_guard(tool_name: str):
    """daily_limit + cooldown 데코레이터. 거부 시 큐 INSERT 안 함."""
    def deco(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            farm_id  = kwargs.get("farm_id")
            house_id = kwargs.get("house_id")

            # 1) daily_limit
            limit = TOOL_DAILY_LIMIT_OVERRIDE.get(tool_name, DAILY_LIMIT)
            cnt = _count_today(tool_name, farm_id, house_id)
            if cnt >= limit:
                msg = (f"daily_limit 초과 ({tool_name} farm={farm_id} "
                       f"house={house_id} {cnt}/{limit})")
                logger.warning(f"[Agent Write] 거부: {msg}")
                return {"success": False, "reason": "daily_limit",
                        "message": msg, "action_id": None}

            # 2) cooldown
            last = _last_call_at(tool_name, farm_id, house_id)
            if last is not None:
                age_sec = (datetime.now() - last).total_seconds()
                if age_sec < COOLDOWN_SECONDS:
                    msg = (f"cooldown 위반 ({tool_name} farm={farm_id} "
                           f"house={house_id} 직전 호출 {age_sec:.1f}s 전, "
                           f"{COOLDOWN_SECONDS}s 필요)")
                    logger.warning(f"[Agent Write] 거부: {msg}")
                    return {"success": False, "reason": "cooldown",
                            "message": msg, "action_id": None}

            return func(*args, **kwargs)
        return wrapper
    return deco


# ────────────────────────────────────────────────────────────────────
# 인자 검증
# ────────────────────────────────────────────────────────────────────
def _validate_int(name: str, v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 정수 필요 (got {v!r})")


def _validate_relay(farm_id, house_id, semantic, on):
    if semantic not in VALID_RELAY_SEMANTICS:
        raise ValueError(f"semantic 부적합 ({semantic!r}). "
                         f"허용: {sorted(VALID_RELAY_SEMANTICS)}")
    if not isinstance(on, bool):
        raise ValueError(f"on 은 bool 필요 (got {type(on).__name__})")
    return _validate_int("farm_id", farm_id), _validate_int("house_id", house_id)


def _validate_threshold(farm_id, house_id, key, value):
    if key not in VALID_THRESHOLD_KEYS:
        raise ValueError(f"key 부적합 ({key!r}). "
                         f"허용: {sorted(VALID_THRESHOLD_KEYS)}")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"value 숫자 필요 (got {value!r})")
    # 합리적 범위 (LLM 환각 방지)
    if not (-50.0 <= value <= 5000.0):
        raise ValueError(f"value 범위 이탈 ({value}) — -50~5000 만 허용")
    return _validate_int("farm_id", farm_id), _validate_int("house_id", house_id), value


def _validate_growth(farm_id, house_id, stage):
    if stage not in VALID_GROWTH_STAGES:
        raise ValueError(f"stage 부적합 ({stage!r}). "
                         f"허용: {sorted(VALID_GROWTH_STAGES)}")
    return _validate_int("farm_id", farm_id), _validate_int("house_id", house_id)


def _validate_alert(level, message):
    if level not in VALID_ALERT_LEVELS:
        raise ValueError(f"level 부적합 ({level!r}). "
                         f"허용: {sorted(VALID_ALERT_LEVELS)}")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message 필수 (비어있지 않은 문자열)")
    if len(message) > 1000:
        raise ValueError(f"message 너무 김 ({len(message)}자, 1000자 제한)")


# ────────────────────────────────────────────────────────────────────
# 도구 1 — set_relay : 릴레이 변경 요청 (큐)
# ────────────────────────────────────────────────────────────────────
@safety_guard("set_relay")
def set_relay(*, farm_id: int, house_id: int, semantic: str, on: bool,
              reason: str = "", trigger_type: str = "user",
              agent_log_id: Optional[int] = None) -> Dict[str, Any]:
    try:
        farm_id, house_id = _validate_relay(farm_id, house_id, semantic, on)
    except ValueError as e:
        return {"success": False, "reason": "invalid_args",
                "message": str(e), "action_id": None}

    cancellable = TOOL_CANCELLABLE_OVERRIDE.get("set_relay", CANCELLABLE_SECONDS)
    args = {"farm_id": farm_id, "house_id": house_id,
            "semantic": semantic, "on": on}
    aid = _enqueue("set_relay", args, reason, trigger_type, cancellable,
                   agent_log_id)
    if aid is None:
        return {"success": False, "reason": "db_error",
                "message": "큐 INSERT 실패", "action_id": None}
    logger.info(f"[Agent Write] set_relay 큐 등록 id={aid} "
                f"farm={farm_id} house={house_id} {semantic}={on} "
                f"execute_at=NOW+{cancellable}s")
    return {"success": True, "action_id": aid, "execute_in_seconds": cancellable,
            "message": f"{cancellable}초 후 {semantic} {'ON' if on else 'OFF'} 예정"}


# ────────────────────────────────────────────────────────────────────
# 도구 2 — set_threshold : 임계값 변경 요청 (큐)
# ────────────────────────────────────────────────────────────────────
@safety_guard("set_threshold")
def set_threshold(*, farm_id: int, house_id: int, key: str, value: float,
                  reason: str = "", trigger_type: str = "user",
                  agent_log_id: Optional[int] = None) -> Dict[str, Any]:
    try:
        farm_id, house_id, value = _validate_threshold(farm_id, house_id, key, value)
    except ValueError as e:
        return {"success": False, "reason": "invalid_args",
                "message": str(e), "action_id": None}

    cancellable = TOOL_CANCELLABLE_OVERRIDE.get("set_threshold", CANCELLABLE_SECONDS)
    args = {"farm_id": farm_id, "house_id": house_id, "key": key, "value": value}
    aid = _enqueue("set_threshold", args, reason, trigger_type, cancellable,
                   agent_log_id)
    if aid is None:
        return {"success": False, "reason": "db_error",
                "message": "큐 INSERT 실패", "action_id": None}
    logger.info(f"[Agent Write] set_threshold 큐 등록 id={aid} "
                f"farm={farm_id} house={house_id} {key}={value} "
                f"execute_at=NOW+{cancellable}s")
    return {"success": True, "action_id": aid, "execute_in_seconds": cancellable,
            "message": f"{cancellable}초 후 {key}={value} 적용 예정"}


# ────────────────────────────────────────────────────────────────────
# 도구 3 — set_growth_stage : 생육단계 변경 요청 (큐)
# ────────────────────────────────────────────────────────────────────
@safety_guard("set_growth_stage")
def set_growth_stage(*, farm_id: int, house_id: int, stage: str,
                     reason: str = "", trigger_type: str = "user",
                     agent_log_id: Optional[int] = None) -> Dict[str, Any]:
    try:
        farm_id, house_id = _validate_growth(farm_id, house_id, stage)
    except ValueError as e:
        return {"success": False, "reason": "invalid_args",
                "message": str(e), "action_id": None}

    cancellable = TOOL_CANCELLABLE_OVERRIDE.get("set_growth_stage", CANCELLABLE_SECONDS)
    args = {"farm_id": farm_id, "house_id": house_id, "stage": stage}
    aid = _enqueue("set_growth_stage", args, reason, trigger_type, cancellable,
                   agent_log_id)
    if aid is None:
        return {"success": False, "reason": "db_error",
                "message": "큐 INSERT 실패", "action_id": None}
    logger.info(f"[Agent Write] set_growth_stage 큐 등록 id={aid} "
                f"farm={farm_id} house={house_id} stage={stage} "
                f"execute_at=NOW+{cancellable}s")
    return {"success": True, "action_id": aid, "execute_in_seconds": cancellable,
            "message": f"{cancellable}초 후 생육단계 → {stage} 변경 예정"}


# ────────────────────────────────────────────────────────────────────
# 도구 4 — send_user_alert : 사용자 알림 (즉시 실행, 0초)
# ────────────────────────────────────────────────────────────────────
@safety_guard("send_user_alert")
def send_user_alert(*, level: str, message: str, reason: str = "",
                    trigger_type: str = "user",
                    agent_log_id: Optional[int] = None) -> Dict[str, Any]:
    try:
        _validate_alert(level, message)
    except ValueError as e:
        return {"success": False, "reason": "invalid_args",
                "message": str(e), "action_id": None}

    cancellable = TOOL_CANCELLABLE_OVERRIDE.get("send_user_alert", 0)
    args = {"level": level, "message": message}
    aid = _enqueue("send_user_alert", args, reason, trigger_type, cancellable,
                   agent_log_id)
    if aid is None:
        return {"success": False, "reason": "db_error",
                "message": "큐 INSERT 실패", "action_id": None}
    logger.info(f"[Agent Write] send_user_alert 큐 등록 id={aid} "
                f"level={level} ({len(message)}자) 즉시 실행")
    return {"success": True, "action_id": aid, "execute_in_seconds": cancellable,
            "message": f"알림({level}) 큐 등록"}


# ────────────────────────────────────────────────────────────────────
# Registry + Specs (ai_monitor_agent 와 통합)
# ────────────────────────────────────────────────────────────────────
TOOL_REGISTRY: Dict[str, Callable] = {
    "set_relay":         set_relay,
    "set_threshold":     set_threshold,
    "set_growth_stage":  set_growth_stage,
    "send_user_alert":   send_user_alert,
}

TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "set_relay",
        "description": ("릴레이(장치) ON/OFF 변경 요청. 30초 취소 큐에 들어간 후 실행. "
                        "비상가드가 비활성화된 상태이므로 신중히 호출 — 호기당 일일 10회 / 60초 cooldown."),
        "args": {
            "farm_id":  "int — 농장 ID",
            "house_id": "int — 호기 ID (0=공통 거부)",
            "semantic": ("str — water_heater_flag / fog_occurs_flag / drainage_motor_flag / "
                         "intake_fan_flag / exhaust_fan_flag / lighting_flag / irrigation_flag / "
                         "air_circulation_valve_flag / air_exhaust_valve_flag / air_intake_valve_flag"),
            "on":       "bool — true=ON / false=OFF",
            "reason":   "str (필수) — LLM 이 결정한 사유 (사용자 화면에 표시)"
        }
    },
    {
        "name": "set_threshold",
        "description": ("센서 임계값 조정. sensor_m_setting UPDATE 로 적용 → 이후 LLM 결정에 영향. "
                        "30초 취소 큐. value 는 -50~5000 범위만."),
        "args": {
            "farm_id":  "int",
            "house_id": "int",
            "key":      ("str — tprt_min/tprt_max / hmdt_min/hmdt_max / co2_max / "
                         "watr_tprt_min/watr_tprt_max / bud_tprt_min/bud_tprt_max"),
            "value":    "float",
            "reason":   "str (필수)"
        }
    },
    {
        "name": "set_growth_stage",
        "description": "재배사 생육단계 변경 요청. 30초 취소 큐.",
        "args": {
            "farm_id":  "int",
            "house_id": "int",
            "stage":    "str — 발아기 / 생육기 / 수확기 / 휴지기",
            "reason":   "str (필수)"
        }
    },
    {
        "name": "send_user_alert",
        "description": "사용자에게 즉시 알림. 안전한 도구 — 취소 큐 0초 (즉시 실행).",
        "args": {
            "level":   "str — info / warning / critical",
            "message": "str — 1~1000자",
            "reason":  "str (선택)"
        }
    },
]


def tool_specs_text() -> str:
    """LLM 시스템 프롬프트 ${TOOLS} 치환용."""
    lines = []
    for s in TOOL_SPECS:
        args_lines = "\n".join(f"      - {k}: {v}" for k, v in s["args"].items())
        lines.append(f"  · {s['name']} — {s['description']}\n{args_lines}")
    return "\n".join(lines)
