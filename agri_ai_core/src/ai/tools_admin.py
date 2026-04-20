# ══════════════════════════════════════════════════════════════════════════════
# 관리 도구 모듈 — LLM이 호출하는 고수준 제어 도구 모음.
# 릴레이 개별 ON/OFF(tools_control.py)와 달리, 시스템 운영 파라미터를 조정한다.
# --->
# set_house_control_mode: 재배사 제어 모드 전환 (manual/algorithm/ai)
# set_growth_stage:       재배사 생육단계 변경 (발아기/생육기/수확기/휴지기)
# set_circulation_mode:   재배사 순환모드 수동 강제 (내부/외부/흡입/배기/정지)
# set_schedule:           조명/관수 자동 스케줄 추가·수정·삭제
# override_ai_thresholds: AI 제어 임계값 일시 조정 (온도·습도·CO2 등)
# ══════════════════════════════════════════════════════════════════════════════
import traceback
from typing import Any, Dict, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.tools_utils import normalize_id as _normalize_id

logger = setup_logger(__name__)


def _normalize_house(value: Any) -> Optional[str]:
    """house_id를 정규화하되 'all'/'전체'/'모든'은 'all' 로 보존.
    숫자 또는 '1호재배사' 류는 숫자만 추출, 그 외는 None."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("all", "전체", "모든", "모든재배사", "전재배사", "전체재배사", "모두"):
        return "all"
    return _normalize_id(value)


# ─────────────────────────────────────────────────────────────────────────────
# 유효성 검증 상수
# ─────────────────────────────────────────────────────────────────────────────
_VALID_CTRL_TYPES = ("manual", "algorithm", "ai")
_GROWTH_STAGE_MAP = {  # 입력(한글/숫자) → crop_lvel 숫자
    "발아기": 1, "발이기": 1, "1": 1, 1: 1,
    "생육기": 2, "2": 2, 2: 2,
    "수확기": 3, "3": 3, 3: 3,
    "휴지기": 4, "4": 4, 4: 4,
}
_GROWTH_STAGE_NAME = {1: "발아기", 2: "생육기", 3: "수확기", 4: "휴지기"}
_VALID_CIRCULATION_MODES = ("내부순환", "외부순환", "흡입순환", "배기순환", "순환정지")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. set_house_control_mode — 재배사 제어 모드 전환
# ═══════════════════════════════════════════════════════════════════════════════
def set_house_control_mode(house_id: str, mode: str, farm_id: str = None) -> Dict[str, Any]:
    """재배사의 제어 모드(mnul_ctrl_flag + ctrl_type)를 변경한다.

    Args:
        house_id: 해당 농장의 hous_id (문자/숫자) 또는 'all' (전 재배사),
                  또는 재배사 이름(예: '상황버섯2호재배사'). 재배사 개수·번호는 농장별 가변.
        mode: 'manual' | 'algorithm' | 'ai'
        farm_id: 농장 ID (기본값: default_tool_args의 farm_id)

    Returns:
        {success, action, changed: [{farm_id, house_id, before: {...}, after: {...}}]}
    """
    from agri_ai_core.src.postgresql.connection import db_session

    # 유효성 검증
    if mode not in _VALID_CTRL_TYPES:
        return {
            "success": False,
            "error": f"유효하지 않은 모드: {mode}. 가능한 값: {_VALID_CTRL_TYPES}",
        }

    # manual / ai → mnul_ctrl_flag=True, algorithm → mnul_ctrl_flag=False
    mnul_flag = mode in ("manual", "ai")

    target_house = _normalize_house(house_id)
    target_farm = _normalize_id(farm_id) or "1"

    try:
        with db_session() as db:
            # 대상 재배사 조회
            if target_house == "all":
                rows = db.fetch_all(
                    query=("SELECT farm_id, hous_id, hous_name, mnul_ctrl_flag, ctrl_type "
                           "FROM farmhouse_m_info "
                           "WHERE farm_id=%s AND hous_id>0 AND COALESCE(dlte_yn,'N')<>'Y'"),
                    vals=(target_farm,),
                    as_dict=True,
                )
            else:
                rows = db.fetch_all(
                    query=("SELECT farm_id, hous_id, hous_name, mnul_ctrl_flag, ctrl_type "
                           "FROM farmhouse_m_info "
                           "WHERE farm_id=%s AND hous_id=%s AND COALESCE(dlte_yn,'N')<>'Y'"),
                    vals=(target_farm, target_house),
                    as_dict=True,
                )

            if not rows:
                return {
                    "success": False,
                    "error": f"재배사를 찾을 수 없습니다 (farm_id={target_farm}, house_id={target_house})",
                }

            # UPDATE 실행
            changed = []
            for r in rows:
                before = {
                    "mnul_ctrl_flag": r["mnul_ctrl_flag"],
                    "ctrl_type": r["ctrl_type"],
                }
                if before["mnul_ctrl_flag"] == mnul_flag and before["ctrl_type"] == mode:
                    # 이미 동일 → 변경 없음
                    changed.append({
                        "farm_id": str(r["farm_id"]),
                        "house_id": str(r["hous_id"]),
                        "house_name": r["hous_name"],
                        "before": before,
                        "after": before,
                        "changed": False,
                    })
                    continue

                db.execute_query(
                    "UPDATE farmhouse_m_info SET mnul_ctrl_flag=%s, ctrl_type=%s, rfrs_flag=TRUE "
                    "WHERE farm_id=%s AND hous_id=%s",
                    (mnul_flag, mode, r["farm_id"], r["hous_id"]),
                )
                changed.append({
                    "farm_id": str(r["farm_id"]),
                    "house_id": str(r["hous_id"]),
                    "house_name": r["hous_name"],
                    "before": before,
                    "after": {"mnul_ctrl_flag": mnul_flag, "ctrl_type": mode},
                    "changed": True,
                })
                logger.info(
                    f"[제어모드변경] farm={r['farm_id']} house={r['hous_id']}({r['hous_name']}) "
                    f"{before} → {{'mnul_ctrl_flag':{mnul_flag},'ctrl_type':'{mode}'}}"
                )

        return {
            "success": True,
            "action": f"control_mode→{mode}",
            "changed": changed,
        }

    except Exception as e:
        logger.error(f"[제어모드변경] 오류: {e}\n{traceback.format_exc()}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. set_growth_stage — 재배사 생육단계 변경
# ═══════════════════════════════════════════════════════════════════════════════
def set_growth_stage(house_id: str, stage: Any, farm_id: str = None) -> Dict[str, Any]:
    """재배사의 생육단계(crop_lvel)를 변경한다.

    Args:
        house_id: 해당 농장의 hous_id 또는 'all' (재배사 구성은 농장별 가변)
        stage: '발아기' | '생육기' | '수확기' | '휴지기' (또는 숫자 1~4)
        farm_id: 농장 ID
    """
    from agri_ai_core.src.postgresql.connection import db_session

    lvel = _GROWTH_STAGE_MAP.get(stage)
    if not lvel:
        return {
            "success": False,
            "error": f"유효하지 않은 생육단계: {stage}. 가능한 값: 발아기/생육기/수확기/휴지기 또는 1~4",
        }

    target_house = _normalize_house(house_id)
    target_farm = _normalize_id(farm_id) or "1"

    try:
        with db_session() as db:
            if target_house == "all":
                rows = db.fetch_all(
                    query=("SELECT farm_id, hous_id, hous_name, crop_lvel FROM farmhouse_m_info "
                           "WHERE farm_id=%s AND hous_id>0 AND COALESCE(dlte_yn,'N')<>'Y'"),
                    vals=(target_farm,),
                    as_dict=True,
                )
            else:
                rows = db.fetch_all(
                    query=("SELECT farm_id, hous_id, hous_name, crop_lvel FROM farmhouse_m_info "
                           "WHERE farm_id=%s AND hous_id=%s AND COALESCE(dlte_yn,'N')<>'Y'"),
                    vals=(target_farm, target_house),
                    as_dict=True,
                )
            if not rows:
                return {"success": False, "error": f"재배사 없음 (farm={target_farm}, house={target_house})"}

            changed = []
            for r in rows:
                before_lvel = int(r["crop_lvel"] or 0)
                if before_lvel == lvel:
                    changed.append({
                        "farm_id": str(r["farm_id"]),
                        "house_id": str(r["hous_id"]),
                        "house_name": r["hous_name"],
                        "before": _GROWTH_STAGE_NAME.get(before_lvel, "미정"),
                        "after": _GROWTH_STAGE_NAME[lvel],
                        "changed": False,
                    })
                    continue

                db.execute_query(
                    "UPDATE farmhouse_m_info SET crop_lvel=%s, rfrs_flag=TRUE "
                    "WHERE farm_id=%s AND hous_id=%s",
                    (lvel, r["farm_id"], r["hous_id"]),
                )
                changed.append({
                    "farm_id": str(r["farm_id"]),
                    "house_id": str(r["hous_id"]),
                    "house_name": r["hous_name"],
                    "before": _GROWTH_STAGE_NAME.get(before_lvel, "미정"),
                    "after": _GROWTH_STAGE_NAME[lvel],
                    "changed": True,
                })
                logger.info(
                    f"[생육단계변경] farm={r['farm_id']} house={r['hous_id']} "
                    f"{_GROWTH_STAGE_NAME.get(before_lvel,'미정')} → {_GROWTH_STAGE_NAME[lvel]}"
                )

        return {"success": True, "action": f"growth_stage→{_GROWTH_STAGE_NAME[lvel]}", "changed": changed}

    except Exception as e:
        logger.error(f"[생육단계변경] 오류: {e}\n{traceback.format_exc()}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. set_circulation_mode — 순환모드 수동 강제
# ═══════════════════════════════════════════════════════════════════════════════
def set_circulation_mode(house_id: str, mode: str, farm_id: str = None) -> Dict[str, Any]:
    """재배사의 순환모드를 강제 설정한다 (댐퍼+팬 조합 반영).

    Args:
        house_id: 해당 농장의 hous_id 또는 'all' (재배사 구성은 농장별 가변)
        mode: '내부순환' | '외부순환' | '흡입순환' | '배기순환' | '순환정지'
        farm_id: 농장 ID

    Note: 이 도구는 릴레이를 직접 제어한다. 재배사의 ctrl_type='manual'일 때만 유효.
          algorithm/ai 모드에서는 5초/10초마다 덮어써질 수 있음.
    """
    from agri_ai_core.src.control.control_common import CIRCULATION_MODES, get_pin_map
    from agri_ai_core.src.control.relay_manager import set_relay_value
    from agri_ai_core.src.postgresql.connection import db_session

    if mode not in _VALID_CIRCULATION_MODES:
        return {
            "success": False,
            "error": f"유효하지 않은 순환모드: {mode}. 가능한 값: {_VALID_CIRCULATION_MODES}",
        }

    circ = CIRCULATION_MODES.get(mode)
    if not circ:
        return {"success": False, "error": f"순환모드 정의 없음: {mode}"}

    target_house = _normalize_house(house_id)
    target_farm = _normalize_id(farm_id) or "1"

    try:
        with db_session() as db:
            if target_house == "all":
                rows = db.fetch_all(
                    query=("SELECT farm_id, hous_id, hous_name FROM farmhouse_m_info "
                           "WHERE farm_id=%s AND hous_id>0 AND COALESCE(dlte_yn,'N')<>'Y'"),
                    vals=(target_farm,), as_dict=True,
                )
            else:
                rows = db.fetch_all(
                    query=("SELECT farm_id, hous_id, hous_name FROM farmhouse_m_info "
                           "WHERE farm_id=%s AND hous_id=%s AND COALESCE(dlte_yn,'N')<>'Y'"),
                    vals=(target_farm, target_house), as_dict=True,
                )
            if not rows:
                return {"success": False, "error": f"재배사 없음 (farm={target_farm}, house={target_house})"}

            applied = []
            for r in rows:
                pin_map = get_pin_map(int(r["hous_id"]))
                relay_values = {}
                # 댐퍼 설정
                for sem_name, val in circ.get("dampers", {}).items():
                    pin = pin_map.get(sem_name)
                    if pin:
                        relay_values[pin] = val
                # 팬 설정
                for sem_name, val in circ.get("fans", {}).items():
                    pin = pin_map.get(sem_name)
                    if pin:
                        relay_values[pin] = val

                result = set_relay_value(r["farm_id"], r["hous_id"], relay_values, raw_mode=False)
                applied.append({
                    "farm_id": str(r["farm_id"]),
                    "house_id": str(r["hous_id"]),
                    "house_name": r["hous_name"],
                    "mode": mode,
                    "relay_updates": relay_values,
                    "success": result.get("success", False) if isinstance(result, dict) else True,
                })
                logger.info(
                    f"[순환모드강제] farm={r['farm_id']} house={r['hous_id']} → {mode} "
                    f"릴레이={relay_values}"
                )

        return {"success": True, "action": f"circulation→{mode}", "applied": applied}

    except Exception as e:
        logger.error(f"[순환모드강제] 오류: {e}\n{traceback.format_exc()}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. set_schedule — 조명/관수 자동 스케줄 관리
# ═══════════════════════════════════════════════════════════════════════════════
def set_schedule(
    action: str,
    house_id: str,
    unit_type: str,
    start_time: str = None,
    end_time: str = None,
    interval_min: int = None,
    weekdays: str = None,
    excs_type: str = "daily",
    farm_id: str = None,
) -> Dict[str, Any]:
    """조명/관수 자동 제어 스케줄을 추가·삭제한다.

    Args:
        action: 'add' | 'delete' | 'list'
        house_id: 단일 hous_id만 허용 ('all' 불가). 재배사 구성은 농장별 가변.
        unit_type: 'light' | 'water'(irrigation)
        start_time: 'HH:MM' (add 시)
        end_time:   'HH:MM' (add 시)
        interval_min: 관수의 경우 반복 주기(분). 조명은 None.
        weekdays: 'mon,tue,...' 콤마 구분 또는 'daily'
        excs_type: 기본 'daily'
        farm_id: 농장 ID
    """
    from agri_ai_core.src.postgresql.connection import db_session
    from datetime import datetime

    if action not in ("add", "delete", "list"):
        return {"success": False, "error": f"action은 add/delete/list 중 하나여야 합니다: {action}"}
    unit_type_db = "water" if unit_type in ("water", "irrigation", "관수") else "light"
    target_farm = _normalize_id(farm_id) or "1"
    target_house = _normalize_house(house_id)
    if target_house in (None, "all"):
        return {"success": False, "error": "set_schedule는 특정 house_id만 지원합니다 (all 불가)"}

    try:
        with db_session() as db:
            if action == "list":
                rows = db.fetch_all(
                    query=("SELECT setn_dttm, unit_type, strt_time, fnsh_time, excs_type, "
                           "excs_itvl, excs_wkdy, dlte_yn FROM light_irrigation_s_setting "
                           "WHERE farm_id=%s AND hous_id=%s AND COALESCE(dlte_yn,FALSE)=FALSE "
                           "ORDER BY unit_type, strt_time"),
                    vals=(target_farm, target_house), as_dict=True,
                )
                # strt_time/fnsh_time time 객체 직렬화
                for r in rows:
                    for k in ("strt_time", "fnsh_time"):
                        if r.get(k) is not None:
                            r[k] = str(r[k])
                    if r.get("setn_dttm") is not None:
                        r["setn_dttm"] = r["setn_dttm"].isoformat()
                return {"success": True, "action": "list", "schedules": rows}

            if action == "add":
                if not start_time or not end_time:
                    return {"success": False, "error": "add 시 start_time / end_time 필수"}
                db.execute_query(
                    "INSERT INTO light_irrigation_s_setting "
                    "(farm_id, hous_id, setn_dttm, dlte_yn, unit_type, strt_time, fnsh_time, "
                    " excs_type, excs_itvl, excs_strt_date, excs_wkdy) "
                    "VALUES (%s, %s, NOW(), FALSE, %s, %s, %s, %s, %s, CURRENT_DATE, %s)",
                    (target_farm, target_house, unit_type_db, start_time, end_time,
                     excs_type, interval_min, weekdays or "daily"),
                )
                logger.info(
                    f"[스케줄추가] farm={target_farm} house={target_house} {unit_type_db} "
                    f"{start_time}~{end_time} 간격={interval_min} 요일={weekdays}"
                )
                return {
                    "success": True, "action": "add",
                    "summary": f"{unit_type_db} {start_time}~{end_time} 추가 (house={target_house})",
                }

            # delete: unit_type + start_time으로 식별
            if not start_time:
                return {"success": False, "error": "delete 시 start_time 필수 (삭제 대상 식별용)"}
            db.execute_query(
                "UPDATE light_irrigation_s_setting SET dlte_yn=TRUE "
                "WHERE farm_id=%s AND hous_id=%s AND unit_type=%s AND strt_time=%s",
                (target_farm, target_house, unit_type_db, start_time),
            )
            logger.info(
                f"[스케줄삭제] farm={target_farm} house={target_house} "
                f"{unit_type_db} {start_time}"
            )
            return {"success": True, "action": "delete",
                    "summary": f"{unit_type_db} {start_time} 삭제 (house={target_house})"}

    except Exception as e:
        logger.error(f"[set_schedule] 오류: {e}\n{traceback.format_exc()}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. override_ai_thresholds — AI 제어 임계값 조회·일시 조정 (in-memory)
# ═══════════════════════════════════════════════════════════════════════════════
_THRESHOLD_OVERRIDES: Dict[str, float] = {}  # 런타임 오버라이드 (재시작 시 초기화)
_ALLOWED_THRESHOLD_KEYS = {
    "TEMP_LOW", "TEMP_HIGH", "TEMP_CRITICAL_LOW", "TEMP_CRITICAL_HIGH",
    "HUMIDITY_LOW", "HUMIDITY_HIGH", "HUMIDITY_CRITICAL_LOW", "HUMIDITY_CRITICAL_HIGH",
    "CO2_LOW", "CO2_HIGH", "CO2_CRITICAL_HIGH",
    "WATER_TEMP_LOW", "WATER_TEMP_HIGH", "WATER_TEMP_CRITICAL_LOW", "WATER_TEMP_CRITICAL_HIGH",
    "BUDDING_TEMP_LOW", "BUDDING_TEMP_HIGH",
}


def override_ai_thresholds(action: str, key: str = None, value: float = None) -> Dict[str, Any]:
    """AI 환경 제어용 임계값을 조회하거나 일시 조정한다.

    Args:
        action: 'get' | 'set' | 'reset'
        key: TEMP_LOW, TEMP_HIGH 등 (set/reset 시)
        value: 새 값 (set 시)

    Note: 런타임 메모리에만 저장된다 (agri_ai_core 재시작 시 초기화).
          적용되려면 control_common 모듈의 get_threshold() 헬퍼를 참조해야 하므로,
          현재는 조회·제안 용도. 실제 반영은 추후 control_common 연동 후 동작.
    """
    from agri_ai_core.src.control import control_common as cc

    if action == "get":
        current = {k: getattr(cc, k, None) for k in _ALLOWED_THRESHOLD_KEYS}
        return {"success": True, "action": "get", "current": current, "overrides": dict(_THRESHOLD_OVERRIDES)}

    if action == "reset":
        if key:
            _THRESHOLD_OVERRIDES.pop(key, None)
            return {"success": True, "action": "reset", "key": key}
        _THRESHOLD_OVERRIDES.clear()
        return {"success": True, "action": "reset_all"}

    if action == "set":
        if key not in _ALLOWED_THRESHOLD_KEYS:
            return {"success": False, "error": f"허용되지 않은 key: {key}. 허용: {sorted(_ALLOWED_THRESHOLD_KEYS)}"}
        if value is None:
            return {"success": False, "error": "set 시 value 필수"}
        try:
            _THRESHOLD_OVERRIDES[key] = float(value)
        except (TypeError, ValueError):
            return {"success": False, "error": f"value 숫자 변환 실패: {value}"}
        logger.info(f"[임계값오버라이드] {key} = {value} (runtime only)")
        return {
            "success": True, "action": "set", "key": key, "value": value,
            "note": "런타임 메모리에만 저장됨. 현재 control_common 상수를 런타임에 재참조하지 않으므로 실제 반영은 추후 연동 필요.",
        }

    return {"success": False, "error": f"action은 get/set/reset 중 하나여야 합니다: {action}"}
