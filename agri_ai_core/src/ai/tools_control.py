# ══════════════════════════════════════════════════════════════════════════════
# 릴레이 제어 도구 — LLM이 호출하는 릴레이 ON/OFF/반전 및 일괄 제어.
# L5 계층 모듈 (tools_executor.py 와 동급).
# --->
# _resolve_relay_ids            : 릴레이 제어용 house_id/farm_id 정규화 및 검증
# _get_ai_judgment_safe         : AI 환경 판단 안전 호출
# _build_post_control_snapshot  : DB 쓰기 직후 그 재배사의 ON/OFF 스냅샷을 LLM 친화 dict로 반환
# _control_relay_all_houses     : house_id='all' 요청 시 모든 재배사 일괄 제어
# control_relay                 : 단일 릴레이 ON/OFF/반전 제어
# _batch_build_by_mode          : mode(reverse_all/all_on/all_off) 기반 일괄 설정 계산
# _batch_build_by_devices       : devices 배열 기반 개별 릴레이 설정 계산
# control_relays_batch          : 여러 릴레이 장치를 한 번에 제어
# ══════════════════════════════════════════════════════════════════════════════
import time
import traceback
from typing import Dict, Any, List

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.tools_utils import (
    normalize_id as _normalize_id,
    build_ai_conflict as _build_ai_conflict,
)
from agri_ai_core.src.ai.tools_auth import (
    require_non_zero_house as _require_non_zero_house,
    check_farm_access as _check_farm_access,
)

logger = setup_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# DB 쓰기 직후 해당 재배사 모든 릴레이를 다시 읽어 ON/OFF 한국어 라벨 dict 반환.
# LLM이 답변 표 작성 시 control 전 데이터가 아닌 최종 상태를 보도록 하기 위함
# (3단계 파이프라인은 control_relay 직전에 데이터를 수집하므로, 응답 자체에
# 변경 후 스냅샷이 없으면 LLM이 옛 데이터를 표에 박아 환각이 발생함).
# 실패 시 None 반환 — 호출자는 응답 dict 에 조건부 포함하면 됨.
# ────────────────────────────────────────────────────────────────────
def _build_post_control_snapshot(farm_id, house_id):
    try:
        from agri_ai_core.src.postgresql.reader import read_latest_relay_info
        from agri_ai_core.config.mappers import get_relay_mapping
        relay = read_latest_relay_info(farm_id, house_id)
        if not relay:
            return None
        mapping = get_relay_mapping(house_id)
        on_devices, off_devices = [], []
        for col, rd in mapping.items():
            value = relay.get(col)
            if value is None:
                continue
            label = rd.kor_func or rd.sem
            (on_devices if value else off_devices).append(label)
        return {"ON": on_devices, "OFF": off_devices}
    except Exception as e:
        logger.warning(f"[post_state] 스냅샷 조회 실패 farm={farm_id} house={house_id}: {e}")
        return None


# ────────────────────────────────────────────────────────────────────
# 릴레이 제어용 house_id/farm_id를 정규화하고 검증한다. (house_id, farm_id) 또는 에러 dict 반환.
# auth_farm_id 가 전달되면 농장 접근권(자기 농장만 제어 가능) 도 검증한다.
# house_id='0' 은 물리 장치 미존재로 항상 거부한다 (권한 무관).
# ────────────────────────────────────────────────────────────────────
def _resolve_relay_ids(house_id, farm_id, auth_farm_id=None):
    from agri_ai_core.src.postgresql.connection import db_session
    from agri_ai_core.src.postgresql.queries import GET_ONE_FARM
    # 0호 거부 가드 — house_id='0' 은 어떤 사용자도 제어 불가 (통합재배사, 물리 장치 없음)
    zero_err = _require_non_zero_house(house_id)
    if zero_err:
        return zero_err
    target_house_id = _normalize_id(house_id)
    if not target_house_id:
        return {"success": False, "error": "house_id를 확인할 수 없습니다. 구체적 재배사 번호 또는 'all' 을 사용하세요."}
    target_farm_id = _normalize_id(farm_id)
    if not target_farm_id or target_farm_id == "0":
        target_farm_id = None
    if not target_farm_id:
        with db_session() as database:
            farm = database.fetch_one(GET_ONE_FARM)
            if farm and farm.get("farm_id") is not None:
                target_farm_id = str(farm.get("farm_id"))
    if not target_farm_id:
        return {"success": False, "error": "farm_id를 확인할 수 없습니다."}
    # 농장 접근권 검증 — 시스템관리자(auth_farm_id=None/0)는 전 농장, 농장관리자는 자기 농장만
    access_err = _check_farm_access(auth_farm_id, target_farm_id)
    if access_err:
        return access_err
    return target_house_id, target_farm_id


