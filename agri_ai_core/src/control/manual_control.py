# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# 환경제어 모듈.
# 센서값 기반 릴레이 자동 제어 알고리즘 (온도/습도/CO2).
# 생육단계별 제어, 비상제어, 외부순환, 64케이스 분기를 포함한다.
# --->
# _log_house_status: log house status
# _classify / _is_external_normal / _is_internal_abnormal: 환경 분류
# _build_device_settings / _determine_devices / _determine_circulation / _check_emergency
# _build_relay_values / _write_relay / _execute_control
# _execute_water_temp_emergency / _handle_ai_emergency
# _determine_environment_action: 센서 → 장치/순환모드 결정
# get_ai_environment_judgment: 현재 센서값 기반 알고리즘 최적 릴레이 상태 (실제 제어 없음)
# control_manual_environment / control_all_manual / _ai_control_loop / start_ai_control_loop / stop_ai_control_loop
# trigger_algorithm_now : algorithm 모드 throttle reset (사용자 설정 변경 시 즉시 1회 실행)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
import os
import time
import traceback
from datetime import datetime, timedelta

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
from agri_ai_core.src.postgresql import queries as dbQry
from agri_ai_core.src.postgresql.reader import read_current_sensor_info, read_latest_relay_info, read_current_growth_stage
from agri_ai_core.src.control.relay_manager import set_relay_value
from agri_ai_core.src.control.schedule_control import control_lighting_schedule, control_irrigation_schedule
from agri_ai_core.src.control.control_common import (
    RELAY_COUNT,
    sort_houses as _sort_houses,
    house_prefix as _house_prefix,
    get_pin_map as _get_pin_map,
    format_sensor_parts,
    format_device_decision,
    format_relay_on_str,
    format_relay_off_str,
    is_llm_relay_locked,
    CIRCULATION_MODES,
    DAMPER_FAN_DELAY_SEC,
)
# [2026-04-28 rev2] 센서 임계값은 모두 ai_thresholds 경유 — control_common 의
# 임계 상수 직접 import 금지.
# 순수 판단 로직은 environment_logic.py로 분리됨 (L6 동급 import)
from agri_ai_core.src.control.environment_logic import (
    _classify,
    _is_external_normal,
    _is_internal_abnormal,
    _build_device_settings,
    _determine_devices,
    _determine_circulation,
    _check_emergency,
    _apply_fog_coupling,
)

logger = setup_logger(__name__)


# ═════════════════════════════════════════
# 헬퍼 함수
# 센서 현황(INFO) + 릴레이 상세(DEBUG) 로그
# ═════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 센서 현황(INFO) + 릴레이 상세(DEBUG) 한 재배사 헬퍼.
# ────────────────────────────────────────────────────────────────────
def _log_house_status(farm_id, house_id, order_label=""):
    scope = _house_prefix(order_label, farm_id, house_id)

    sensor = read_current_sensor_info(farm_id, house_id)
    sensor_str = format_sensor_parts(sensor)
    if sensor_str:
        logger.info(f"{scope}: 센서 현황 - {sensor_str}")
    else:
        logger.info(f"{scope}: 센서 데이터 없음")

    relay = read_latest_relay_info(farm_id, house_id)
    if relay:
        logger.debug(f"{scope}: 릴레이 ON → [{format_relay_on_str(relay, house_id)}]")
        logger.debug(f"{scope}: 릴레이 OFF → [{format_relay_off_str(relay, house_id)}]")


# _classify, _is_external_normal, _is_internal_abnormal,
# _build_device_settings, _determine_devices, _determine_circulation,
# _check_emergency 는 environment_logic.py로 분리됨 (상단 import)




# ═══════════════════════════════════════════════════
# semantic 설정을 relay_*st_flag 16개 딕셔너리로 변환
# ═══════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 시멘틱 설정을 relay_*st_flag 16개 dict 로 변환.
# [2026-05-01] "배수밸브 상시 ON" 강제 제거 — mappers.py 룰: 수온히터 ON 시
#   배수밸브 OFF 필수(가온 효과 위해 물 가둠). semantic_settings(=AI 결정) 또는
#   current_relay(=현재 DB 값)를 우선 존중하도록 정책 변경.
#   조명·관수와 동일하게 current_relay 보존, 미존재 시만 default ON 폴백.
# 우선순위: semantic_settings > current_relay > default(False, drainage 만 True 폴백)
# ────────────────────────────────────────────────────────────────────
def _build_relay_values(house_id, semantic_settings, current_relay, harvest_mode):
    pin_map = _get_pin_map(house_id)

    relay_values = {f"relay_{i}st_flag": False for i in range(1, RELAY_COUNT + 1)}

    # 현재 조명/관수/배수밸브 상태 보존 — semantic_settings 가 명시하면 그것이 최우선
    drainage_pin = pin_map.get('drainage_motor_flag')
    if current_relay:
        lighting_pin = pin_map.get('lighting_flag')
        irrigation_pin = pin_map.get('irrigation_flag')
        if lighting_pin:
            relay_values[lighting_pin] = bool(current_relay.get(lighting_pin, False))
        if irrigation_pin:
            relay_values[irrigation_pin] = bool(current_relay.get(irrigation_pin, False))
        if drainage_pin:
            # 배수밸브 default True (지하수 정상 흐름 — 안전 폴백)
            relay_values[drainage_pin] = bool(current_relay.get(drainage_pin, True))
    elif drainage_pin:
        relay_values[drainage_pin] = True  # current_relay 비어 있을 때만 default ON

    # 수확기: 관수 강제 OFF
    if harvest_mode:
        irrigation_pin = pin_map.get('irrigation_flag')
        if irrigation_pin:
            relay_values[irrigation_pin] = False

    # semantic 설정 적용 — 최우선 (AI 결정의 drainage_motor_flag 도 여기서 반영됨)
    for name, value in semantic_settings.items():
        pin_key = pin_map.get(name)
        if pin_key:
            relay_values[pin_key] = value

    return relay_values


# ────────────────────────────────────────────────────────────────────
# raw_mode=True 로 set_relay_value 호출 — 16개 핀 직접 쓰기.
# ────────────────────────────────────────────────────────────────────
def _write_relay(farm_id, house_id, relay_values):
    return set_relay_value(farm_id, house_id, relay_values, raw_mode=True)


