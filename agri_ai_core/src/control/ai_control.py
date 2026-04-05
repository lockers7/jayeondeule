# ════════════════════════════════════════
# AI 릴레이 제어 모듈.
#
# LLM이 센서값·릴레이·생육단계·최적조건을 종합 분석하여 릴레이를 결정.
# 센서 트렌드 분석으로 임계치 도달 전 선행(예방) 제어를 수행한다.
# ════════════════════════════════════════
import os
import re
import json
import time
import traceback
from decimal import Decimal
from collections import deque
from datetime import datetime

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import get_ollama_url, get_model_name
from agri_ai_core.src.postgresql.reader import (
    read_current_sensor_info,
    read_latest_relay_info,
    read_optimal_condition,
)
from agri_ai_core.src.control.control_common import (
    house_prefix,
    get_pin_map,
    format_sensor_parts,
    format_relay_on_str,
    format_relay_off_str,
    format_device_decision,
    SEMANTIC_LABELS,
    CIRCULATION_MODES,
    TEMP_LOW, TEMP_HIGH, TEMP_CRITICAL_LOW, TEMP_CRITICAL_HIGH,
    HUMIDITY_LOW, HUMIDITY_HIGH, HUMIDITY_CRITICAL_LOW, HUMIDITY_CRITICAL_HIGH,
    CO2_LOW, CO2_HIGH, CO2_CRITICAL_HIGH,
    WATER_TEMP_LOW, WATER_TEMP_HIGH, WATER_TEMP_CRITICAL_LOW, WATER_TEMP_CRITICAL_HIGH,
    HEATER_MAX_CONTINUOUS_MIN, HEATER_COOLDOWN_MIN,
)
from agri_ai_core.src.control.control_common import check_heater_cooldown
from agri_ai_core.src.control.manual_control import _execute_control

logger = setup_logger(__name__)

# 설정
# ══════════════════
AI_CONTROL_TIMEOUT = int(os.getenv("AI_CONTROL_TIMEOUT", "60"))
AI_PROXIMITY_RATIO = float(os.getenv("AI_PROXIMITY_RATIO", "0.8"))

VALID_CIRCULATIONS = set(CIRCULATION_MODES.keys())
PROTECTED_DEVICES = {'lighting_flag', 'irrigation_flag', 'drainage_motor_flag'}


# 인메모리 상태 추적
# ══════════════════
_sensor_history = {}


def _to_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


# 상세 로깅 함수 (공통 포맷팅 함수 활용)
# 센서 현황 + 릴레이 상태 로그 (AI 태그)
# ═════════════════════════
def _log_ai_status(scope, sensor_data, current_relay, house_id):
    sensor_str = format_sensor_parts(sensor_data, include_outdoor=True)
    if sensor_str:
        logger.info(f"{scope}: [AI] 센서 현황 - {sensor_str}")
    else:
        logger.info(f"{scope}: [AI] 센서 데이터 없음")

    if current_relay:
        logger.info(f"{scope}: [AI] 현재 릴레이 ON → [{format_relay_on_str(current_relay, house_id)}]")
        logger.info(f"{scope}: [AI] 현재 릴레이 OFF → [{format_relay_off_str(current_relay, house_id)}]")
    else:
        logger.info(f"{scope}: [AI] 릴레이 정보 없음")


# AI 판단 결과 상세 로그
# ══════════════════
def _log_ai_decision(scope, action, reason, devices=None, circulation=None):
    if action == "keep":
        logger.info(f"{scope}: [AI] 판단: 현상 유지 → {reason}")
        return

    # action == "change"
    if devices:
        logger.info(
            f"{scope}: [AI] 판단: 제어 변경 → {circulation} | "
            f"{format_device_decision(devices)} | 사유: {reason}"
        )
    else:
        logger.info(f"{scope}: [AI] 판단: 제어 변경 → {circulation} | 사유: {reason}")