# ────────────────────────────────────────────────────────────────────
# AI 환경 판단을 안전하게 호출 (실패해도 None 반환).
# ────────────────────────────────────────────────────────────────────
def _get_ai_judgment_safe(farm_id, house_id):
    try:
        from agri_ai_core.src.control.manual_control import get_ai_environment_judgment
        return get_ai_environment_judgment(farm_id, house_id)
    except Exception as e:
        logger.warning(f"[AI판단] 조회 실패: {e}")
        return None


# ────────────────────────────────────────────────────────────────────
# [deprecated] 히터 쿨다운 미지원 — 항상 None 반환.
# 호환을 위해 시그니처만 유지. 호출자는 결과를 무시해도 됨.
# ────────────────────────────────────────────────────────────────────
def _get_heater_cooldown_warning(farm_id, house_id, device_name: str, action: str):
    return None


# ────────────────────────────────────────────────────────────────────
# house_id='all' 요청 시 모든 재배사(hous_id!=0)에 대해 일괄 제어.
# auth_farm_id 전달 시 farm 접근권(자기 농장만)도 검증한다.
# ────────────────────────────────────────────────────────────────────
def _control_relay_all_houses(device_name: str = None, action: str = None, farm_id: str = None,
                               mode: str = None, devices: list = None,
                               auth_farm_id: str = None) -> Dict[str, Any]:
    from agri_ai_core.src.postgresql.connection import db_session
    from agri_ai_core.src.postgresql.queries import GET_ONE_FARM, GET_ALL_HOUSES
    t_start = time.time()
    target_farm_id = _normalize_id(farm_id)
    if not target_farm_id or target_farm_id == "0":
        target_farm_id = None
    if not target_farm_id:
        with db_session() as database:
            farm = database.fetch_one(GET_ONE_FARM)
            if farm and farm.get("farm_id") is not None:
                target_farm_id = str(farm.get("farm_id"))
    if not target_farm_id:
        return {"success": False, "error": "farm_id를 확인할 수 없습니다."}
    # 농장 접근권 검증 (시스템관리자 auth_farm_id=None/0 → 전체 허용, 농장관리자는 자기 농장만)
    access_err = _check_farm_access(auth_farm_id, target_farm_id)
    if access_err:
        return access_err
    with db_session() as database:
        houses = database.fetch_all(GET_ALL_HOUSES, vals=(target_farm_id,), as_dict=True)
    if not houses:
        return {"success": False, "error": "재배사 정보를 조회할 수 없습니다."}
    # device_name이 있으면 mode 무시 — 특정 장치만 제어
    eff_action = action
    eff_mode = mode
    if device_name and mode in ("all_off", "all_on"):
        eff_action = "off" if mode == "all_off" else "on"
        eff_mode = None
    results = []
    for house in houses:
        h_id = str(house.get("hous_id", ""))
        if not h_id or h_id == "0":
            continue
        if devices and isinstance(devices, list) and len(devices) > 0:
            r = control_relays_batch(house_id=h_id, devices=devices,
                                     farm_id=target_farm_id, mode=eff_mode)
        else:
            r = control_relay(house_id=h_id, device_name=device_name, action=eff_action,
                              farm_id=target_farm_id, mode=eff_mode)
        results.append({"house_id": h_id, "result": r})
    success_count = sum(1 for r in results if r["result"].get("success"))
    total = len(results)
    elapsed = time.time() - t_start
    logger.info(f"[릴레이전체제어] 완료 ({elapsed:.1f}s) {success_count}/{total}개 재배사 성공")
    _first_ok = next((r["result"] for r in results if r["result"].get("success")), {})
    ret = {
        "success": success_count == total and total > 0,
        "message": f"전체 {total}개 재배사({', '.join(r['house_id']+'호' for r in results if r['result'].get('success'))}) 제어 완료.",
        "farm_id": target_farm_id,
        "controlled_houses": [r["house_id"] for r in results if r["result"].get("success")],
        # 각 재배사별 변경 직후 실제 ON/OFF 스냅샷 포함 — LLM 표 작성 시 환각 방지
        "results": [{"house_id": r["house_id"], "success": r["result"].get("success"),
                     "message": r["result"].get("message", ""),
                     "post_state": r["result"].get("post_state")} for r in results],
    }
    if _first_ok.get("ai_judgment"):
        ret["ai_judgment"] = _first_ok["ai_judgment"]
    if _first_ok.get("ai_conflict"):
        ret["ai_conflict"] = _first_ok["ai_conflict"]
    return ret