# ═════════════════════════════════════════════════
# 2단계 릴레이 제어 (밸브 → 15초 → 팬)
# ═════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 2단계 릴레이 제어 (Phase1 밸브+장치 → 15초 → Phase2 팬).
# rev4 · 2026-04-27: Phase 1 팬 = current AND target 으로 valve OFF 안전 보장.
# ────────────────────────────────────────────────────────────────────
def _execute_control(
    farm_id,
    house_id,
    device_settings,
    circulation_mode,
    current_relay,
    harvest_mode,
    reason="",
    order_label="",
):
    pin_map = _get_pin_map(house_id)

    circ = CIRCULATION_MODES.get(circulation_mode, CIRCULATION_MODES['내부순환'])

    # 수확기: 배기순환 우선
    if harvest_mode and circulation_mode == '내부순환':
        circulation_mode = '배기순환'
        circ = CIRCULATION_MODES['배기순환']

    # === Phase 1: 밸브 + 장치 (팬 시퀀스 대기) ===
    phase1_semantic = {}

    # 순환 밸브 설정
    phase1_semantic.update(circ['dampers'])

    # ────────────────────────────────────────────────────────────────
    # [2026-05-04 Phase B] 현상유지 패턴 — None 또는 미명시 키는 current_relay 보존.
    # 사용자 원칙: 운용모드(또는 비상 오버라이드) 가 명시한 장치만 변경.
    # 명시 안 한 장치는 _build_relay_values 가 current_relay 값으로 채움.
    # ────────────────────────────────────────────────────────────────
    for _key in ('water_heater_flag', 'fog_occurs_flag', 'drainage_motor_flag'):
        _v = device_settings.get(_key)
        if _v is not None:
            phase1_semantic[_key] = bool(_v)

    # 팬: Phase 1 = current AND target (rev4 · 2026-04-27)
    # [변경 사유] 기존 "현재 상태 유지" 는 새 mode 에서 OFF 가 될 팬을 ON 으로
    # 끌고 가서 valve OFF 전이 시 인터록 게이트(Rule 3/4)에 의해 valve 가 차단됨.
    # current AND target 으로 처리하면 OFF 될 팬은 Phase 1 에서 미리 OFF 되어
    # 같은 쓰기에서 valve OFF 가 안전하게 통과. ON 으로 켤 팬은 Phase 1 에선
    # 그대로 OFF 두었다 Phase 2 에서 ON (밸브 dwell 충족 후).
    new_intake_fan  = bool(circ['fans'].get('intake_fan_flag', False))
    new_exhaust_fan = bool(circ['fans'].get('exhaust_fan_flag', False))
    if current_relay:
        intake_pin = pin_map.get('intake_fan_flag')
        exhaust_pin = pin_map.get('exhaust_fan_flag')
        cur_intake  = bool(current_relay.get(intake_pin, False)) if intake_pin else False
        cur_exhaust = bool(current_relay.get(exhaust_pin, False)) if exhaust_pin else False
        phase1_semantic['intake_fan_flag']  = cur_intake  and new_intake_fan
        phase1_semantic['exhaust_fan_flag'] = cur_exhaust and new_exhaust_fan
    else:
        phase1_semantic['intake_fan_flag']  = False
        phase1_semantic['exhaust_fan_flag'] = False

    # Phase 1 쓰기
    logger.debug(f"Phase 1 릴레이 시멘틱 설정: {phase1_semantic}")
    phase1_values = _build_relay_values(house_id, phase1_semantic, current_relay, harvest_mode)
    _write_relay(farm_id, house_id, phase1_values)

    scope = _house_prefix(order_label, farm_id, house_id)
    logger.info(f"{scope}: Phase 1 밸브제어 완료 ({reason}, {circulation_mode})")

    # === 15초 대기 (밸브→팬) ===
    time.sleep(DAMPER_FAN_DELAY_SEC)

    # === Phase 2: 팬 최종 상태 ===
    phase2_semantic = dict(phase1_semantic)
    phase2_semantic.update(circ['fans'])

    # Phase 2 쓰기
    logger.debug(f"Phase 2 릴레이 시멘틱 설정: {phase2_semantic}")
    phase2_values = _build_relay_values(house_id, phase2_semantic, current_relay, harvest_mode)
    result = _write_relay(farm_id, house_id, phase2_values)

    logger.info(f"{scope}: Phase 2 팬  제어 완료 ({reason}, {circulation_mode})")

    return {
        "success": result.get("success", False),
        "reason": reason,
        "circulation": circulation_mode,
        "devices": device_settings,
        "message": f"{reason} → {circulation_mode}",
    }


# ═════════════════════════════════════════════
# 수온 비상 전용 (수온히터만 변경, 나머지 유지)
# ═════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 수온 비상 전용 — 수온히터·포그만 변경, 나머지 릴레이는 현재 상태 그대로.
# fog_on 은 호출자(_check_emergency → _apply_fog_coupling) 결과를 그대로 반영.
# ────────────────────────────────────────────────────────────────────
def _execute_water_temp_emergency(
    farm_id,
    house_id,
    water_heater_on,
    current_relay,
    harvest_mode,
    order_label="",
    fog_on=None,       # [2026-05-04] None=current 보존 (사용자 정책 #4 — 현상유지)
                       # True/False = 명시 강제. 수온저하비상은 True, 수온과열비상은 None.
    drainage_on=None,  # [2026-05-01] 수온히터·배수밸브 상호배타 룰 적용용.
                       # None=current 보존 / True=ON / False=OFF.
                       # 사용자 정책 #4: 수온과열비상 시 None (현상유지).
):
    pin_map = _get_pin_map(house_id)

    relay_values = {f"relay_{i}st_flag": False for i in range(1, RELAY_COUNT + 1)}

    # 현재 상태 전체 복사 — 명시 강제(True/False) 가 아닌 장치는 그대로 유지.
    if current_relay:
        for key in relay_values:
            relay_values[key] = bool(current_relay.get(key, False))

    # [2026-05-04 rev3] 수온히터/포그 결정 — None 시 current 보존.
    # 수온저하비상(수온 < critical_low): heater=ON, fog=ON (가열 시퀀스).
    # 수온과열비상(수온 > critical_high): heater=OFF, fog/drainage=None (현상유지).
    water_heater_pin = pin_map.get('water_heater_flag')
    if water_heater_pin:
        relay_values[water_heater_pin] = bool(water_heater_on)
    fog_pin = pin_map.get('fog_occurs_flag')
    if fog_pin and fog_on is not None:
        relay_values[fog_pin] = bool(fog_on)
    # 배수밸브 — None 이면 current 보존 (사용자 정책 #4).
    drainage_pin = pin_map.get('drainage_motor_flag')
    if drainage_pin and drainage_on is not None:
        relay_values[drainage_pin] = bool(drainage_on)

    # 수확기: 관수 강제 OFF
    if harvest_mode:
        irrigation_pin = pin_map.get('irrigation_flag')
        if irrigation_pin:
            relay_values[irrigation_pin] = False

    result = _write_relay(farm_id, house_id, relay_values)

    status = "ON" if water_heater_on else "OFF"
    scope = _house_prefix(order_label, farm_id, house_id)
    logger.info(f"{scope}: 수온 비상 → 수온히터 {status}")

    return {
        "success": result.get("success", False),
        "reason": f"수온비상_수온히터{status}",
        "message": f"수온 비상제어 → 수온히터 {status}",
    }