# 트렌드 분석 (선행 조치 핵심)
# 최근 30회 센서값으로 기울기 분석 → 임계치 도달 예측
# ═══════════════════════════════
def _detect_trend(farm_id, house_id, sensor_data):
    key = (farm_id, house_id)
    if key not in _sensor_history:
        _sensor_history[key] = deque(maxlen=30)
    history = _sensor_history[key]

    history.append({
        'temp': sensor_data.get('indoor_temperature'),
        'humidity': sensor_data.get('indoor_humidity'),
        'co2': sensor_data.get('co2'),
        'timestamp': datetime.now(),
    })

    if len(history) < 3:
        return False, ""

    # 기울기 계산 (분당 변화율)
    trends = []
    trend_detected = False

    for metric, label, unit, critical_low, critical_high in [
        ('temp', '온도', '℃', TEMP_CRITICAL_LOW, TEMP_CRITICAL_HIGH),
        ('humidity', '습도', '%', HUMIDITY_CRITICAL_LOW, HUMIDITY_CRITICAL_HIGH),
        ('co2', 'CO2', 'ppm', None, CO2_CRITICAL_HIGH),
    ]:
        values = [(h[metric], h['timestamp']) for h in history if h[metric] is not None]
        if len(values) < 3:
            continue

        first_val, first_time = values[0]
        last_val, last_time = values[-1]
        first_val_f = _to_float(first_val)
        last_val_f = _to_float(last_val)
        if first_val_f is None or last_val_f is None:
            continue

        elapsed_min = (last_time - first_time).total_seconds() / 60
        if elapsed_min < 0.5:
            continue

        rate = (last_val_f - first_val_f) / elapsed_min

        # 5분 후 예측값
        predicted = last_val_f + rate * 5

        # 비상 임계치 도달 예측
        if critical_high is not None and rate > 0 and predicted > critical_high:
            trends.append(f"{label} 상승 추세 {rate:+.1f}{unit}/분 (5분 후 {predicted:.1f}{unit} 예측)")
            trend_detected = True
        elif critical_low is not None and rate < 0 and predicted < critical_low:
            trends.append(f"{label} 하강 추세 {rate:+.1f}{unit}/분 (5분 후 {predicted:.1f}{unit} 예측)")
            trend_detected = True
        elif abs(rate) > 0.1:
            direction = "상승" if rate > 0 else "하강"
            trends.append(f"{label} {direction} 추세 {rate:+.1f}{unit}/분")

    trend_info = ""
    if trends:
        trend_info = "추세 분석: " + ", ".join(trends)

    return trend_detected, trend_info


# 임계치 근접 판단
# 정상범위 이탈 후 비상 임계치까지 80% 이상 근접 여부
# ═══════════════════════════════
def _check_threshold_proximity(sensor_data):
    checks = [
        ('indoor_temperature', TEMP_LOW, TEMP_HIGH, TEMP_CRITICAL_LOW, TEMP_CRITICAL_HIGH),
        ('indoor_humidity', HUMIDITY_LOW, HUMIDITY_HIGH, HUMIDITY_CRITICAL_LOW, HUMIDITY_CRITICAL_HIGH),
        ('co2', CO2_LOW, CO2_HIGH, None, CO2_CRITICAL_HIGH),
    ]

    for key, normal_low, normal_high, critical_low, critical_high in checks:
        value = _to_float(sensor_data.get(key))
        if value is None:
            continue

        if value > normal_high and critical_high is not None:
            gap = critical_high - normal_high
            progress = (value - normal_high) / gap if gap > 0 else 1.0
            if progress >= AI_PROXIMITY_RATIO:
                return True

        if value < normal_low and critical_low is not None:
            gap = normal_low - critical_low
            progress = (normal_low - value) / gap if gap > 0 else 1.0
            if progress >= AI_PROXIMITY_RATIO:
                return True

    return False


