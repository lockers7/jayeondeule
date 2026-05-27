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
import re
import traceback
from typing import Any, Dict, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.tools_utils import normalize_id as _normalize_id
from agri_ai_core.src.ai.tools_auth import (
    check_house_control_access as _check_house_control_access,
    check_farm_access as _check_farm_access,
)

logger = setup_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# house_id를 정규화하되 'all'/'전체'/'모든'은 'all' 로 보존.
# 숫자 또는 '1호재배사' 류는 숫자만 추출, 그 외는 None.
# ────────────────────────────────────────────────────────────────────
def _normalize_house(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("all", "전체", "모든", "모든재배사", "전재배사", "전체재배사", "모두"):
        return "all"
    return _normalize_id(value)


# ────────────────────────────────────────────────────────────────────
# house_id 를 '리스트'로 정규화 — 콤마/공백/슬래시 구분 다중 호기 지원.
#   '2,3'·'2 3'·'2,3호'·'2/3' → ['2','3'] / 'all'·'전체' → ['all'] / '2' → ['2']
# ⛔ _normalize_house(단일)는 normalize_id 가 콤마 문자열을 첫 숫자만 뽑아
#    나머지 호기를 조용히 버렸다(예: '2,3'→'2'). 다중 지정 시 반드시 이 함수 사용.
# 중복은 제거하고 입력 순서를 보존. 인식 불가 토큰은 제외, 빈 결과는 [].
# ────────────────────────────────────────────────────────────────────
def _normalize_house_list(value: Any) -> list:
    if value is None:
        return []
    s = str(value).strip().lower()
    if s in ("all", "전체", "모든", "모든재배사", "전재배사", "전체재배사", "모두"):
        return ["all"]
    out = []
    for part in re.split(r"[,\s/·]+", s):
        if not part:
            continue
        n = _normalize_id(part)
        if n and n not in out:
            out.append(n)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 시스템 농장(farm_id=0)은 물리 재배사가 없음 → 첫 번째 실제 농장으로 대체.
# 제어 도구(tools_data/tools_control)와 동일 규칙 — 지시가 farm 0 에 등록되면
# relay_manager 최종 관문(실농장 기준)에 영원히 적용되지 않는 허점 차단.
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_physical_farm(fid: str) -> str:
    if str(fid) != "0":
        return str(fid)
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        from agri_ai_core.src.postgresql.queries import GET_ONE_FARM
        with db_session() as database:
            real = database.fetch_one(GET_ONE_FARM)
        if real and real.get("farm_id") is not None:
            logger.info(f"[관리자지시 도구] farm_id=0(시스템농장) → 실제 농장 자동 대체: farm_id={real['farm_id']}")
            return str(real["farm_id"])
    except Exception as e:
        logger.warning(f"[관리자지시 도구] 시스템농장 대체 실패: {e}")
    return str(fid)


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
def set_house_control_mode(house_id: str, mode: str, farm_id: str = None,
                            auth_farm_id: str = None) -> Dict[str, Any]:
    from agri_ai_core.src.postgresql.connection import db_session

    # 유효성 검증
    if mode not in _VALID_CTRL_TYPES:
        return {
            "success": False,
            "error": f"유효하지 않은 모드: {mode}. 가능한 값: {_VALID_CTRL_TYPES}",
        }

    # ⛔ [필수 주의] 런타임 판정(manual_control)과 동일 매핑 — 필드명과 반대 의미:
    #   mnul_ctrl_flag=False → 수동(사용자 직접입력) / True+'ai' → AI / True+'algorithm' → 알고리즘
    mnul_flag = mode in ("algorithm", "ai")
    ctrl_store = mode if mode != "manual" else "algorithm"

    target_houses = _normalize_house_list(house_id)
    target_farm = _normalize_id(farm_id) or _normalize_id(auth_farm_id) or "1"

    if not target_houses:
        return {
            "success": False,
            "error": f"재배사 번호를 인식할 수 없습니다: {house_id!r}",
        }

    # 0호 거부 + 농장 접근권 검증 (다중 지정 시 호기별 각각 확인 — tools_auth 위임)
    for _h in target_houses:
        auth_err = _check_house_control_access(auth_farm_id, target_farm, _h)
        if auth_err:
            return auth_err

    try:
        with db_session() as db:
            # 대상 재배사 조회 ('all' 또는 다중 호기 리스트)
            if target_houses == ["all"]:
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
                           "WHERE farm_id=%s AND hous_id = ANY(%s) AND COALESCE(dlte_yn,'N')<>'Y'"),
                    vals=(target_farm, [int(h) for h in target_houses]),
                    as_dict=True,
                )

            if not rows:
                return {
                    "success": False,
                    "error": f"재배사를 찾을 수 없습니다 (farm_id={target_farm}, house_id={house_id})",
                }

            # UPDATE 실행
            changed = []
            for r in rows:
                before = {
                    "mnul_ctrl_flag": r["mnul_ctrl_flag"],
                    "ctrl_type": r["ctrl_type"],
                }
                if bool(before["mnul_ctrl_flag"]) == mnul_flag and (before["ctrl_type"] or "algorithm") == ctrl_store:
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
                    (mnul_flag, ctrl_store, r["farm_id"], r["hous_id"]),
                )
                changed.append({
                    "farm_id": str(r["farm_id"]),
                    "house_id": str(r["hous_id"]),
                    "house_name": r["hous_name"],
                    "before": before,
                    "after": {"mnul_ctrl_flag": mnul_flag, "ctrl_type": ctrl_store},
                    "changed": True,
                })
                logger.info(
                    f"[제어모드변경] farm={r['farm_id']} house={r['hous_id']}({r['hous_name']}) "
                    f"{before} → {{'mnul_ctrl_flag':{mnul_flag},'ctrl_type':'{ctrl_store}'}}"
                )
                # algorithm 모드로 전환 시 throttle 즉시 reset →
                # 다음 relay_control_job 사이클(최대 5초)에서 즉시 1회 환경제어 실행.
                if mode == "algorithm":
                    try:
                        from agri_ai_core.src.control.manual_control import (
                            trigger_algorithm_now,
                        )
                        trigger_algorithm_now(int(r["farm_id"]), int(r["hous_id"]))
                    except Exception as _e:
                        logger.warning(f"[제어모드변경] algorithm 즉시 트리거 실패: {_e}")

        result = {
            "success": True,
            "action": f"control_mode→{mode}",
            "changed": changed,
        }
        # 요청했으나 실제로 없는 호기 → 정직하게 표기(도구가 조용히 성공 오보하지 않도록)
        if target_houses != ["all"]:
            found = {c["house_id"] for c in changed}
            missing = [h for h in target_houses if h not in found]
            if missing:
                result["not_found"] = missing
                result["warning"] = (
                    f"요청한 재배사 중 {', '.join(missing)}호는 존재하지 않아 처리되지 않았습니다."
                )
        return result

    except Exception as e:
        logger.error(f"[제어모드변경] 오류: {e}\n{traceback.format_exc()}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. set_growth_stage — 재배사 생육단계 변경
# ═══════════════════════════════════════════════════════════════════════════════
def set_growth_stage(house_id: str, stage: Any, farm_id: str = None,
                      auth_farm_id: str = None) -> Dict[str, Any]:
    from agri_ai_core.src.postgresql.connection import db_session

    lvel = _GROWTH_STAGE_MAP.get(stage)
    if not lvel:
        return {
            "success": False,
            "error": f"유효하지 않은 생육단계: {stage}. 가능한 값: 발아기/생육기/수확기/휴지기 또는 1~4",
        }

    target_house = _normalize_house(house_id)
    target_farm = _normalize_id(farm_id) or _normalize_id(auth_farm_id) or "1"

    # 0호 거부 + 농장 접근권 검증
    auth_err = _check_house_control_access(auth_farm_id, target_farm, target_house)
    if auth_err:
        return auth_err

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
def set_circulation_mode(house_id: str, mode: str, farm_id: str = None,
                          auth_farm_id: str = None) -> Dict[str, Any]:
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
    target_farm = _normalize_id(farm_id) or _normalize_id(auth_farm_id) or "1"

    # 0호 거부 + 농장 접근권 검증
    auth_err = _check_house_control_access(auth_farm_id, target_farm, target_house)
    if auth_err:
        return auth_err

    try:
        with db_session() as db:
            # ctrl_type 을 함께 조회하여 algorithm/ai 모드 재배사에는 경고 포함
            if target_house == "all":
                rows = db.fetch_all(
                    query=("SELECT farm_id, hous_id, hous_name, ctrl_type FROM farmhouse_m_info "
                           "WHERE farm_id=%s AND hous_id>0 AND COALESCE(dlte_yn,'N')<>'Y'"),
                    vals=(target_farm,), as_dict=True,
                )
            else:
                rows = db.fetch_all(
                    query=("SELECT farm_id, hous_id, hous_name, ctrl_type FROM farmhouse_m_info "
                           "WHERE farm_id=%s AND hous_id=%s AND COALESCE(dlte_yn,'N')<>'Y'"),
                    vals=(target_farm, target_house), as_dict=True,
                )
            if not rows:
                return {"success": False, "error": f"재배사 없음 (farm={target_farm}, house={target_house})"}

            applied = []
            warnings = []
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
                # algorithm/ai 모드 재배사는 자동 루프가 덮어쓰므로 경고 수집
                ctrl_type = (r.get("ctrl_type") or "").strip().lower()
                if ctrl_type in ("algorithm", "ai"):
                    warnings.append(
                        f"{r['hous_id']}호({r.get('hous_name','')})는 현재 ctrl_type='{ctrl_type}' "
                        f"이므로 자동 제어 루프가 되돌릴 수 있습니다. "
                        f"⚠ 사용자가 '유지'를 요청했다면 set_admin_directive 를 즉시 추가 호출하세요 — "
                        f"호출 전에는 '유지된다'고 답변하지 마세요."
                    )
                applied.append({
                    "farm_id": str(r["farm_id"]),
                    "house_id": str(r["hous_id"]),
                    "house_name": r["hous_name"],
                    "ctrl_type": ctrl_type,
                    "mode": mode,
                    "relay_updates": relay_values,
                    "success": result.get("success", False) if isinstance(result, dict) else True,
                })
                logger.info(
                    f"[순환모드강제] farm={r['farm_id']} house={r['hous_id']} → {mode} "
                    f"릴레이={relay_values} ctrl_type={ctrl_type}"
                )

        ret = {"success": True, "action": f"circulation→{mode}", "applied": applied}
        if warnings:
            ret["warnings"] = warnings
        return ret

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
    auth_farm_id: str = None,
) -> Dict[str, Any]:
    from agri_ai_core.src.postgresql.connection import db_session
    from datetime import datetime

    if action not in ("add", "delete", "list"):
        return {"success": False, "error": f"action은 add/delete/list 중 하나여야 합니다: {action}"}
    unit_type_db = "water" if unit_type in ("water", "irrigation", "관수") else "light"
    target_farm = _normalize_id(farm_id) or _normalize_id(auth_farm_id) or "1"
    target_house = _normalize_house(house_id)

    # 0호 거부 + 'all' 거부(단건 전용) + 농장 접근권 검증
    auth_err = _check_house_control_access(auth_farm_id, target_farm, target_house, allow_all=False)
    if auth_err:
        return auth_err

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
_ALLOWED_THRESHOLD_KEYS = {
    "TEMP_LOW", "TEMP_HIGH", "TEMP_CRITICAL_LOW", "TEMP_CRITICAL_HIGH",
    "HUMIDITY_LOW", "HUMIDITY_HIGH", "HUMIDITY_CRITICAL_LOW", "HUMIDITY_CRITICAL_HIGH",
    "CO2_LOW", "CO2_HIGH", "CO2_CRITICAL_HIGH",
    "WATER_TEMP_LOW", "WATER_TEMP_HIGH", "WATER_TEMP_CRITICAL_LOW", "WATER_TEMP_CRITICAL_HIGH",
    "BUDDING_TEMP_LOW", "BUDDING_TEMP_HIGH",
}