# ══════════════════════════════════════════════════════════════════
# AI 모드 비상제어 공통 처리
# control_all_manual, control_all_ai 양쪽에서 사용
# Returns: (result, True) if emergency handled, (None, False) if not
# ══════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# AI 모드 비상제어 공통 처리 — control_all_manual / control_all_ai 양쪽 사용.
# Returns: (result, True) if emergency handled, (None, False) if not.
# ────────────────────────────────────────────────────────────────────
def _handle_ai_emergency(farm_id, house_id, growth_stage, order_label=""):
    sensor_data = read_current_sensor_info(farm_id, house_id)
    if not sensor_data:
        return None, False

    # [2026-04-28 fix] 재배사별 동적 임계값 ts + 결합규칙 후처리 — AI 모드 비상에도
    # _determine_environment_action 과 동일한 정확도 적용. 수정 전: ts 미전달로
    # 99호 같이 임계 컬럼 NULL 인 재배사가 폴백값으로 잘못 비상 트립 + fog 강제 ON.
    from agri_ai_core.src.control.ai_thresholds import get_thresholds
    ts = get_thresholds(farm_id, house_id)
    is_emergency, emergency_devices, emergency_circulation, water_temp_only = \
        _check_emergency(sensor_data, ts)
    if not is_emergency:
        return None, False

    # 결합규칙 후처리 (수온 < ts.water_temp_low 이면 fog OFF 강제) — 알고리즘 모드와
    # 일관 적용. 수온저하비상이라도 수온이 정상 도달하지 않은 시점에는 fog OFF.
    emergency_devices = _apply_fog_coupling(
        emergency_devices, sensor_data, scope="[AI비상]", ts=ts,
    )

    current_relay = read_latest_relay_info(farm_id, house_id)
    harvest_mode = (growth_stage == '수확기')

    # [2026-04-28] 비상제어를 단계화 — 14단계 LLM 흐름이 SKIP 되는 케이스도
    # 공통 [AI비상 N/3] 또는 [AI수온비상 N/2] 로 표시. 슬래시 뒤가 항상 전체 단계 수.
    # [2026-04-28] step 헤더는 단순 "0-99" 만 — order_label 의 [AI재배사 N/M] 은
    # 매 단계 중복 출력 회피.
    scope_pref = _house_prefix("", farm_id, house_id)
    from agri_ai_core.src.control.ai_step_logger import AiStepLogger

    if water_temp_only:
        steps = AiStepLogger(scope=scope_pref, total=2, prefix='AI수온비상')
        steps.step("수온비상 감지",
                   extra=f"수온 {sensor_data.get('water_temperature')}℃ → "
                         f"수온히터={'ON' if emergency_devices.get('water_heater_flag') else 'OFF'}")
        steps.detail(
            f"센서 스냅샷: 내부 {sensor_data.get('indoor_temperature')}℃ / "
            f"{sensor_data.get('indoor_humidity')}% / CO2 {sensor_data.get('co2')}ppm / "
            f"수온 {sensor_data.get('water_temperature')}℃",
            "→ 운용모드 fallback, 다른 장치는 현상 유지 (water_temp_only)",
        )
    else:
        steps = AiStepLogger(scope=scope_pref, total=3, prefix='AI비상')
        steps.step("환경비상 감지",
                   extra=f"내부 {sensor_data.get('indoor_temperature')}℃/"
                         f"{sensor_data.get('indoor_humidity')}% · "
                         f"CO2 {sensor_data.get('co2')}ppm")
        steps.detail(
            f"센서 스냅샷: 내부 {sensor_data.get('indoor_temperature')}℃ / "
            f"{sensor_data.get('indoor_humidity')}% / CO2 {sensor_data.get('co2')}ppm / "
            f"외부 {sensor_data.get('outdoor_temperature')}℃ / 수온 {sensor_data.get('water_temperature')}℃",
            "→ 운용모드 fallback, 비상 오버라이드만 강제 적용",
        )
        steps.step("강제 결정 산출",
                   extra=f"순환={emergency_circulation} / 강제장치={format_device_decision(emergency_devices)}")
        steps.detail(
            f"emergency_devices = {emergency_devices}",
            f"emergency_circulation = {emergency_circulation}",
            f"harvest_mode = {harvest_mode}",
        )

    if water_temp_only:
        steps.step("수온비상 적용 실행", extra="다른 장치 현상유지")
        # [2026-05-04] fog_on/drainage_on 둘 다 None 허용 — 사용자 정책 #4 의
        # "수온히터만 OFF, 다른 장치 현상유지" 흐름 보존. _check_emergency 가
        # 능동 냉각이 필요할 때만 True/False 명시.
        result = _execute_water_temp_emergency(
            farm_id, house_id,
            emergency_devices.get('water_heater_flag', False),
            current_relay, harvest_mode, order_label=order_label,
            fog_on=emergency_devices.get('fog_occurs_flag'),
            drainage_on=emergency_devices.get('drainage_motor_flag'),
        )
        steps.detail(
            f"수온히터 강제={'ON' if emergency_devices.get('water_heater_flag') else 'OFF'}",
            f"포그생성 강제={'ON' if emergency_devices.get('fog_occurs_flag') else 'OFF'}",
        )
        # [Phase 3] 수온 비상 알림 발행
        try:
            from agri_ai_core.src.ai import alert_bus as _ab
            _ab.publish(
                level="warning", category="water",
                farm_id=farm_id, house_id=house_id,
                title=f"수온 비상 제어 ({house_id}호)",
                message=f"수온 {sensor_data.get('water_temperature','?')}℃ → 수온히터 "
                        f"{'ON' if emergency_devices.get('water_heater_flag') else 'OFF'} 자동 적용",
                data={"sensor": sensor_data, "water_heater": bool(emergency_devices.get('water_heater_flag'))},
            )
        except Exception:
            pass
        # [2026-05-01] 비상제어 fallback 분기에도 결정 이력 DB 적재
        # — 사용자 정오 운영 내역 조회 시 1/2/3호 비상제어가 누락되지 않도록.
        try:
            from agri_ai_core.src.control.ai_decision_log import record_decision
            record_decision(
                farm_id, house_id, growth_stage=growth_stage,
                action="emergency_water_temp", circulation=None,
                water_heater=bool(emergency_devices.get('water_heater_flag')),
                fog_occurs=bool(emergency_devices.get('fog_occurs_flag')),
                reason=f"수온비상 자동제어 (수온={sensor_data.get('water_temperature')}℃)",
                sensor_snapshot=sensor_data,
            )
        except Exception as _e:
            logger.debug(f"[수온비상] 결정이력 기록 실패: {_e}")
        steps.done(summary="수온비상 적용 완료")
    else:
        steps.step("강제 적용 (2-phase)", extra=f"{emergency_circulation} / 운용모드 fallback")
        result = _execute_control(
            farm_id, house_id, emergency_devices, emergency_circulation,
            current_relay, harvest_mode, reason="AI모드_비상제어", order_label=order_label
        )
        # [2026-05-01] 환경비상 fallback 분기에도 결정 이력 DB 적재
        try:
            from agri_ai_core.src.control.ai_decision_log import record_decision
            record_decision(
                farm_id, house_id, growth_stage=growth_stage,
                action="emergency_environment", circulation=emergency_circulation,
                water_heater=bool(emergency_devices.get('water_heater_flag')),
                fog_occurs=bool(emergency_devices.get('fog_occurs_flag')),
                reason=(f"환경비상 자동제어 (내부={sensor_data.get('indoor_temperature')}℃ "
                        f"/ {sensor_data.get('indoor_humidity')}% / CO2={sensor_data.get('co2')}ppm)"),
                sensor_snapshot=sensor_data,
            )
        except Exception as _e:
            logger.debug(f"[환경비상] 결정이력 기록 실패: {_e}")
        # 16개 릴레이 비트맵
        try:
            applied = (result or {}).get('devices') if isinstance(result, dict) else None
            if isinstance(applied, dict):
                bitmap = ", ".join(
                    f"r{i}={'ON' if applied.get(f'relay_{i}st_flag') else 'OFF'}"
                    for i in range(1, 17)
                )
                steps.detail(f"적용된 16개 릴레이: [{bitmap}]")
        except Exception as _e:
            steps.detail(f"(비트맵 추출 실패: {_e})")

        # [Phase 3] 비상제어 알림 발행
        try:
            from agri_ai_core.src.ai import alert_bus as _ab
            indoor_temp = sensor_data.get('indoor_temperature')
            indoor_hum = sensor_data.get('indoor_humidity')
            co2 = sensor_data.get('co2')
            _ab.publish(
                level="critical", category="control",
                farm_id=farm_id, house_id=house_id,
                title=f"비상 제어 발동 ({house_id}호)",
                message=(f"센서: 온도 {indoor_temp}℃ · 습도 {indoor_hum}% · CO2 {co2}ppm → "
                         f"순환={emergency_circulation}, 강제장치={format_device_decision(emergency_devices)}"),
                data={"sensor": sensor_data, "devices": emergency_devices, "circulation": emergency_circulation},
            )
        except Exception:
            pass
        steps.done(summary=f"{emergency_circulation} 강제 적용 완료")
    return result, True