# 10초 주기 AI 센서 모니터링 (긴급 개입 판단)
# 임계치 근접 OR 트렌드 급변 감지 시 True → 즉시 LLM 호출 필요
# ═════════════════════════════════════════
def monitor_ai_emergency(farm_id, house_id, order_label=""):
    scope = house_prefix(order_label, farm_id, house_id)

    sensor_data = read_current_sensor_info(farm_id, house_id)
    if not sensor_data:
        return False

    # 센서 이력 업데이트 + 트렌드 분석
    trend_detected, trend_info = _detect_trend(farm_id, house_id, sensor_data)

    # 임계치 근접 감지
    proximity_detected = _check_threshold_proximity(sensor_data)

    if proximity_detected:
        logger.info(f"{scope}: [AI모니터링] 임계치 근접 → 긴급 LLM 개입")
        return True

    if trend_detected:
        logger.info(f"{scope}: [AI모니터링] 트렌드 급변 → 긴급 LLM 개입")
        return True

    return False


# 시스템 프롬프트
# ══════════════════
def _build_system_prompt(growth_stage):
    base = (
        "/no_think\n"
        "당신은 상황버섯 스마트팜 릴레이 제어 전문 AI입니다.\n\n"
        "## 재배사 구조\n"
        "- 공기흐름: 바닥 2열 덕트 흡입 → 환풍기 → 열냉가습기 → 환풍기 → 상단 1열 덕트 배기\n"
        "- 열냉가습기: 지하수 탱크 + 물가열기 + 분사펌프 → 물안개를 통과하는 공기에 분사펌프 온도의 습기를 더하는장치\n\n"
        "## 제어 장치와 효과\n"
        "- water_heater_flag: 물가열기 → 열냉가습기 내 지하수 탱크의 물을 가열 → 수온 상승 → 내부온도·습도 동시 상승\n"
        "- fog_occurs_flag: 분사펌프 → 탱크물을 물안개로 강하게 분사 → 공기가 물안개 통과 시 습도 상승\n"
        f"- indoor_heater_flag: 열풍기 → 직접 가열 → 내부온도 급속 상승 (최대 {HEATER_MAX_CONTINUOUS_MIN}분 연속, {HEATER_COOLDOWN_MIN}분 쿨다운 필수)\n"
        "- indoor_heater_valve_flag: 열풍댐퍼 → 열풍기ON 전 반드시 먼저 ON, OFF 시 열풍기 먼저 OFF\n"
        "- intake_fan_flag: 흡기팬 → 흡기댐퍼와 연동, 외부 공기 유입\n"
        "- exhaust_fan_flag: 배기팬 → 배기댐퍼와 연동, 내부 공기 배출\n"
        "- air_circulation_valve_flag: 순환댐퍼 → 내부 공기 순환 경로 조절\n"
        "- air_intake_valve_flag: 흡기댐퍼 → 외부 공기 유입 경로 조절\n"
        "- air_exhaust_valve_flag: 배기댐퍼 → 내부 공기 배출 경로 조절\n"
        "- lighting_flag, irrigation_flag, drainage_motor_flag: 별도 스케줄 제어 → 변경 금지\n\n"
        "## 순환 모드 (댐퍼 설정 후 15초 뒤 팬 가동)\n"
        "- 내부순환: 순환댐퍼ON, 흡기댐퍼OFF, 배기댐퍼OFF → 흡기팬ON, 배기팬ON (내부 공기 순환, 온습도 유지)\n"
        "- 외부순환: 순환댐퍼OFF, 흡기댐퍼ON, 배기댐퍼ON → 흡기팬ON, 배기팬ON (내부공기를 외부공기로 대체)\n"
        "- 흡입순환: 순환댐퍼OFF, 흡기댐퍼ON, 배기댐퍼OFF → 흡기팬ON, 배기팬OFF (외부공기 유입으로 CO2 하락)\n"
        "- 배기순환: 순환댐퍼OFF, 흡기댐퍼OFF, 배기댐퍼ON → 흡기팬OFF, 배기팬ON (내부공기 배출로 CO2 하락)\n"
        "- 순환정지: 순환댐퍼ON, 흡기댐퍼ON, 배기댐퍼ON → 흡기팬OFF, 배기팬OFF\n\n"
        "## 제어 우선순위 (반드시 준수)\n"
        "온도 > 습도 > CO2 순서로 판단하고, 상위 항목의 결정을 하위 항목이 뒤집지 마세요.\n\n"
        "### 1순위: 온도\n"
        f"- 온도 < {TEMP_LOW}℃ (저온): 물가열기ON, 내부순환 → 가열 우선. 습도/CO2 조치가 온도를 더 낮추면 안 됨\n"
        f"- 온도 > {TEMP_HIGH}℃ (고온): 가열장치 전체OFF, 배기순환 → 냉각 우선. 습도 조치가 온도를 더 높이면 안 됨\n"
        "- 온도 정상: 다음 순위(습도)로 이동\n\n"
        "### 2순위: 습도 (온도 결정과 충돌 시 온도 우선)\n"
        f"- 습도 < {HUMIDITY_LOW}% (저습): 분사펌프ON + 내부순환 권장. 단, 온도가 고온이면 배기순환 유지\n"
        f"- 습도 > {HUMIDITY_HIGH}% (고습): 분사펌프OFF + 배기순환 권장. 단, 온도가 저온이면 내부순환 유지\n"
        "- 습도 정상: 다음 순위(CO2)로 이동\n\n"
        "### 3순위: CO2 (온도·습도 결정과 충돌 시 상위 우선)\n"
        f"- CO2 > {CO2_HIGH}ppm (고농도): 배기순환 권장. 단, 저온이면 내부순환 유지 (온도 우선)\n"
        "- CO2 정상: 현재 순환모드 유지\n\n"
        "### 복합 상황 판단 예시\n"
        "- 저온+고습: 열풍기ON + 내부순환 (온도 우선, 습도는 열풍으로 자연 하강)\n"
        "- 저온+저습: 물가열기ON + 분사펌프ON + 내부순환 (둘 다 가열/가습 방향 일치)\n"
        "- 고온+저습: 분사펌프ON + 배기순환 (온도 우선 냉각, 습도는 분사펌프로 보완)\n"
        "- 고온+고습: 전체OFF + 배기순환 (온도·습도 모두 하강 방향 일치)\n"
        "- 정상온도+고습+고CO2: 배기순환 (습도·CO2 동시 해소)\n"
        "- 정상온도+저습+고CO2: 내부순환 + 분사펌프ON (습도 우선, CO2는 차선)\n\n"
        "## 외부순환 제한 규칙\n"
        f"- 외부온도가 {TEMP_LOW}~{TEMP_HIGH}℃ 범위 밖이면 외부순환 금지\n"
        f"- 외부습도가 {HUMIDITY_LOW}~{HUMIDITY_HIGH}% 범위 밖이면 외부순환 금지\n"
        "- 위 조건 충족 시에는 장치 제어보다 외부순환을 우선 활용\n\n"
    )

    if growth_stage == '발이기':
        stage_guide = (
            "## 현재 생육단계: 발이기 (3~5일)\n"
            "- 적정 온도: 29~33℃ (온도 제어에만 집중)\n"
            "- 습도/CO2 제어 중지\n"
            "- 온도 < 29℃ → 물가열기ON + 열풍기ON + 내부순환\n"
            "- 온도 > 33℃ → 전체 가열OFF + 배기순환\n"
            "- 온도 정상(29~33℃) → 제어 없음\n\n"
        )
    elif growth_stage == '수확기':
        stage_guide = (
            "## 현재 생육단계: 수확기 (2~3일)\n"
            "- 관수밸브 강제 OFF (변경 금지)\n"
            "- 배기순환 우선\n"
            "- 이외 생육기 제어와 동일\n\n"
        )
    else:
        stage_guide = (
            "## 현재 생육단계: 생육기 (2~2.5개월)\n"
            f"- 적정 온도: {TEMP_LOW}~{TEMP_HIGH}℃ (임계: {TEMP_CRITICAL_LOW}~{TEMP_CRITICAL_HIGH}℃)\n"
            f"- 적정 습도: {HUMIDITY_LOW}~{HUMIDITY_HIGH}% (임계: {HUMIDITY_CRITICAL_LOW}~{HUMIDITY_CRITICAL_HIGH}%)\n"
            f"- 적정 CO2: {CO2_LOW}~{CO2_HIGH}ppm (최고임계: {CO2_CRITICAL_HIGH}ppm)\n"
            f"- 적정 수온: {WATER_TEMP_LOW}~{WATER_TEMP_HIGH}℃ (임계: {WATER_TEMP_CRITICAL_LOW}~{WATER_TEMP_CRITICAL_HIGH}℃)\n\n"
        )

    rules = (
        "## 비상 임계값 (절대 위반 금지)\n"
        f"- 온도 < {TEMP_CRITICAL_LOW}℃ → 물가열기+열풍기 ON, 내부순환\n"
        f"- 온도 > {TEMP_CRITICAL_HIGH}℃ → 전체 가열 OFF, 배기순환\n"
        f"- 습도 < {HUMIDITY_CRITICAL_LOW}% → 물가열기ON+분사펌프ON, 내부순환\n"
        f"- 습도 > {HUMIDITY_CRITICAL_HIGH}% → 분사펌프OFF, 배기순환\n"
        f"- CO2 > {CO2_CRITICAL_HIGH}ppm → 배기순환\n"
        f"- 수온 < {WATER_TEMP_CRITICAL_LOW}℃ → 물가열기 ON\n"
        f"- 수온 > {WATER_TEMP_CRITICAL_HIGH}℃ → 물가열기 OFF\n\n"
        "## 선행 조치 규칙\n"
        "- 온도/습도/CO2가 정상범위 경계에 접근 중이면, 비상 임계치 도달 전에 예방 조치를 취하세요.\n"
        "- 예: 온도 30.5℃ 상승 추세 → 외부순환으로 33℃ 도달 방지\n"
        "- 예: 습도 73% 하강 추세 → 분사펌프 가동으로 70% 미만 방지\n"
        "- 외부 온도/습도도 고려하여 외부순환 적합 여부를 판단하세요.\n\n"
        "## 응답 형식 (JSON 1개만 출력, 설명 없이 JSON만)\n"
        "필수 키 5개: action, reason, devices, circulation (최상위 키)\n"
        "devices에는 4개 장치만 포함, circulation은 devices 밖에 위치:\n"
        '{"action":"change","reason":"20자이내",'
        '"devices":{"water_heater_flag":true,"fog_occurs_flag":false,'
        '"indoor_heater_flag":false,"indoor_heater_valve_flag":false},'
        '"circulation":"내부순환"}\n'
        'action이 "keep"이면: {"action":"keep","reason":"사유"}\n'
    )

    return base + stage_guide + rules