# ────────────────────────────────────────────────────────────────────
# AI 환경 제어 임계값 조회/변경 — SENSOR_M_SETTING 재배사별 실시간 반영.
# get: 해당 재배사의 현행 임계값. set: 컬럼 즉시 UPDATE (updt_dttm 갱신 →
# ai_thresholds 캐시 자동 invalidate, 다음 제어 사이클부터 반영).
# reset: 해당 컬럼 NULL (ai_thresholds 폴백 규칙 적용).
# 가드: 물리 타당 범위 + (min<max) 쌍 순서 검증, 농장 접근권. house 'all'/'0' = 전 재배사.
# ────────────────────────────────────────────────────────────────────
_TH_COLUMN = {
    "TEMP_LOW": "tprt_min", "TEMP_HIGH": "tprt_max",
    "TEMP_CRITICAL_LOW": "tprt_crit_min", "TEMP_CRITICAL_HIGH": "tprt_crit_max",
    "HUMIDITY_LOW": "hmdt_min", "HUMIDITY_HIGH": "hmdt_max",
    "HUMIDITY_CRITICAL_LOW": "hmdt_crit_min", "HUMIDITY_CRITICAL_HIGH": "hmdt_crit_max",
    "CO2_LOW": "co2_min", "CO2_HIGH": "co2_max", "CO2_CRITICAL_HIGH": "co2_crit_max",
    "WATER_TEMP_LOW": "watr_tprt_min", "WATER_TEMP_HIGH": "watr_tprt_max",
    "WATER_TEMP_CRITICAL_LOW": "watr_tprt_crit_min", "WATER_TEMP_CRITICAL_HIGH": "watr_tprt_crit_max",
    "BUDDING_TEMP_LOW": "bud_tprt_min", "BUDDING_TEMP_HIGH": "bud_tprt_max",
}
_TH_RANGE = {
    "TEMP": (-30.0, 80.0), "HUMIDITY": (0.0, 100.0), "CO2": (0.0, 10000.0),
    "WATER_TEMP": (0.0, 80.0), "BUDDING_TEMP": (0.0, 60.0),
}
_TH_PAIRS = [
    ("TEMP_LOW", "TEMP_HIGH"), ("TEMP_CRITICAL_LOW", "TEMP_CRITICAL_HIGH"),
    ("HUMIDITY_LOW", "HUMIDITY_HIGH"), ("HUMIDITY_CRITICAL_LOW", "HUMIDITY_CRITICAL_HIGH"),
    ("CO2_LOW", "CO2_HIGH"),
    ("WATER_TEMP_LOW", "WATER_TEMP_HIGH"), ("WATER_TEMP_CRITICAL_LOW", "WATER_TEMP_CRITICAL_HIGH"),
    ("BUDDING_TEMP_LOW", "BUDDING_TEMP_HIGH"),
]