# ────────────────────────────────────────────────────────────────────
# LLM 이 호출하는 단일 릴레이 제어 진입점.
# auth_farm_id 는 세션 사용자(시스템관리자=None, 농장관리자=자기농장ID)의 권한 검증용.
# ────────────────────────────────────────────────────────────────────
def control_relay(house_id: str, device_name: str = None, action: str = None,
                   farm_id: str = None, mode: str = None,
                   auth_farm_id: str = None) -> Dict[str, Any]:
    # house_id='all' → 전 재배사 일괄 제어
    if str(house_id or "").strip().lower() in ("all", "전체", "모든"):
        return _control_relay_all_houses(device_name=device_name, action=action,
                                         farm_id=farm_id, mode=mode,
                                         auth_farm_id=auth_farm_id)
    # mode가 지정된 경우 일괄 제어로 위임
    if mode in ("reverse_all", "all_on", "all_off"):
        return control_relays_batch(house_id=house_id, farm_id=farm_id, mode=mode,
                                    auth_farm_id=auth_farm_id)

    t_start = time.time()
    logger.info(f"[릴레이제어] 시작 farm_id={farm_id} house_id={house_id} device={device_name} action={action}")
    logger.info(f"[릴레이제어] 제어 시도 house_id={house_id} device={device_name} action={action} mode={mode}")
    try:
        from agri_ai_core.src.control.relay_manager import set_relay_value
        from agri_ai_core.src.control.control_common import SEMANTIC_LABELS, set_llm_relay_lock, resolve_device_alias

        ids = _resolve_relay_ids(house_id, farm_id, auth_farm_id=auth_farm_id)
        if isinstance(ids, dict):
            return ids
        target_house_id, target_farm_id = ids

        if action not in ("on", "off", "reverse"):
            return {"success": False, "error": f"잘못된 action입니다: {action} (on/off/reverse만 가능)"}

        device_name = resolve_device_alias(device_name)
        valid_devices = set(SEMANTIC_LABELS.keys())
        if device_name not in valid_devices:
            return {
                "success": False,
                "error": f"잘못된 device_name입니다: {device_name}",
                "valid_devices": list(valid_devices),
            }

        ai_judgment = _get_ai_judgment_safe(target_farm_id, target_house_id)

        # action='reverse': 현재 상태 조회 후 반전
        if action == "reverse":
            from agri_ai_core.src.postgresql.reader import read_latest_relay_info
            from agri_ai_core.src.control.control_common import get_pin_map
            current = read_latest_relay_info(target_farm_id, target_house_id)
            pin_map = get_pin_map(target_house_id)
            pin_key = pin_map.get(device_name)
            current_value = bool(current.get(pin_key, False)) if (current and pin_key) else False
            relay_value = not current_value
        else:
            relay_value = (action == "on")
        relay_settings = {device_name: relay_value}
        result = set_relay_value(target_farm_id, target_house_id, relay_settings)
        if isinstance(result, dict) and result.get("success"):
            try:
                from agri_ai_core.src.control.ai_decision_log import record_external_action
                record_external_action("채팅지시", target_farm_id, target_house_id,
                                       relay_settings, "사용자 채팅 지시로 릴레이 제어")
            except Exception:
                pass

        elapsed = time.time() - t_start
        device_label = SEMANTIC_LABELS.get(device_name, device_name)
        action_label = "켜기(ON)" if relay_value else "끄기(OFF)"

        ai_conflict = _build_ai_conflict(ai_judgment, relay_settings)

        if result.get("success"):
            # LLM 제어 잠금 설정 (자동제어 스케줄러 충돌 방지)
            set_llm_relay_lock(target_farm_id, target_house_id)
            logger.info(f"[릴레이제어] 완료 ({elapsed:.1f}s) {device_label} → {action_label} (LLM 잠금 설정)")
            # 히터 계열 ON 시 쿨다운 경고 (실행은 이미 성공, 안내만 추가)
            heater_warn = _get_heater_cooldown_warning(
                target_farm_id, target_house_id, device_name, action,
            )
            # 변경 직후 실제 ON/OFF 스냅샷 — LLM 표 작성 시 환각 방지용
            post_state = _build_post_control_snapshot(target_farm_id, target_house_id)
            resp = {
                "success": True,
                "message": (f"{target_house_id}호 재배사의 {device_label}을(를) {action_label} 처리했습니다. "
                            f"⚠ 이 제어는 1회성 — 사용자가 유지를 요청했다면 set_admin_directive 를 즉시 추가 호출하고, 호출 전에는 유지된다고 답하지 마세요."),
                "farm_id": target_farm_id,
                "house_id": target_house_id,
                "device_name": device_name,
                "device_label": device_label,
                "action": action,
                "applied_value": relay_value,
                "ai_judgment": ai_judgment,
                "ai_conflict": ai_conflict,
                "post_state": post_state,
            }
            if heater_warn:
                resp["warnings"] = [heater_warn]
            return resp
        else:
            logger.warning(f"[릴레이제어] 실패 ({elapsed:.1f}s): {result.get('message')}")
            return {
                "success": False,
                "error": result.get("message", "릴레이 값 설정에 실패했습니다."),
                "farm_id": target_farm_id,
                "house_id": target_house_id,
                "device_name": device_name,
            }

    except Exception as e:
        elapsed = time.time() - t_start
        logger.error(f"[릴레이제어] 오류 ({elapsed:.1f}s): {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════
# 릴레이 다중 일괄 제어
# 여러 장치를 한 번에 제어한다 (LLM의 반복 tool call 횟수 절감).
# ══════════════════════════════════════════════════════════════
def _batch_build_by_mode(target_farm_id, target_house_id, mode, valid_devices, SEMANTIC_LABELS, reverse_pin_map):
    from agri_ai_core.src.postgresql.reader import read_latest_relay_info

    current = read_latest_relay_info(target_farm_id, target_house_id)
    if not current:
        return {}, [], {"success": False, "error": "현재 릴레이 상태를 조회할 수 없습니다."}

    relay_settings = {}
    results_detail = []
    rev_map = reverse_pin_map(target_house_id)
    for pin_key, semantic_name in rev_map.items():
        if semantic_name not in valid_devices:
            continue
        current_value = bool(current.get(pin_key, False))
        label = SEMANTIC_LABELS.get(semantic_name, semantic_name)

        if mode == "reverse_all":
            new_value = not current_value
        elif mode == "all_on":
            new_value = True
        else:  # all_off
            new_value = False

        relay_settings[semantic_name] = new_value
        prev_status = "ON(작동중)" if current_value else "OFF(미작동)"
        new_status = "ON(작동중)" if new_value else "OFF(미작동)"
        action_label = "켜기(ON)" if new_value else "끄기(OFF)"
        results_detail.append({
            "device": semantic_name,
            "label": label,
            "pin": pin_key,
            "action": action_label,
            "prev_status": prev_status,
            "new_status": new_status,
            "success": True,
        })
    logger.info(f"[릴레이일괄제어] mode={mode} → {len(relay_settings)}개 장치 설정 생성")
    return relay_settings, results_detail, None


# ────────────────────────────────────────────────────────────────────
# devices 배열 기반 개별 릴레이 설정 계산.
# Returns: (relay_settings dict, results_detail list)
# ────────────────────────────────────────────────────────────────────
def _batch_build_by_devices(devices, valid_devices, SEMANTIC_LABELS):
    relay_settings = {}
    results_detail = []
    for item in devices:
        device_name = item.get("device_name", "")
        action = item.get("action", "")

        if device_name not in valid_devices:
            results_detail.append({"device": device_name, "success": False, "error": "잘못된 device_name"})
            continue
        if action not in ("on", "off"):
            results_detail.append({"device": device_name, "success": False, "error": "잘못된 action"})
            continue

        relay_settings[device_name] = (action == "on")
        label = SEMANTIC_LABELS.get(device_name, device_name)
        action_label = "켜기(ON)" if action == "on" else "끄기(OFF)"
        results_detail.append({"device": device_name, "label": label, "action": action_label, "success": True})
    return relay_settings, results_detail


# ────────────────────────────────────────────────────────────────────
# 재배사의 여러 릴레이 장치를 일괄 제어한다.
# mode 우선 (reverse_all/all_on/all_off) → mode 없으면 devices 배열 사용.
# 제어 후 LLM 잠금을 설정하여 자동제어가 일정시간 억제된다.
# ────────────────────────────────────────────────────────────────────
def control_relays_batch(house_id: str, devices: List[Dict[str, str]] = None,
                         farm_id: str = None, mode: str = None,
                         auth_farm_id: str = None) -> Dict[str, Any]:
    t_start = time.time()
    logger.info(f"[릴레이일괄제어] 시작 farm_id={farm_id} house_id={house_id} mode={mode} devices={len(devices or [])}건")
    try:
        from agri_ai_core.src.control.relay_manager import set_relay_value
        from agri_ai_core.src.control.control_common import (
            SEMANTIC_LABELS, set_llm_relay_lock, reverse_pin_map,
        )

        ids = _resolve_relay_ids(house_id, farm_id, auth_farm_id=auth_farm_id)
        if isinstance(ids, dict):
            return ids
        target_house_id, target_farm_id = ids

        valid_devices = set(SEMANTIC_LABELS.keys())

        if mode in ("reverse_all", "all_on", "all_off"):
            relay_settings, results_detail, err = _batch_build_by_mode(
                target_farm_id, target_house_id, mode, valid_devices, SEMANTIC_LABELS, reverse_pin_map
            )
            if err is not None:
                return err
        elif devices and isinstance(devices, list):
            relay_settings, results_detail = _batch_build_by_devices(devices, valid_devices, SEMANTIC_LABELS)
        else:
            return {"success": False, "error": "mode 또는 devices 파라미터가 필요합니다."}

        if not relay_settings:
            return {"success": False, "error": "유효한 장치 설정이 없습니다.", "details": results_detail}

        ai_judgment = _get_ai_judgment_safe(target_farm_id, target_house_id)
        result = set_relay_value(target_farm_id, target_house_id, relay_settings)
        if isinstance(result, dict) and result.get("success"):
            try:
                from agri_ai_core.src.control.ai_decision_log import record_external_action
                record_external_action("채팅지시", target_farm_id, target_house_id,
                                       relay_settings, "사용자 채팅 지시로 릴레이 제어")
            except Exception:
                pass
        ai_conflict = _build_ai_conflict(ai_judgment, relay_settings)

        elapsed = time.time() - t_start
        if result.get("success"):
            set_llm_relay_lock(target_farm_id, target_house_id)
            controlled_labels = [d["label"] for d in results_detail if d.get("success")]
            # 변경 직후 실제 ON/OFF 스냅샷 — LLM 표 작성 시 환각 방지용
            post_state = _build_post_control_snapshot(target_farm_id, target_house_id)
            logger.info(f"[릴레이일괄제어] 완료 ({elapsed:.1f}s) {len(controlled_labels)}건 (LLM 잠금 설정)")
            return {
                "success": True,
                "message": (f"{target_house_id}호 재배사의 {len(controlled_labels)}개 장치를 일괄 제어했습니다. "
                            f"⚠ 이 제어는 1회성 — 사용자가 유지를 요청했다면 set_admin_directive 를 즉시 추가 호출하고, 호출 전에는 유지된다고 답하지 마세요."),
                "farm_id": target_farm_id,
                "house_id": target_house_id,
                "controlled_count": len(controlled_labels),
                "details": results_detail,
                "ai_judgment": ai_judgment,
                "ai_conflict": ai_conflict,
                "post_state": post_state,
            }
        else:
            logger.warning(f"[릴레이일괄제어] 실패 ({elapsed:.1f}s): {result.get('message')}")
            return {
                "success": False,
                "error": result.get("message", "릴레이 일괄 설정에 실패했습니다."),
                "details": results_detail,
            }

    except Exception as e:
        elapsed = time.time() - t_start
        logger.error(f"[릴레이일괄제어] 오류 ({elapsed:.1f}s): {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "error": str(e)}