# 유저 프롬프트
# ══════════════════
def _build_user_prompt(sensor_data, current_relay, growth_stage, optimal, trend_info, house_id):
    # 릴레이 ON 상태를 시멘틱 이름으로 (보호장치 제외)
    pin_map = get_pin_map(house_id)
    reverse = {v: k for k, v in pin_map.items()}
    on_list = []
    if current_relay:
        for pin_key, semantic_name in reverse.items():
            if semantic_name in PROTECTED_DEVICES:
                continue
            if current_relay.get(pin_key):
                on_list.append(SEMANTIC_LABELS.get(semantic_name, semantic_name))
    relay_str = f"ON=[{', '.join(on_list)}]" if on_list else "ON=[없음]"

    parts = [
        f"현재 센서값: "
        f"내부온도={sensor_data.get('indoor_temperature')}℃, "
        f"내부습도={sensor_data.get('indoor_humidity')}%, "
        f"CO2={sensor_data.get('co2')}ppm, "
        f"외부온도={sensor_data.get('outdoor_temperature')}℃, "
        f"외부습도={sensor_data.get('outdoor_humidity')}%, "
        f"수온={sensor_data.get('water_temperature')}℃",
        f"생육단계: {growth_stage}",
    ]

    if optimal:
        parts.append(
            f"최적조건: "
            f"온도={optimal.get('온도최저')}~{optimal.get('온도최고')}℃, "
            f"습도={optimal.get('습도최저')}~{optimal.get('습도최고')}%, "
            f"수온={WATER_TEMP_LOW}~{WATER_TEMP_HIGH}℃"
        )

    parts.append(f"현재 릴레이: {relay_str}")

    if trend_info:
        parts.append(trend_info)

    return "\n".join(parts)


