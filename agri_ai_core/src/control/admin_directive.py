# ══════════════════════════════════════════════════════════════════════════════
# 관리자 강제 지시(Admin Directive)
# 사용자(농장주/관리자)가 명시 지시한 장치 상태를 "해제 지시 전까지" 강제 유지.
#
# 1회성 제어(control_relay)만으로는 자율 제어(스케줄 LLM/agent)가 다음 사이클에서
#   자기 판단으로 되돌릴 수 있음 — 본 모듈이 지속 지시의 공식 이행 수단.
#
# ⛔ 제거 금지 — 우선순위(하드 강제): 인터록(물리보호) > 관리자지시 > 비상가드 > LLM/agent.
#   · relay_manager.set_relay_value 최종 단계(인터록 직전)에서 무조건 적용.
#   · 제어 LLM user 프롬프트 + agent 컨텍스트에 지시 블록 주입 → LLM 도 인지·준수.
#
# 호출 룰: postgresql 만 의존. 매 호출 DB 실시간 read (TTL 캐시 금지).
# --->
# ensure_table        : 테이블 생성(idempotent)
# get_active          : 재배사 활성 지시 dict {semantic: {...}}
# set_directive       : 지시 등록/갱신(upsert)
# release_directive   : 지시 해제
# apply_to_relay_values: relay_values(핀 dict)에 강제 적용 — relay_manager 용
# format_prompt_block : 제어 LLM/agent 프롬프트 주입용 텍스트
# ══════════════════════════════════════════════════════════════════════════════
import threading
from typing import Any, Dict, List, Optional, Tuple

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
import agri_ai_core.src.postgresql.queries as dbQry

logger = setup_logger(__name__)

_table_ready_lock = threading.Lock()
_table_ready = False

VALID_SEMANTICS = {
    "water_heater_flag", "fog_occurs_flag", "drainage_motor_flag",
    "intake_fan_flag", "exhaust_fan_flag", "lighting_flag", "irrigation_flag",
    "air_circulation_valve_flag", "air_intake_valve_flag", "air_exhaust_valve_flag",
}


def ensure_table() -> bool:
    global _table_ready
    if _table_ready:
        return True
    with _table_ready_lock:
        if _table_ready:
            return True
        try:
            with db_session() as d:
                d.execute_query(dbQry.CREATE_ADMIN_DIRECTIVE_TABLE, ())
            _table_ready = True
            logger.info("[관리자지시] admin_device_directive 테이블 보장 완료")
            return True
        except Exception as e:
            logger.warning(f"[관리자지시] 테이블 보장 실패: {e}")
            return False


# ⛔ 마지막 성공 조회값 — DB 일시 오류로 지시가 조용히 풀리는 것을 막는 fail-closed 장치.
#    TTL 캐시가 아니다: 조회 성공 시 항상 최신값이 즉시 덮어쓰므로 실시간성은 그대로다.
#    오류일 때만 개입한다. ⛔ 제거 금지 — 없으면 DB 순단 한 번에 관리자지시가 해제된다.
_LAST_GOOD: Dict[Any, Dict[str, Dict[str, Any]]] = {}


def get_active(farm_id, house_id) -> Dict[str, Dict[str, Any]]:
    """활성 지시 {semantic: {'forced_value','note','created_by','created_at'}}.
    조회 실패 시 마지막 성공값을 유지(fail-closed). 성공 이력이 없을 때만 {}."""
    key = (int(farm_id), int(house_id))

    def _fallback(reason: str) -> Dict[str, Dict[str, Any]]:
        last = _LAST_GOOD.get(key)
        if last:
            # 지시가 살아있는데 조회만 실패한 상황 — 강제를 유지해야 한다.
            logger.error(f"[관리자지시] 조회 실패 farm={farm_id} house={house_id} ({reason}) "
                         f"→ 마지막 성공값 {list(last)} 유지(fail-closed)")
            return dict(last)
        logger.error(f"[관리자지시] 조회 실패 farm={farm_id} house={house_id} ({reason}) "
                     f"→ 성공 이력 없음, 지시 없음으로 진행")
        return {}

    if not ensure_table():
        return _fallback("ensure_table 실패")
    try:
        with db_session() as d:
            rows = d.fetch_all(dbQry.GET_ACTIVE_ADMIN_DIRECTIVES,
                               (int(farm_id), int(house_id)), as_dict=True) or []
        active = {r["semantic"]: dict(r) for r in rows}
        _LAST_GOOD[key] = active          # 해제도 정상 조회 결과이므로 그대로 반영
        return active
    except Exception as e:
        return _fallback(str(e))