def _th_family(key: str) -> str:
    for fam in ("WATER_TEMP", "BUDDING_TEMP", "HUMIDITY", "CO2", "TEMP"):
        if key.startswith(fam):
            return fam
    return "TEMP"


def override_ai_thresholds(action: str, key: str = None, value: float = None,
                           farm_id: str = None, house_id: str = None,
                           auth_farm_id: str = None) -> Dict[str, Any]:
    from agri_ai_core.src.postgresql.connection import db_session

    target_farm = _normalize_id(farm_id) or _normalize_id(auth_farm_id) or "1"
    if target_farm == "0":
        return {"success": False, "error": "시스템 농장(0)에는 임계값이 없습니다. farm_id 를 지정하세요."}
    denied = _check_farm_access(auth_farm_id, target_farm)
    if denied:
        return denied

    if action == "get":
        from agri_ai_core.src.control.ai_thresholds import get_thresholds
        hid = str(house_id or "").strip()
        hid = hid if (hid and hid not in ("0", "all")) else "1"
        _t = get_thresholds(target_farm, hid)
        current = {k: getattr(_t, k.lower(), None) for k in _ALLOWED_THRESHOLD_KEYS}
        return {"success": True, "action": "get", "farm_id": target_farm,
                "house_id": hid, "source": getattr(_t, "source", None), "current": current,
                "note": "변경은 action='set' (key, value, house_id 'all' 가능) — DB 즉시 반영"}

    if action not in ("set", "reset"):
        return {"success": False, "error": f"지원 action: get/set/reset (입력: {action})"}

    key = str(key or "").strip().upper()
    if key not in _TH_COLUMN:
        return {"success": False,
                "error": f"지원 key: {sorted(_TH_COLUMN.keys())} (입력: {key})"}
    col = _TH_COLUMN[key]

    new_val = None
    if action == "set":
        try:
            new_val = float(value)
        except (TypeError, ValueError):
            return {"success": False, "error": "value 는 숫자여야 합니다."}
        lo, hi = _TH_RANGE[_th_family(key)]
        if not (lo <= new_val <= hi):
            return {"success": False,
                    "error": f"{key} 허용 범위 {lo}~{hi} 밖의 값({new_val}) — 안전상 거부"}

    hid_raw = str(house_id or "").strip().lower()
    all_houses = hid_raw in ("", "0", "all", "전체", "모든")

    try:
        with db_session() as db:
            if all_houses:
                rows = db.fetch_all(
                    query=("SELECT hous_id FROM farmhouse_m_info WHERE farm_id=%s "
                           "AND hous_id>0 AND COALESCE(dlte_yn,'N')<>'Y' ORDER BY hous_id"),
                    vals=(target_farm,), as_dict=True) or []
                targets = [str(int(r["hous_id"])) for r in rows]
            else:
                targets = [_normalize_id(house_id) or hid_raw]
            if not targets:
                return {"success": False, "error": f"대상 재배사 없음 (farm_id={target_farm})"}

            changed = []
            for hid in targets:
                cur = db.fetch_one(
                    query=("SELECT * FROM sensor_m_setting WHERE farm_id=%s AND hous_id=%s "
                           "ORDER BY setn_dttm DESC LIMIT 1"),
                    vals=(target_farm, hid))
                if not cur:
                    changed.append({"house_id": hid, "changed": False,
                                    "error": "설정 행 없음 — 재배사관리 화면에서 최초 저장 필요"})
                    continue
                cur = dict(cur)
                before = cur.get(col)
                # min<max 쌍 순서 검증 (set 시)
                if action == "set":
                    trial = dict(cur); trial[col] = new_val
                    conflict = None
                    for lo_k, hi_k in _TH_PAIRS:
                        if key not in (lo_k, hi_k):
                            continue
                        lo_v, hi_v = trial.get(_TH_COLUMN[lo_k]), trial.get(_TH_COLUMN[hi_k])
                        if lo_v is not None and hi_v is not None and float(lo_v) >= float(hi_v):
                            conflict = f"{lo_k}({lo_v}) < {hi_k}({hi_v}) 순서 위반 — 안전상 거부"
                    if conflict:
                        changed.append({"house_id": hid, "changed": False, "error": conflict})
                        continue
                db.execute_query(
                    f"UPDATE sensor_m_setting SET {col}=%s, updt_dttm=now() "
                    "WHERE farm_id=%s AND hous_id=%s AND setn_dttm=%s",
                    (new_val, target_farm, hid, cur["setn_dttm"]))
                changed.append({"house_id": hid, "key": key, "column": col,
                                "before": float(before) if before is not None else None,
                                "after": new_val, "changed": True})
                logger.info(f"[임계값변경] farm={target_farm} house={hid} {key}({col}) "
                            f"{before} → {new_val}")
        ok = [c for c in changed if c.get("changed")]
        return {"success": bool(ok), "action": action, "farm_id": target_farm,
                "key": key, "results": changed,
                "message": (f"{len(ok)}개 재배사 임계값 변경 완료 — 즉시 제어에 반영됩니다."
                            if ok else "변경된 재배사가 없습니다 (results 참조).")}
    except Exception as e:
        logger.error(f"[임계값변경] 오류: {e}\n{traceback.format_exc()}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 6. set_admin_directive — 관리자 강제 지시 등록
#    사용자의 "유지/계속/해제 전까지" 류 지속 요청의 공식 이행 수단.
#    등록 즉시 relay_manager 최종 관문에서 하드 강제 + 제어LLM/agent 프롬프트 주입.
#    우선순위: 인터록(물리) > 관리자지시 > 비상가드 > LLM.
# ═══════════════════════════════════════════════════════════════════════════════
def set_admin_directive(house_id: str, device_name: str, state: str,
                        note: str = "", farm_id: str = None,
                        auth_farm_id: str = None) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.control.control_common import resolve_device_alias
        from agri_ai_core.src.control.admin_directive import set_directive

        fid = _resolve_physical_farm(_normalize_id(farm_id) or "1")
        denied = _check_farm_access(auth_farm_id, fid)
        if denied:
            return denied
        semantic = resolve_device_alias(device_name)
        if not semantic:
            return {"success": False, "error": f"알 수 없는 장치명: {device_name}"}
        forced = str(state).strip().upper() in ("ON", "TRUE", "1", "켜", "켜기")

        h = _normalize_house(house_id)
        houses = ["1", "2", "3"] if h == "all" else ([h] if h else [])
        if not houses:
            return {"success": False, "error": f"house_id 해석 불가: {house_id}"}

        results = []
        for hh in houses:
            r = set_directive(int(fid), int(hh), semantic, forced,
                              note=note, created_by=str(auth_farm_id or "admin"))
            results.append(f"{hh}호: {'등록' if r.get('success') else '실패(' + str(r.get('error'))[:40] + ')'}")
        return {"success": True,
                "message": (f"관리자 강제 지시 등록 — {device_name}({semantic}) = "
                            f"{'ON' if forced else 'OFF'} 유지. [{', '.join(results)}] "
                            f"해제 전까지 자율 제어(LLM/agent)·비상가드보다 우선 적용됩니다. "
                            f"해제는 release_admin_directive 로 하세요.")}
    except Exception as e:
        logger.error(f"[관리자지시 도구] 등록 실패: {e}\n{traceback.format_exc()}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 7. release_admin_directive — 관리자 강제 지시 해제
# ═══════════════════════════════════════════════════════════════════════════════
def release_admin_directive(house_id: str, device_name: str,
                            farm_id: str = None,
                            auth_farm_id: str = None) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.control.control_common import resolve_device_alias
        from agri_ai_core.src.control.admin_directive import release_directive

        fid = _resolve_physical_farm(_normalize_id(farm_id) or "1")
        denied = _check_farm_access(auth_farm_id, fid)
        if denied:
            return denied
        semantic = resolve_device_alias(device_name)
        if not semantic:
            return {"success": False, "error": f"알 수 없는 장치명: {device_name}"}

        h = _normalize_house(house_id)
        houses = ["1", "2", "3"] if h == "all" else ([h] if h else [])
        if not houses:
            return {"success": False, "error": f"house_id 해석 불가: {house_id}"}

        for hh in houses:
            release_directive(int(fid), int(hh), semantic)
        return {"success": True,
                "message": (f"관리자 강제 지시 해제 — {device_name}({semantic}), "
                            f"대상 {', '.join(houses)}호. 다음 사이클부터 LLM 자율 판단으로 복귀합니다.")}
    except Exception as e:
        logger.error(f"[관리자지시 도구] 해제 실패: {e}\n{traceback.format_exc()}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 8. manage_control_prompt — 제어/agent 시스템 프롬프트 자가 관리
#    LLM 이 사용자 요구를 판단해 control_prompt_m 테이블을 스스로 업데이트.
#    updt_dttm 즉시반영(재기동 불필요).
#    안전: 관리자(auth_farm_id=None)만 update 허용, 이전 본문은 로그에 보존.
# ═══════════════════════════════════════════════════════════════════════════════
def manage_control_prompt(action: str, block_id: str = None,
                          body_text: str = None,
                          auth_farm_id: str = None) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        act = str(action or "").strip().lower()

        if act == "list":
            with db_session() as d:
                rows = d.fetch_all(
                    "SELECT block_id, section_key, name, active_yn, "
                    "LENGTH(body_text) AS body_len, to_char(updt_dttm,'MM-DD HH24:MI') AS updt "
                    "FROM control_prompt_m ORDER BY sort_order", (), as_dict=True) or []
            return {"success": True, "count": len(rows),
                    "blocks": "\n".join(str(dict(r)) for r in rows)[:5000]}

        if act == "get":
            if not block_id:
                return {"success": False, "error": "block_id 필수"}
            with db_session() as d:
                r = d.fetch_one(
                    "SELECT block_id, name, body_text, placeholders, active_yn "
                    "FROM control_prompt_m WHERE block_id = %s", (str(block_id),))
            if not r:
                return {"success": False, "error": f"블록 없음: {block_id}"}
            return {"success": True, "block": dict(r)}

        if act == "update":
            # 프롬프트는 제어 판단의 근간 — 관리자 권한만 허용
            if auth_farm_id is not None:
                return {"success": False,
                        "error": "프롬프트 수정은 시스템관리자 계정에서만 가능합니다."}
            if not block_id or body_text is None or not str(body_text).strip():
                return {"success": False, "error": "block_id 와 body_text 필수"}
            with db_session() as d:
                prev = d.fetch_one(
                    "SELECT body_text FROM control_prompt_m WHERE block_id = %s",
                    (str(block_id),))
                if not prev:
                    return {"success": False, "error": f"블록 없음: {block_id}"}
                d.execute_query(
                    "UPDATE control_prompt_m SET body_text = %s, updt_dttm = NOW() "
                    "WHERE block_id = %s", (str(body_text), str(block_id)))
            # 이전 본문 전문을 로그에 보존 (롤백 근거)
            logger.warning(
                f"[프롬프트자가수정] {block_id} 갱신 (이전 {len(prev['body_text'] or '')}자 "
                f"→ 신규 {len(str(body_text))}자). 이전 본문 보존:\n"
                f"----- PREV {block_id} -----\n{prev['body_text']}\n----- END PREV -----"
            )
            return {"success": True,
                    "message": (f"{block_id} 프롬프트 갱신 완료 — updt_dttm 즉시반영으로 "
                                f"다음 제어 사이클부터 적용됩니다(재기동 불필요). "
                                f"이전 본문은 시스템 로그에 보존되었습니다.")}

        return {"success": False, "error": f"action 은 list|get|update 중 하나: {action}"}
    except Exception as e:
        logger.error(f"[프롬프트자가수정] 실패: {e}\n{traceback.format_exc()}")
        return {"success": False, "error": str(e)}