# LLM 호출
# Ollama /api/generate 호출 → 응답 텍스트 반환
# ═══════════════════════════════════
def _call_llm(system_prompt, user_prompt):
    try:
        from agri_ai_core.src.ai.mcp_client import mcp_http_request

        ollama_url = get_ollama_url()
        model_name = get_model_name()

        prompt = system_prompt + "\n\n" + user_prompt

        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0,
                "num_predict": 200,
            },
        }

        t_start = time.time()

        status_code, data, error_text = mcp_http_request(
            method="POST",
            url=f"{ollama_url}/api/generate",
            json_body=payload,
            timeout=AI_CONTROL_TIMEOUT,
        )

        elapsed = time.time() - t_start

        if status_code != 200 or not data:
            logger.warning(f"[AI제어] LLM 호출 실패: status={status_code}, {elapsed:.1f}s")
            return None

        response_text = data.get("response", "") if isinstance(data, dict) else ""
        logger.info(f"[AI제어] LLM 응답 ({elapsed:.1f}s): {response_text[:150]}")
        return response_text

    except Exception as e:
        logger.warning(f"[AI제어] LLM 호출 예외: {e}")
        return None


# JSON 응답 파싱
# LLM JSON 응답 파싱
# ══════════════════
def _parse_relay_response(response_text):
    if not response_text:
        return None

    # 중첩 1단계 JSON 매칭 (devices:{...} 포함)
    match = re.search(r'\{(?:[^{}]|\{[^{}]*\})*\}', response_text, re.DOTALL)
    if not match:
        logger.warning(f"[AI제어] JSON 패턴 없음: {response_text[:100]}")
        return None

    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError as e:
        logger.warning(f"[AI제어] JSON 파싱 실패: {e}")
        return None

    action = parsed.get("action", "keep")
    reason = parsed.get("reason", "")

    if action == "keep":
        return {"action": "keep", "reason": reason}

    if action != "change":
        logger.warning(f"[AI제어] 알 수 없는 action: {action}")
        return None

    devices = parsed.get("devices")
    circulation = parsed.get("circulation")

    # LLM이 circulation을 devices 안에 넣은 경우 보정
    if isinstance(devices, dict) and not circulation:
        circulation = devices.pop("circulation", None)

    if not isinstance(devices, dict) or not circulation:
        logger.warning(f"[AI제어] devices 또는 circulation 누락: {json.dumps(parsed, ensure_ascii=False)[:150]}")
        return None

    if circulation not in VALID_CIRCULATIONS:
        logger.warning(f"[AI제어] 잘못된 순환모드: {circulation}")
        return None

    normalized_devices = {
        'water_heater_flag': bool(devices.get('water_heater_flag', False)),
        'fog_occurs_flag': bool(devices.get('fog_occurs_flag', False)),
        'indoor_heater_flag': bool(devices.get('indoor_heater_flag', False)),
        'indoor_heater_valve_flag': bool(devices.get('indoor_heater_valve_flag', False)),
    }

    return {
        "action": "change",
        "reason": reason,
        "devices": normalized_devices,
        "circulation": circulation,
    }