def set_directive(farm_id, house_id, semantic: str, forced_value: bool,
                  note: str = "", created_by: str = "admin") -> Dict[str, Any]:
    if semantic not in VALID_SEMANTICS:
        return {"success": False,
                "error": f"유효하지 않은 장치: {semantic} (허용: {sorted(VALID_SEMANTICS)})"}
    if not ensure_table():
        return {"success": False, "error": "테이블 보장 실패"}
    try:
        with db_session() as d:
            d.execute_query(dbQry.UPSERT_ADMIN_DIRECTIVE,
                            (int(farm_id), int(house_id), semantic,
                             bool(forced_value), str(note or "")[:200],
                             str(created_by or "admin")[:40]))
        logger.warning(
            f"[관리자지시] 등록 farm={farm_id} house={house_id} "
            f"{semantic}={'ON' if forced_value else 'OFF'} 강제유지 (사유: {note})"
        )
        return {"success": True,
                "message": (f"{semantic}={'ON' if forced_value else 'OFF'} 강제 유지 등록 — "
                            f"해제(release_admin_directive) 전까지 LLM/agent/비상가드 판단보다 우선 적용됩니다.")}
    except Exception as e:
        logger.warning(f"[관리자지시] 등록 실패: {e}")
        return {"success": False, "error": str(e)}


def release_directive(farm_id, house_id, semantic: str) -> Dict[str, Any]:
    if not ensure_table():
        return {"success": False, "error": "테이블 보장 실패"}
    try:
        with db_session() as d:
            d.execute_query(dbQry.RELEASE_ADMIN_DIRECTIVE,
                            (int(farm_id), int(house_id), semantic))
        logger.warning(f"[관리자지시] 해제 farm={farm_id} house={house_id} {semantic} — 자율 제어 복귀")
        return {"success": True,
                "message": f"{semantic} 강제 유지 해제 — 다음 사이클부터 LLM 자율 판단으로 복귀합니다."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def apply_to_relay_values(farm_id, house_id, relay_values: Dict[str, bool],
                          pin_map: Dict[str, str]) -> Tuple[Dict[str, bool], List[str]]:
    """relay_manager 최종 단계용 — 활성 지시를 핀 dict 에 무조건 적용.
    반환: (적용된 relay_values, 적용 로그 문자열 목록)."""
    directives = get_active(farm_id, house_id)
    applied: List[str] = []
    if not directives:
        return relay_values, applied
    for semantic, info in directives.items():
        pin = pin_map.get(semantic)
        if not pin or pin not in relay_values:
            continue
        forced = bool(info["forced_value"])
        if relay_values[pin] != forced:
            relay_values[pin] = forced
            applied.append(
                f"{semantic}({pin}) → {'ON' if forced else 'OFF'} 강제 "
                f"(관리자지시 {info.get('created_at')}, 사유: {info.get('note') or '-'})"
            )
    return relay_values, applied


def format_prompt_block(farm_id, house_id) -> str:
    """제어 LLM/agent 프롬프트 주입용 — 활성 지시가 없으면 ''."""
    directives = get_active(farm_id, house_id)
    if not directives:
        return ""
    lines = ["⛔ [관리자 강제 지시 — 최우선 준수, 다른 모든 판단보다 우선]"]
    for semantic, info in directives.items():
        lines.append(
            f"  · {semantic} = {'ON' if info['forced_value'] else 'OFF'} 유지 "
            f"(등록 {info.get('created_at')}, 사유: {info.get('note') or '-'})"
        )
    lines.append("  위 장치는 관리자가 해제할 때까지 지시된 상태를 절대 변경하지 말 것.")
    return "\n".join(lines)