# ═══════════════════════════════════════════════════════════════════
# 공통 환경판단 로직
# get_ai_environment_judgment()와 control_manual_environment()가 공유
# ═══════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 센서 데이터 기반 장치/순환모드 결정 — 판단 결과 dict 반환.
# 비상→발이기→외부정상+내부비정상→64케이스 우선순위로 분기.
# Returns dict {sensor, growth_stage, reason, devices, circulation,
#   device_summary, is_emergency, water_temp_only} 또는 센서 부족 시 None.
# ────────────────────────────────────────────────────────────────────
def _determine_environment_action(sensor_data, growth_stage, farm_id, house_id):
    indoor_temp = sensor_data.get('indoor_temperature')
    indoor_humidity = sensor_data.get('indoor_humidity')
    outdoor_temp = sensor_data.get('outdoor_temperature')
    outdoor_humidity = sensor_data.get('outdoor_humidity')
    co2 = sensor_data.get('co2')

    sensor_str = format_sensor_parts(sensor_data)

    # [2026-04-28] 재배사별 동적 임계값 로드 (DB SENSOR_M_SETTING) — 캐시 5분
    from agri_ai_core.src.control.ai_thresholds import get_thresholds
    ts = get_thresholds(farm_id, house_id)
    bud_low, bud_high = ts.budding_temp_low, ts.budding_temp_high

    # ────────────────────────────────────────────────────────────────
    # [2026-05-04 Phase C] 사용자 원칙 — 비상 시에도 64케이스 결정 산출 후
    # 그 위에 비상 오버라이드 적용. 더 이상 조기 반환 안 함.
    # is_emergency 만 추출하여 결과 dict 의 메타로 표시 (적용은 호출자에서).
    # ────────────────────────────────────────────────────────────────
    from agri_ai_core.src.control.environment_logic import _emergency_override
    _is_emerg_meta, _, _, _wto_meta = _emergency_override(sensor_data, ts)

    # (2) 발이기 판단 — 가열 시 수온히터 ON
    # [2026-04-28] 수온히터 ON 시 포그생성도 동반 ON (열기 재배사 유입 매개체)
    if growth_stage == '발이기':
        if indoor_temp is None:
            return None
        if indoor_temp < bud_low:
            devices = _build_device_settings(water_heater=True, fog=True)
            reason, circ = "발이기_가열", "내부순환"
        elif indoor_temp > bud_high:
            devices = _build_device_settings()
            reason, circ = "발이기_냉각", "배기순환"
        else:
            devices = _build_device_settings()
            reason, circ = "발이기_정상", "순환정지"
        devices = _apply_fog_coupling(devices, sensor_data, scope="[발이기]")
        # [2026-05-04 Phase C] 발이기 결정 위에 비상 오버라이드
        from agri_ai_core.src.control.environment_logic import apply_emergency_override as _aeo
        devices, circ, applied = _aeo(devices, circ, sensor_data, ts)
        if applied:
            reason = f"{reason} + 비상오버라이드"
        return {
            "sensor": sensor_str, "growth_stage": growth_stage, "reason": reason,
            "devices": devices, "circulation": circ,
            "device_summary": format_device_decision(devices),
            "is_emergency": applied, "water_temp_only": _wto_meta,
        }

    # (3) 외부정상 + 내부비정상 → 외부순환
    if _is_external_normal(outdoor_temp, outdoor_humidity, ts) and \
       _is_internal_abnormal(indoor_temp, indoor_humidity, co2, ts):
        devices = _build_device_settings()
        devices = _apply_fog_coupling(devices, sensor_data, scope="[외부순환]")
        # [2026-05-04 Phase C] 외부정상+내부비정상 결정 위에 비상 오버라이드
        from agri_ai_core.src.control.environment_logic import apply_emergency_override as _aeo
        devices, circ_x, applied = _aeo(devices, "외부순환", sensor_data, ts)
        return {
            "sensor": sensor_str, "growth_stage": growth_stage,
            "reason": "외부정상+내부비정상" + (" + 비상오버라이드" if applied else ""),
            "devices": devices, "circulation": circ_x,
            "device_summary": format_device_decision(devices),
            "is_emergency": applied, "water_temp_only": _wto_meta,
        }

    # (4) 64케이스 — 임계값은 ts 우선, 없으면 control_common 폴백
    temp_state = _classify(indoor_temp, ts.temp_low, ts.temp_high)
    humidity_state = _classify(indoor_humidity, ts.humidity_low, ts.humidity_high)
    co2_state = _classify(co2, ts.co2_low, ts.co2_high)
    ext_temp_state = 'normal' if (outdoor_temp is not None and ts.temp_low <= outdoor_temp <= ts.temp_high) else 'abnormal'
    ext_humidity_state = 'normal' if (outdoor_humidity is not None and ts.humidity_low <= outdoor_humidity <= ts.humidity_high) else 'abnormal'
    ext_co2_state = 'normal'

    water_heater, fog_pump = _determine_devices(temp_state, humidity_state)

    circulation_mode = _determine_circulation(temp_state, ext_temp_state, humidity_state, ext_humidity_state, co2_state, ext_co2_state)

    harvest_mode = (growth_stage == '수확기')
    if harvest_mode and circulation_mode == '내부순환':
        circulation_mode = '배기순환'

    devices = _build_device_settings(water_heater, fog_pump)
    devices = _apply_fog_coupling(devices, sensor_data, scope="[64케이스]")

    # ────────────────────────────────────────────────────────────────
    # [2026-05-04 사용자 정의] 64-케이스 결정 위에 계절 분기 override 적용.
    # 저온계절(외기<내부+내부<적정하한): 가열 시퀀스 그대로, 실내≥적정상한 시 heater OFF
    # 고온계절(외기≥내부 또는 내부 적정 안): heater 절대 OFF, 내부>적정상한 시 fog+drainage+내부순환
    # ────────────────────────────────────────────────────────────────
    from agri_ai_core.src.control.environment_logic import (
        _determine_season, _apply_season_override,
    )
    season = _determine_season(indoor_temp, outdoor_temp, ts)
    devices, circulation_mode = _apply_season_override(
        devices, circulation_mode, season, indoor_temp, ts,
    )

    reason = f"64케이스(온도:{temp_state},습도:{humidity_state},CO2:{co2_state},계절:{season})"

    # ────────────────────────────────────────────────────────────────
    # [2026-05-04 Phase C] 사용자 원칙 — 운용 결정 위에 비상 오버라이드.
    # 64케이스 결정 + 계절 override 산출 후 비상 위반 항목만 덮어쓰기.
    # 비상은 계절 룰보다 항상 우선.
    # ────────────────────────────────────────────────────────────────
    from agri_ai_core.src.control.environment_logic import apply_emergency_override
    final_devices, final_circ, applied_emerg = apply_emergency_override(
        devices, circulation_mode, sensor_data, ts,
    )
    if applied_emerg:
        reason = f"{reason} + 비상오버라이드"

    return {
        "sensor": sensor_str, "growth_stage": growth_stage,
        "reason": reason,
        "devices": final_devices, "circulation": final_circ,
        "device_summary": format_device_decision(final_devices),
        "is_emergency": applied_emerg, "water_temp_only": _wto_meta,
    }