# 안전 검증
# LLM 응답 안전 검증 — 비상조건 위반·쿨다운 위반·외부순환 제한 거부
# ════════════════════════════════════════
def _validate_safety(parsed, sensor_data, farm_id, house_id):
    devices = parsed.get("devices", {})
    circulation = parsed.get("circulation", "")

    indoor_temp = sensor_data.get('indoor_temperature')
    indoor_humidity = sensor_data.get('indoor_humidity')
    co2 = sensor_data.get('co2')
    water_temp = sensor_data.get('water_temperature')
    outdoor_temp = sensor_data.get('outdoor_temperature')
    outdoor_humidity = sensor_data.get('outdoor_humidity')

    # (1) 비상 온도 위반 방지
    if indoor_temp is not None:
        if indoor_temp > TEMP_CRITICAL_HIGH:
            # 고온 비상 시 가열 장치 ON 거부
            if devices.get('indoor_heater_flag') or devices.get('water_heater_flag'):
                logger.warning(f"[AI제어] 안전 보정: 고온비상({indoor_temp}℃) → 가열장치 강제 OFF")
                devices['indoor_heater_flag'] = False
                devices['indoor_heater_valve_flag'] = False
                devices['water_heater_flag'] = False
            if circulation not in ('배기순환', '외부순환'):
                circulation = '배기순환'
                logger.warning(f"[AI제어] 안전 보정: 고온비상 → 배기순환 강제")

        elif indoor_temp < TEMP_CRITICAL_LOW:
            # 저온 비상 시 가열 OFF 거부
            if not devices.get('water_heater_flag') and not devices.get('indoor_heater_flag'):
                logger.warning(f"[AI제어] 안전 보정: 저온비상({indoor_temp}℃) → 물가열기+열풍기 강제 ON")
                devices['water_heater_flag'] = True
                devices['indoor_heater_flag'] = True
                devices['indoor_heater_valve_flag'] = True

    # (2) 비상 습도 위반 방지
    if indoor_humidity is not None:
        if indoor_humidity > HUMIDITY_CRITICAL_HIGH:
            if devices.get('fog_occurs_flag'):
                logger.warning(f"[AI제어] 안전 보정: 고습비상({indoor_humidity}%) → 분사펌프 강제 OFF")
                devices['fog_occurs_flag'] = False

        elif indoor_humidity < HUMIDITY_CRITICAL_LOW:
            if not devices.get('fog_occurs_flag'):
                logger.warning(f"[AI제어] 안전 보정: 저습비상({indoor_humidity}%) → 분사펌프 강제 ON")
                devices['fog_occurs_flag'] = True

    # (3) 수온 비상 위반 방지
    if water_temp is not None:
        if water_temp > WATER_TEMP_CRITICAL_HIGH and devices.get('water_heater_flag'):
            logger.warning(f"[AI제어] 안전 보정: 수온과열({water_temp}℃) → 물가열기 강제 OFF")
            devices['water_heater_flag'] = False
        elif water_temp < WATER_TEMP_CRITICAL_LOW and not devices.get('water_heater_flag'):
            logger.warning(f"[AI제어] 안전 보정: 수온저하({water_temp}℃) → 물가열기 강제 ON")
            devices['water_heater_flag'] = True

    # (4) 외부순환 제한 검증
    if circulation == '외부순환':
        ext_temp_bad = outdoor_temp is not None and (outdoor_temp < TEMP_LOW or outdoor_temp > TEMP_HIGH)
        ext_hum_bad = outdoor_humidity is not None and (outdoor_humidity < HUMIDITY_LOW or outdoor_humidity > HUMIDITY_HIGH)
        if ext_temp_bad or ext_hum_bad:
            logger.warning(f"[AI제어] 안전 보정: 외부환경 부적합(외부온도={outdoor_temp}, 외부습도={outdoor_humidity}) → 내부순환 전환")
            circulation = '내부순환'

    # (5) 열풍기 쿨다운 검증
    if devices.get('indoor_heater_flag', False):
        heater_available, in_cooldown = check_heater_cooldown(farm_id, house_id)
        if not heater_available:
            logger.warning(f"[AI제어] 안전 보정: 열풍기 쿨다운 중 → 열풍기 OFF")
            devices['indoor_heater_flag'] = False
            devices['indoor_heater_valve_flag'] = False

    # (6) 열풍기-열풍댐퍼 연동 보정
    if devices.get('indoor_heater_flag', False) and not devices.get('indoor_heater_valve_flag', False):
        devices['indoor_heater_valve_flag'] = True
        logger.info(f"[AI제어] 안전 보정: 열풍기ON → 열풍댐퍼 강제 ON")

    # (7) 순환모드 유효성
    if circulation not in VALID_CIRCULATIONS:
        logger.warning(f"[AI제어] 안전 거부: 잘못된 순환모드 {circulation}")
        return None

    return {
        "action": "change",
        "reason": parsed.get("reason", ""),
        "devices": devices,
        "circulation": circulation,
    }


# 메인 AI 제어 함수
# AI 릴레이 제어 메인 함수
# ══════════════════
def control_ai_environment(farm_id, house_id, growth_stage='생육기', order_label=""):
    try:
        scope = house_prefix(order_label, farm_id, house_id)

        # 1. 센서/릴레이 조회
        sensor_data = read_current_sensor_info(farm_id, house_id)
        if not sensor_data:
            logger.info(f"{scope}: [AI] 센서 데이터 없음")
            return {"success": False, "message": "센서 데이터 없음"}

        current_relay = read_latest_relay_info(farm_id, house_id)

        # 센서 + 릴레이 현황 로그 (매 호출마다 출력)
        _log_ai_status(scope, sensor_data, current_relay, house_id)

        # 2. 센서 이력 업데이트 (트렌드 분석)
        _trend_detected, trend_info = _detect_trend(farm_id, house_id, sensor_data)
        if trend_info:
            logger.info(f"{scope}: [AI] {trend_info}")

        # 3. 최적 조건 조회
        optimal = read_optimal_condition(farm_id, house_id) or {}

        # 5. LLM 호출
        logger.info(f"{scope}: [AI] LLM 호출 시작 (생육단계: {growth_stage})")
        system_prompt = _build_system_prompt(growth_stage)
        user_prompt = _build_user_prompt(
            sensor_data, current_relay, growth_stage, optimal, trend_info, house_id
        )
        logger.info(f"{scope}: [AI] === 시스템 프롬프트 ===\n{system_prompt}")
        logger.info(f"{scope}: [AI] === 유저 프롬프트 ===\n{user_prompt}")
        llm_result = _call_llm(system_prompt, user_prompt)

        if not llm_result:
            _log_ai_decision(scope, "keep", "LLM 호출 실패")

            return {"success": True, "message": "AI 제어: LLM 실패 → 현상 유지", "action": "keep"}

        # 6. 파싱
        parsed = _parse_relay_response(llm_result)
        if not parsed:
            _log_ai_decision(scope, "keep", "응답 파싱 실패")

            return {"success": True, "message": "AI 제어: 파싱 실패 → 현상 유지", "action": "keep"}

        # 7. action=keep
        if parsed.get("action") == "keep":
            reason = parsed.get('reason', '')
            _log_ai_decision(scope, "keep", reason)

            return {"success": True, "message": f"AI 제어: 현상 유지 ({reason})", "action": "keep"}

        # 8. 안전 검증
        validated = _validate_safety(parsed, sensor_data, farm_id, house_id)
        if not validated:
            _log_ai_decision(scope, "keep", "안전 검증 실패")

            return {"success": True, "message": "AI 제어: 안전 검증 실패", "action": "keep"}

        # 9. AI 판단 결과 상세 로그
        _log_ai_decision(
            scope, "change", validated.get('reason', ''),
            devices=validated['devices'], circulation=validated['circulation']
        )

        # 10. 2-phase 릴레이 실행
        harvest_mode = (growth_stage == '수확기')
        result = _execute_control(
            farm_id, house_id,
            validated['devices'],
            validated['circulation'],
            current_relay,
            harvest_mode,
            reason=f"AI제어({validated.get('reason', '')})",
            order_label=order_label,
        )

        logger.info(f"{scope}: [AI] 제어 실행 완료")

        return result

    except Exception as e:
        scope = house_prefix(order_label, farm_id, house_id)
        logger.error(f"AI 환경제어 오류 ({scope}): {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "message": f"AI 제어 오류: {str(e)}"}