# ══════════════════════════════════════════════════════
# AI 환경 판단 (제어 없이 판단만 수행)
# 수동 릴레이 제어 시 전/후 AI 판단을 제공하기 위한 함수
# ══════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 현재 센서값 기반 알고리즘이 판단한 최적 릴레이 상태 반환 (실제 제어 없음).
# 수동 릴레이 제어 UI 에서 전/후 AI 판단 표시용.
# ────────────────────────────────────────────────────────────────────
def get_ai_environment_judgment(farm_id, house_id):
    try:
        sensor_data = read_current_sensor_info(farm_id, house_id)
        if not sensor_data:
            return None

        growth_stage = read_current_growth_stage(farm_id, house_id) or '생육기'
        result = _determine_environment_action(sensor_data, growth_stage, farm_id, house_id)
        if not result:
            return None

        return {
            "sensor": result["sensor"],
            "growth_stage": result["growth_stage"],
            "reason": result["reason"],
            "devices": result["devices"],
            "circulation": result["circulation"],
            "device_summary": result["device_summary"],
        }

    except Exception as e:
        logger.error(f"AI 환경 판단 오류: {e}")
        return None


# ══════════════════
# 환경제어 메인 함수
# ══════════════════
# ────────────────────────────────────────────────────────────────────
# 알고리즘 환경제어 메인 함수 — 5단계 흐름.
# [2026-04-28] AI 모드와 동일한 [<MODE> N/M] 단계 로그 적용.
# 흐름: 센서/릴레이 → 판단 → 비상/일반 분기 → 2-phase 실행 → 완료.
# ────────────────────────────────────────────────────────────────────
def control_manual_environment(farm_id, house_id, growth_stage='생육기', order_label=""):
    try:
        scope = _house_prefix(order_label, farm_id, house_id)
        # [2026-04-28] step scope 는 단순 "N-M" 만 — order_label 의 [재배사 N/M] 은
        # 매 단계 중복 출력 회피.
        step_scope = _house_prefix("", farm_id, house_id)
        # AiStepLogger 를 prefix='ALGO' 로 재사용 — 동급 import 룰 위반 아님 (M3 모듈은
        # 의존성 0, 어디서든 import 가능한 공용 포맷터).
        from agri_ai_core.src.control.ai_step_logger import AiStepLogger
        steps = AiStepLogger(scope=step_scope, total=5, prefix='ALGO')

        # ─── [ALGO 1/5] 센서/릴레이 조회 ───
        sensor_data = read_current_sensor_info(farm_id, house_id)
        if not sensor_data:
            steps.skip("센서/릴레이 조회", reason="센서 데이터 없음")
            return {"success": False, "message": "센서 데이터 없음"}
        current_relay = read_latest_relay_info(farm_id, house_id)
        harvest_mode = (growth_stage == '수확기')
        steps.step("센서/릴레이 조회",
                   extra=f"내부 {sensor_data.get('indoor_temperature')}℃/"
                         f"{sensor_data.get('indoor_humidity')}% · "
                         f"CO2 {sensor_data.get('co2')}ppm · "
                         f"수온 {sensor_data.get('water_temperature')}℃")
        steps.detail(
            f"외부 {sensor_data.get('outdoor_temperature')}℃ / "
            f"{sensor_data.get('outdoor_humidity')}%",
            f"릴레이 ON: [{format_relay_on_str(current_relay or {}, house_id)}]",
            f"릴레이 OFF: [{format_relay_off_str(current_relay or {}, house_id)}]",
            f"수확기={'Y' if harvest_mode else 'N'} · 생육단계={growth_stage}",
        )

        # ─── [ALGO 2/5] 환경 판단 (64케이스 / 비상 / 외부정상+내부비정상) ───
        action = _determine_environment_action(sensor_data, growth_stage, farm_id, house_id)
        if not action:
            steps.skip("환경 판단", reason="센서 부족 — 판단 불가")
            return {"success": False, "message": "판단 불가"}
        steps.step("환경 판단",
                   extra=f"{action['reason']} → {action.get('circulation') or '(수온비상)'}")
        steps.detail(
            f"reason={action['reason']}",
            f"circulation={action.get('circulation')}",
            f"devices={action.get('devices')}",
            f"is_emergency={action['is_emergency']} · water_temp_only={action['water_temp_only']}",
        )

        # ─── [ALGO 3/5] 분기 처리 (비상/일반) ───
        if action["is_emergency"]:
            steps.step("비상제어 분기", extra=action["reason"])
            steps.detail(
                f"비상 사유: 내부온도={sensor_data.get('indoor_temperature')}℃ · "
                f"습도={sensor_data.get('indoor_humidity')}% · CO2={sensor_data.get('co2')}ppm · "
                f"수온={sensor_data.get('water_temperature')}℃",
            )
            if action["water_temp_only"]:
                steps.step("수온비상 단독 실행", extra="다른 장치 유지")
                result = _execute_water_temp_emergency(
                    farm_id, house_id,
                    action["devices"].get('water_heater_flag', False),
                    current_relay, harvest_mode, order_label=order_label,
                    fog_on=action["devices"].get('fog_occurs_flag', False),
                )
                steps.done(
                    summary=f"수온히터={action['devices'].get('water_heater_flag')} · "
                            f"포그={action['devices'].get('fog_occurs_flag')}"
                )
                return result
            steps.step("비상 2-phase 실행", extra=f"{action['circulation']} 강제")
            result = _execute_control(
                farm_id, house_id, action["devices"], action["circulation"],
                current_relay, harvest_mode, reason="비상제어", order_label=order_label
            )
            steps.done(summary=f"{action['circulation']} 비상 적용")
            return result

        if action["reason"] == "외부정상+내부비정상":
            steps.step("일반 분기", extra="외부정상+내부비정상 → 외부순환")
        else:
            steps.step("일반 분기", extra=f"64케이스 → {action['circulation']}")
        steps.detail(
            f"최종 결정: 수온히터={action['devices'].get('water_heater_flag')} · "
            f"포그={action['devices'].get('fog_occurs_flag')} · "
            f"순환={action['circulation']}"
        )

        # ─── [ALGO 4/5] 2-phase 릴레이 실행 ───
        steps.step("2-phase 릴레이 실행", extra="밸브 → 15s 대기 → 팬")
        result = _execute_control(
            farm_id, house_id, action["devices"], action["circulation"],
            current_relay, harvest_mode,
            reason=action["reason"], order_label=order_label,
        )

        # ─── [ALGO 5/5] 적용 결과 로그 ───
        try:
            applied = (result or {}).get('devices') if isinstance(result, dict) else None
            if isinstance(applied, dict):
                bitmap = ", ".join(
                    f"r{i}={'ON' if applied.get(f'relay_{i}st_flag') else 'OFF'}"
                    for i in range(1, 17)
                )
                steps.step("결정 적용 완료", extra=f"{action['circulation']}")
                steps.detail(f"적용된 16개 릴레이: [{bitmap}]")
            else:
                steps.step("결정 적용 완료", extra=f"{action['circulation']}")
        except Exception as _e:
            steps.step("결정 적용 완료", extra=f"비트맵 추출 실패: {_e}")

        steps.done(summary=f"{action['circulation']} 적용")
        return result

    except Exception as e:
        scope = _house_prefix(order_label, farm_id, house_id)
        logger.error(f"알고리즘 환경제어 오류 ({scope}): {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "message": f"오류 발생: {str(e)}"}


# ════════════════════
# 전체 재배사 환경제어
# ════════════════════
# ────────────────────────────────────────────────────────────────────
# 재배사 레코드에서 짧은 모드명 추출 (control_all_manual 내부 헬퍼).
# ────────────────────────────────────────────────────────────────────
def _mode_short_of(h):
    if not h.get("mnul_ctrl_flag"):
        return "수동제어"
    elif h.get("ctrl_type") == "ai":
        return "인공지능"
    else:
        return "알고리즘"


# ────────────────────────────────────────────────────────────────────
# 재배사 순서 + 모드 접두사 로그 출력 — 단일 모드면 prefix 통일.
# ────────────────────────────────────────────────────────────────────
def _log_house_order_prefix(ordered_houses):
    mode_set = set(_mode_short_of(h) for h in ordered_houses if h.get("hous_id") is not None)
    if len(mode_set) == 1:
        all_mode_prefix = mode_set.pop()
        house_order = ", ".join(
            str(h.get("hous_id")) for h in ordered_houses if h.get("hous_id") is not None
        )
    else:
        all_mode_prefix = ""
        house_order = ", ".join(
            f"{h.get('hous_id')}({_mode_short_of(h)})"
            for h in ordered_houses if h.get("hous_id") is not None
        )
    if house_order:
        logger.info(f"{all_mode_prefix} 환경제어 대상 순서: {house_order}")


# ────────────────────────────────────────────────────────────────────
# 재배사별 조명/관수 스케줄 제어 실행 + 로그 출력.
# ────────────────────────────────────────────────────────────────────
def _run_schedules_for_house(farm_id, house_id, order_label):
    logger.info("-")
    light_result = control_lighting_schedule(farm_id, house_id)
    irrigation_result = control_irrigation_schedule(farm_id, house_id)
    sched_parts = [
        f"조명 {light_result.get('status', '-')}",
        f"관수 {irrigation_result.get('status', '-')}",
    ]
    sched_schedules = list(light_result.get("schedules", [])) + list(irrigation_result.get("schedules", []))
    sched_info = f" (스케줄: {', '.join(sched_schedules)})" if sched_schedules else ""
    logger.info(
        f"{order_label} {farm_id}-{house_id}: "
        f"{' / '.join(sched_parts)}{sched_info}"
    )


# ────────────────────────────────────────────────────────────────────
# 재배사 설정 + 생육단계로부터 모드 라벨/단축명 결정.
# Returns: (mode_label, mode_short).
# ────────────────────────────────────────────────────────────────────
def _determine_mode_label(house, growth_stage):
    mnul_ctrl_flag = house.get("mnul_ctrl_flag")
    ctrl_type = house.get("ctrl_type", "algorithm")
    if not mnul_ctrl_flag:
        return "사용자 직접입력 모드", "수동제어"
    if ctrl_type == 'ai':
        return "AI 제어 모드", "인공지능"
    if growth_stage == '휴지기':
        return "휴지기", "휴지기"
    return "알고리즘 수동제어", "알고리즘"


# ────────────────────────────────────────────────────────────────────
# AI 제어 모드 재배사 처리 — 비상제어(하드 리밋) + 모니터링(소프트 긴급).
# Returns: (result_dict_or_None, success_delta, fail_delta).
# ────────────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────────────
# [2026-05-04] LLM 호출 연속 실패 카운터 (재배사별).
# AI 모드에서 LLM 응답 실패가 반복되면 algorithm 모드 결정으로 자동 전환.
# 임계 N회 도달 시 _determine_environment_action 의 64케이스 결정 적용.
# 카운터는 LLM 정상 응답 시 0 으로 reset.
# ────────────────────────────────────────────────────────────────────
_LLM_FAIL_COUNTER = {}
_LLM_FAIL_THRESHOLD = 3


def _process_ai_mode_house(farm_id, house_id, growth_stage, order_label):
    # [2026-05-04 G6] AI 모드 5초 주기 호출 — 결정/제어 미적용.
    #   60초 _ai_control_loop 가 단독 결정자 (LLM + emergency_override 통합).
    #   본 함수는 모니터링 로깅만 수행하여 비상 임계 근접/트렌드 급변 가시성 유지.
    #   배경 — 5초 주기 algorithm_fallback 적용 시 ai_decision_log 가 fallback 으로
    #   도배되어 다음 LLM cycle 의 "직전 결정 이력" 컨텍스트가 오염되는 부작용 방지.
    #   사용자 원칙 "AI 제어 완료 → 비상 → 완료" 와 일치. 비상 즉응성은 60초 cycle 내.
    try:
        import importlib
        _ai_mod = importlib.import_module('agri_ai_core.src.control.ai_control')
        monitor_ai_emergency = _ai_mod.monitor_ai_emergency

        from agri_ai_core.src.control.environment_logic import _check_emergency
        from agri_ai_core.src.control.ai_thresholds import get_thresholds as _get_ts
        sensor_data = read_current_sensor_info(farm_id, house_id) or {}
        ts = _get_ts(farm_id, house_id)
        is_emerg, _, _, _ = _check_emergency(sensor_data, ts) if sensor_data else (False, None, None, False)

        # 모니터링 로깅 — 결과는 활용하지 않으나 가시성 유지
        monitor_ai_emergency(farm_id, house_id, order_label)

        scope = _house_prefix(order_label, farm_id, house_id)
        if is_emerg:
            logger.info(f"{scope}: [AI모니터링] 비상 감지 — 60초 주기 LLM cycle 에서 emergency_override 적용 예정")
        else:
            logger.debug(f"{scope}: [AI모니터링] 정상 — LLM 미호출 주기")
        return None, 0, 0
    except Exception as e:
        logger.error(f"{order_label} AI 제어 예외: {e}")
        return None, 0, 0


# ────────────────────────────────────────────────────────────────────
# [2026-05-04] LLM 실패 반복 시 algorithm 모드 결정 적용.
# _determine_environment_action 의 64케이스 결정 (비상/발이기/외부정상+내부비정상/일반)
# 을 그대로 사용하여 _execute_control 로 적용.
# ────────────────────────────────────────────────────────────────────
def _execute_algorithm_fallback(farm_id, house_id, growth_stage, sensor_data, order_label):
    try:
        action = _determine_environment_action(sensor_data, growth_stage, farm_id, house_id)
        if not action:
            return None
        current_relay = read_latest_relay_info(farm_id, house_id) or {}
        harvest_mode = (growth_stage == '수확기')
        result = _execute_control(
            farm_id, house_id,
            action.get('devices') or {},
            action.get('circulation'),
            current_relay, harvest_mode,
            reason=f"algorithm_fallback({action.get('reason')})",
            order_label=order_label,
        )
        try:
            from agri_ai_core.src.control.ai_decision_log import record_decision
            devices = action.get('devices') or {}
            record_decision(
                farm_id, house_id, growth_stage=growth_stage,
                action='change', circulation=action.get('circulation'),
                water_heater=bool(devices.get('water_heater_flag')),
                fog_occurs=bool(devices.get('fog_occurs_flag')),
                reason=f"[algorithm_fallback] {action.get('reason')}",
                sensor_snapshot=sensor_data,
            )
        except Exception:
            pass
        return result
    except Exception as e:
        logger.error(f"{order_label} algorithm fallback 예외: {e}")
        return None


# ────────────────────────────────────────────────────────────────────
# 전체 환경제어 완료 요약 로그 — 단일 모드면 prefix 통일, 복합이면 분리.
# ────────────────────────────────────────────────────────────────────
def _log_completion_summary(mode_counts, total, success_count, fail_count):
    if len(mode_counts) == 1:
        done_prefix = list(mode_counts.keys())[0]
        logger.info(f"{done_prefix} 환경제어 완료: 총 {total}개 재배사 (성공: {success_count}, 실패: {fail_count})")
    else:
        mode_str = ", ".join(f"{k} {v}" for k, v in mode_counts.items())
        logger.info(f"환경제어 완료: {mode_str} (총 {total}개, 성공: {success_count}, 실패: {fail_count})")
    logger.info("-")


# ════════════════════════════════════════════════════════════════════
# [변경11 · 2026-04-30] algorithm 모드 throttle — 잡 주기 5초는 manual 즉시 반영용,
# algorithm 호기는 _ALGO_THROTTLE_SEC(기본 180초) 마다 1회 처리. 사용자 설정 변경
# 시 trigger_algorithm_now() 로 throttle reset → 다음 잡 사이클에서 즉시 실행.
# 영향: ai_control LLM 큐 압박 해소. manual/AI 모드는 영향 없음.
# ════════════════════════════════════════════════════════════════════
_ALGO_THROTTLE_SEC = int(os.environ.get('ALGO_THROTTLE_SEC', '180'))
_algo_last_run = {}   # (farm_id, house_id) → unix_ts


# ────────────────────────────────────────────────────────────────────
# algorithm 호기의 처리 가능 여부 — throttle 미만이면 False (skip).
# ────────────────────────────────────────────────────────────────────
def _should_run_algorithm(farm_id, house_id):
    last = _algo_last_run.get((farm_id, house_id), 0)
    return (time.time() - last) >= _ALGO_THROTTLE_SEC


# ────────────────────────────────────────────────────────────────────
# algorithm 호기의 last_run timestamp 갱신.
# ────────────────────────────────────────────────────────────────────
def _mark_algorithm_run(farm_id, house_id):
    _algo_last_run[(farm_id, house_id)] = time.time()


# ────────────────────────────────────────────────────────────────────
# algorithm 모드 throttle 즉시 reset — 사용자가 알고리즘 모드 진입/설정 변경 시
# 외부에서 호출 (예: tools_admin.set_house_control_mode mode='algorithm'). 다음
# relay_control_job 사이클(최대 5초)에서 즉시 1회 실행.
# farm_id/house_id 가 None 이면 전 호기 reset.
# ────────────────────────────────────────────────────────────────────
def trigger_algorithm_now(farm_id=None, house_id=None):
    if farm_id is None or house_id is None:
        _algo_last_run.clear()
        logger.info("[알고리즘 throttle] 전체 reset — 다음 사이클에서 모든 algorithm 호기 즉시 실행")
        return
    _algo_last_run.pop((farm_id, house_id), None)
    logger.info(
        f"[알고리즘 throttle] {farm_id}-{house_id} reset — 다음 사이클에서 즉시 실행"
    )


# ────────────────────────────────────────────────────────────────────
# 전체 재배사 수동/알고리즘/AI 환경제어 실행 (스케줄러 10초 주기).
# 모드별 인덱스 prefix 부여 [AI재배사 N/M] / [ALGO재배사 N/M] / [수동재배사 N/M].
# ────────────────────────────────────────────────────────────────────
def control_all_manual():
    try:
        with db_session() as database:
            houses = database.fetch_all(
                query=dbQry.GET_HOUSE_NAME,
                vals=(None, None, None, None),
                as_dict=True
            )

            if not houses:
                logger.warning("등록된 재배사가 없습니다")
                return {"success": True, "total": 0, "results": []}

            ordered_houses = _sort_houses(houses)
            _log_house_order_prefix(ordered_houses)

            results = []
            success_count = 0
            fail_count = 0
            mode_counts = {}  # 모드별 재배사 수 집계

            # [2026-04-28] 모드별 재배사 카운팅 — order_label 을 모드별 인덱스로
            # 부여하여 [AI재배사 1/N] / [수동재배사 1/N] / [ALGO재배사 1/N] 형태로
            # 일관된 prefix 사용. 14단계/5단계/4단계 진행과 명확히 구분.
            mode_total = {}
            for h in ordered_houses:
                if h.get("farm_id") is None or h.get("hous_id") is None:
                    continue
                _gs = read_current_growth_stage(h.get("farm_id"), h.get("hous_id")) or '생육기'
                _, _ms = _determine_mode_label(h, _gs)
                mode_total[_ms] = mode_total.get(_ms, 0) + 1
            mode_seen = {k: 0 for k in mode_total}

            for index, house in enumerate(ordered_houses, start=1):
                farm_id = house.get("farm_id")
                house_id = house.get("hous_id")

                if farm_id is None or house_id is None:
                    continue

                # 모드 사전 결정 (label 형성에 필요)
                _gs_for_label = read_current_growth_stage(farm_id, house_id) or '생육기'
                _, _ms_for_label = _determine_mode_label(house, _gs_for_label)
                mode_seen[_ms_for_label] = mode_seen.get(_ms_for_label, 0) + 1

                # 모드별 prefix — 슬래시 뒤가 항상 같은 모드의 전체 재배사 수
                _label_prefix = {
                    '인공지능': 'AI재배사',
                    '알고리즘': 'ALGO재배사',
                    '수동제어': '수동재배사',
                    '휴지기':   '휴지재배사',
                }.get(_ms_for_label, '재배사')
                order_label = (
                    f"[{_label_prefix} {mode_seen[_ms_for_label]}/{mode_total.get(_ms_for_label, 1)}]"
                )

                # 조명/관수 스케줄 제어
                _run_schedules_for_house(farm_id, house_id, order_label)

                # 생육단계 + 운용 모드 — label 형성 시 이미 조회·계산했으므로 재사용
                growth_stage = _gs_for_label
                mode_label, mode_short = _determine_mode_label(house, growth_stage)
                mode_counts[mode_short] = mode_counts.get(mode_short, 0) + 1

                logger.info(
                    f"{order_label} ──── {farm_id}-{house_id} "
                    f"──── {mode_label} (생육단계: {growth_stage})"
                )

                # AI 제어 모드 (10초 주기: 비상제어 + 모니터링만)
                if mode_label == "AI 제어 모드":
                    ai_result, s, f = _process_ai_mode_house(farm_id, house_id, growth_stage, order_label)
                    if ai_result is not None:
                        results.append({"farm_id": farm_id, "house_id": house_id, "result": ai_result})
                    success_count += s
                    fail_count += f
                    continue

                # 나머지 모드 (사용자 직접입력, 휴지기) → 센서/릴레이 현황만 로깅 후 스킵
                if mode_label != "알고리즘 수동제어":
                    _log_house_status(farm_id, house_id, order_label)
                    continue

                # ─── [변경11 · 2026-04-30] algorithm throttle (3분) ───
                # 잡 자체는 5초 주기로 모든 모드 순회 (manual 즉시 반영) — 다만 algorithm
                # 호기는 _ALGO_THROTTLE_SEC 마다 1회만 환경제어 실행. 사용자 알고리즘 설정
                # 변경 시 trigger_algorithm_now() 호출로 즉시 다음 사이클에서 실행됨.
                if not _should_run_algorithm(farm_id, house_id):
                    _log_house_status(farm_id, house_id, order_label)
                    continue
                _mark_algorithm_run(farm_id, house_id)

                # LLM 제어 잠금 체크
                if is_llm_relay_locked(farm_id, house_id):
                    scope = _house_prefix(order_label, farm_id, house_id)
                    logger.info(f"{scope}: LLM 제어 잠금 활성 → 자동제어 스킵")
                    _log_house_status(farm_id, house_id, order_label)
                    continue

                result = control_manual_environment(
                    farm_id, house_id, growth_stage, order_label=order_label,
                )

                if result.get("success"):
                    success_count += 1
                else:
                    fail_count += 1

                results.append({
                    "farm_id": farm_id,
                    "house_id": house_id,
                    "result": result
                })

            _log_completion_summary(mode_counts, len(results), success_count, fail_count)

            return {
                "success": fail_count == 0,
                "total": len(results),
                "success_count": success_count,
                "fail_count": fail_count,
                "results": results
            }

    except Exception as e:
        logger.error(f"전체 환경제어 오류: {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "message": f"오류 발생: {str(e)}"}


# ═══════════════════════════════════════════════════════════════════════
# AI 환경제어 순환 루프 (재배사 순환 + 30초 delay)
# 재배사를 ascending 순으로 순환하며 LLM 정기 호출
# 1재배사 제어 → 30초 대기 → 2재배사 → 30초 대기 → ... → 마지막 → 1재배사
# ═══════════════════════════════════════════════════════════════════════
from agri_ai_core.config import AI_CONTROL_LOOP_DELAY_SEC as _AI_LOOP_DELAY_SEC
_ai_loop_running = False
_ai_loop_thread = None


# ────────────────────────────────────────────────────────────────────
# AI 재배사 순환 제어 루프 (별도 스레드에서 실행).
# 1재배사 제어 → AI_LOOP_DELAY_SEC 대기 → 2재배사 → ... → 마지막 → 1재배사.
# ────────────────────────────────────────────────────────────────────
def _ai_control_loop():
    global _ai_loop_running
    _ai_loop_running = True
    logger.info(f"[AI순환루프] 시작 (재배사 간 {_AI_LOOP_DELAY_SEC}초 대기)")

    while _ai_loop_running:
        try:
            # 매 순환마다 AI 재배사 목록을 새로 조회 (모드 변경 반영)
            with db_session() as database:
                houses = database.fetch_all(
                    query=dbQry.GET_HOUSE_NAME,
                    vals=(None, None, None, None),
                    as_dict=True
                )

            if not houses:
                time.sleep(_AI_LOOP_DELAY_SEC)
                continue

            ordered_houses = _sort_houses(houses)
            ai_houses = [
                h for h in ordered_houses
                if h.get("mnul_ctrl_flag") and h.get("ctrl_type") == "ai"
                and h.get("farm_id") is not None and h.get("hous_id") is not None
            ]

            if not ai_houses:
                time.sleep(_AI_LOOP_DELAY_SEC)
                continue

            ai_order = ", ".join(str(h.get("hous_id")) for h in ai_houses)
            logger.info(f"[AI순환루프] 순환 시작: 대상 재배사 {ai_order} ({len(ai_houses)}개)")

            for index, house in enumerate(ai_houses, start=1):
                if not _ai_loop_running:
                    break

                farm_id = house.get("farm_id")
                house_id = house.get("hous_id")
                # [2026-04-28] AI 순환루프 재배사 순회 인덱스 — 14단계 [AI N/14] 와
                # 명확히 구분되도록 "AI재배사" prefix 사용.
                order_label = f"[AI재배사 {index}/{len(ai_houses)}]"

                growth_stage = read_current_growth_stage(farm_id, house_id) or '생육기'

                try:
                    import importlib
                    _ai_mod = importlib.import_module('agri_ai_core.src.control.ai_control')
                    control_ai_environment = _ai_mod.control_ai_environment

                    # [2026-05-04 Phase D rev2] 사용자 원칙 — LLM 호출 후 실패 시
                    # algorithm fallback (운용+비상 통합). _handle_ai_emergency 우회 제거.
                    result = control_ai_environment(farm_id, house_id, growth_stage, order_label)
                    action = result.get("action", "unknown")
                    llm_failed = (
                        action == 'keep' and 'LLM' in str(result.get('message', ''))
                    )
                    if llm_failed:
                        key = (farm_id, house_id)
                        _LLM_FAIL_COUNTER[key] = _LLM_FAIL_COUNTER.get(key, 0) + 1
                        cnt = _LLM_FAIL_COUNTER[key]
                        sensor_data = read_current_sensor_info(farm_id, house_id) or {}
                        algo_result = _execute_algorithm_fallback(
                            farm_id, house_id, growth_stage, sensor_data, order_label)
                        if algo_result is not None:
                            result = algo_result
                            action = result.get("action", "algorithm_fallback")
                            logger.warning(
                                f"{order_label} 재배사 {house_id}: LLM 실패 {cnt}회 → "
                                f"algorithm fallback → {action}"
                            )
                        else:
                            logger.info(f"{order_label} 재배사 {house_id}: LLM 실패 → algorithm 결정 없음, keep 유지")
                    else:
                        if _LLM_FAIL_COUNTER.get((farm_id, house_id)):
                            _LLM_FAIL_COUNTER[(farm_id, house_id)] = 0
                        logger.info(f"{order_label} 재배사 {house_id}: AI 제어 완료 → {action}")

                except Exception as e:
                    logger.error(f"{order_label} AI 제어 예외: {e}")
                    logger.error(traceback.format_exc())

                # 다음 재배사 전 30초 대기
                if _ai_loop_running:
                    logger.info(f"{order_label} 재배사 {house_id}: 제어 완료, {_AI_LOOP_DELAY_SEC}초 대기 후 다음 재배사")
                    time.sleep(_AI_LOOP_DELAY_SEC)

            # 마지막 재배사 완료 후 다시 1재배사부터 순환
            if _ai_loop_running:
                logger.info(f"[AI순환루프] 전체 순환 완료 ({len(ai_houses)}개 재배사), 다시 처음부터 순환")

        except Exception as e:
            logger.error(f"[AI순환루프] 루프 오류: {e}")
            logger.error(traceback.format_exc())
            if _ai_loop_running:
                time.sleep(_AI_LOOP_DELAY_SEC)

    logger.info("[AI순환루프] 종료")


# ────────────────────────────────────────────────────────────────────
# AI 순환 제어 루프를 별도 daemon 스레드로 시작.
# ────────────────────────────────────────────────────────────────────
def start_ai_control_loop():
    global _ai_loop_thread, _ai_loop_running
    if _ai_loop_thread and _ai_loop_thread.is_alive():
        logger.warning("[AI순환루프] 이미 실행 중")
        return

    import threading
    _ai_loop_running = True
    _ai_loop_thread = threading.Thread(target=_ai_control_loop, daemon=True, name="ai_control_loop")
    _ai_loop_thread.start()
    logger.info("[AI순환루프] 스레드 시작됨")


# ────────────────────────────────────────────────────────────────────
# AI 순환 제어 루프 정지 — _ai_loop_running=False 로 graceful 종료.
# ────────────────────────────────────────────────────────────────────
def stop_ai_control_loop():
    global _ai_loop_running
    _ai_loop_running = False
    logger.info("[AI순환루프] 정지 요청됨")
