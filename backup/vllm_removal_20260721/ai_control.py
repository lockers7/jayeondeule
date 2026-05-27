# ════════════════════════════════════════════════════════════════════
# AI 릴레이 제어 모듈.
# LLM이 센서값·릴레이·생육단계·최적조건을 종합 분석하여 릴레이를 결정.
# 센서 트렌드 분석으로 임계치 도달 전 선행(예방) 제어를 수행한다.
# --->
# _to_float: to float
# _log_ai_status: log ai status
# _log_ai_decision: log ai decision
# _detect_trend: detect trend
# _check_threshold_proximity: check threshold proximity
# monitor_ai_emergency: monitor ai emergency
# _build_system_prompt: build system prompt
# _build_user_prompt: build user prompt
# _call_llm: call llm
# _parse_relay_response: parse relay response
# _validate_safety: validate safety
# control_ai_environment: control ai environment
# ════════════════════════════════════════════════════════════════════
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
from agri_ai_core.src.ai.llm_runtime_guard import (
    LlmCallLockTimeout,
    llm_activity,
    llm_call_lock,
)
from agri_ai_core.src.utils.json_utils import safe_json_load
from agri_ai_core.src.utils.http_client import http_json_request
from agri_ai_core.src.utils.error_utils import log_and_return
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
)
# 임계값은 ai_thresholds.get_thresholds() 또는 인자 ts 사용
from agri_ai_core.src.control.manual_control import _execute_control
from agri_ai_core.src.control.environment_logic import apply_water_safety
from agri_ai_core.src.control.relay_manager import set_relay_value
# AI 환경제어 컨텍스트 확장 — 모든 모듈은 단방향 의존이며
# 모든 호출은 try/except 보호되어 실패 시 빈 문자열 반환 → 기존 LLM 흐름 보존.
from agri_ai_core.src.control.ai_history_context import format_history_block
from agri_ai_core.src.control.ai_rag_context import (
    query_similar_periods, format_rag_block,
)
from agri_ai_core.src.control.ai_step_logger import AiStepLogger
from agri_ai_core.src.control.ai_decision_log import (
    record_decision as _record_ai_decision,
    get_recent as _get_recent_ai_decisions,
    format_recent_block as _format_recent_decisions_block,
)
from agri_ai_core.src.control.ai_peer_compare import (
    get_peer_snapshot, format_peer_block,
)
from agri_ai_core.src.control.ai_harvest_context import (
    get_harvest_context, format_harvest_block,
)
from agri_ai_core.src.control.ai_anomaly_history import (
    get_anomaly_patterns, format_anomaly_block,
)
from agri_ai_core.src.control.ai_weather_forecast import (
    get_forecast as _get_weather_forecast,
    format_forecast_block as _format_weather_block,
)
from agri_ai_core.src.control.ai_air_quality import (
    get_air_quality as _get_air_quality,
    format_air_quality_block as _format_air_quality_block,
)
from agri_ai_core.src.control.ai_weather_alert import (
    get_weather_alerts as _get_weather_alerts,
    format_weather_alert_block as _format_weather_alert_block,
)
from agri_ai_core.src.control.ai_atm_stagnation import (
    get_atm_stagnation as _get_atm_stagnation,
    format_atm_stagnation_block as _format_atm_stagnation_block,
)
# 즉석 Vision LLM 호출 없음 — ai_camera_archive 가 매시간 정각에
# 캡처+Vision+RAG 처리하므로 read_recent_history(DB) 만 사용.
# 환경제어 사이클에서 60초 vision LLM 큐 점유 회피 (채팅 응답 지연 방지).
from agri_ai_core.src.control.ai_camera_archive import (
    read_recent_history, format_image_history_block,
)
from agri_ai_core.src.control.ai_doc_rag import (
    query_domain_knowledge, format_doc_block,
)
from agri_ai_core.src.control.ai_yield_correlation import (
    get_high_quality_periods, format_yield_block,
)
from agri_ai_core.src.control.ai_forecast import (
    get_forecast as _get_ts_forecast,
    format_forecast_block as _format_ts_forecast_block,
)
from agri_ai_core.src.control.ai_seasonality import (
    get_monthly_seasonality, format_seasonality_block,
)
from agri_ai_core.src.control.ai_power_usage import (
    get_power_usage_24h, format_power_block,
)
# 최근 raw 시계열 (3분 간격 20건) — LLM 에 직접 노출
from agri_ai_core.src.control.ai_recent_timeseries import (
    get_recent_samples as _get_recent_samples,
    format_recent_block as _format_recent_ts_block,
)
# 모듈 레벨 import — _validate_safety 가드 테스트 monkeypatch 지원
from agri_ai_core.src.control.ai_thresholds import get_thresholds

logger = setup_logger(__name__)

# ══════════════════
# 설정 (환경제어 LLM 전용 — 사용자 대화 LLM 과 분리)
# "정확한 판단 우선, 시간 무관" 정책 — 토큰·컨텍스트 확장
# ══════════════════
AI_CONTROL_TIMEOUT     = int(os.getenv("AI_CONTROL_TIMEOUT",     "600"))   # Ollama 큐 대기 후에도 응답 수신 가능 — 제어 결정 지연 허용 정책.
AI_PROXIMITY_RATIO     = float(os.getenv("AI_PROXIMITY_RATIO",   "0.8"))
AI_CONTROL_NUM_PREDICT = int(os.getenv("AI_CONTROL_NUM_PREDICT", "400"))   # 실응답 <200토큰 · GPU 점유시간 단축
AI_CONTROL_NUM_CTX     = int(os.getenv("AI_CONTROL_NUM_CTX",     "16384")) # 모델 기본 4096 → 16k (raw 시계열 + 다중 컨텍스트 수용)
AI_CONTROL_LLM_LOCK_WAIT = int(os.getenv("AI_CONTROL_LLM_LOCK_WAIT", str(AI_CONTROL_TIMEOUT)))

VALID_CIRCULATIONS = set(CIRCULATION_MODES.keys())


def _control_llm_retry_backoffs():
    raw = os.getenv("AI_CONTROL_LLM_RETRY_BACKOFFS", "1.5,5,15")
    backoffs = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = float(part)
        except ValueError:
            continue
        if value > 0:
            backoffs.append(min(value, 120.0))
    return backoffs


def _is_transient_control_llm_failure(status_code, error_text):
    text = (error_text or "").lower()
    return (
        status_code in {408, 429, 500, 502, 503, 504}
        or "timeout" in text
        or "timed out" in text
        or "connection refused" in text
        or "server disconnected" in text
        or "connection reset" in text
        or "maximum pending requests" in text
        or "server busy" in text
    )

# PROTECTED_DEVICES 를 RELAY_FIELD_MAPPING.flags 에서 자동 도출.
# RelayDef 의 flags 에 'PROTECTED' 가 설정된 sem 만 자동 포함 — 신규 PROTECTED 릴레이
# 추가 시 mappers.py 의 _PROTECTED_SEMS 만 갱신하면 본 set 자동 반영.
from agri_ai_core.config.mappers import (
    protected_semantic_keys as _protected_semantic_keys,
    device_mapping_text as _device_mapping_text,
    circulation_modes_text as _circulation_modes_text,
)
PROTECTED_DEVICES = _protected_semantic_keys()

# ══════════════════════════════════════════════════════════════════════════════
# Ollama format=<schema> 강제용 JSON Schema
# Ollama 0.5+ 는 이 스키마에 맞는 JSON 만 출력하도록 강제. 모델이 다른 키 못 만듦.
# ══════════════════════════════════════════════════════════════════════════════
RELAY_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["change", "keep"]},
        "reason": {"type": "string"},
        # LLM 결정 도메인 — mappers.py 룰 자율 적용.
        # drainage_motor_flag 포함 (수온히터·배수밸브 상호배타 LLM 직접 판단).
        # 향후 더 많은 릴레이를 LLM 에 위임할 수 있으나 우선 가장 영향 큰 1개부터.
        "devices": {
            "type": "object",
            "properties": {
                "water_heater_flag":  {"type": "boolean"},
                "fog_occurs_flag":    {"type": "boolean"},
                "drainage_motor_flag": {"type": "boolean"},
            },
            "required": ["water_heater_flag", "fog_occurs_flag", "drainage_motor_flag"],
        },
        "circulation": {
            "type": "string",
            "enum": list(VALID_CIRCULATIONS) if VALID_CIRCULATIONS else
                    ["내부순환", "외부순환", "흡입순환", "배기순환", "순환정지"],
        },
    },
    "required": ["action", "reason"],
}


# ══════════════════
# 인메모리 상태 추적
# ══════════════════
_sensor_history = {}


# ────────────────────────────────────────────────────────────────────
# 임의 값 → float 안전 변환. 실패 시 None.
# ────────────────────────────────────────────────────────────────────
def _to_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


# ══════════════════════════════════════
# 상세 로깅 함수 (공통 포맷팅 함수 활용)
# 센서 현황 + 릴레이 상태 로그 (AI 태그)
# ══════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 센서 현황 + 릴레이 상태 INFO 로그 (AI 태그) — 공통 포맷팅 함수 활용.
# ────────────────────────────────────────────────────────────────────
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


# ══════════════════════
# AI 판단 결과 상세 로그
# ══════════════════════
# ────────────────────────────────────────────────────────────────────
# AI 판단 결과 상세 로그 — keep/change 분기 INFO 출력.
# ────────────────────────────────────────────────────────────────────
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


# ═══════════════════════════════════════════════════
# 트렌드 분석 (선행 조치 핵심)
# 최근 30회 센서값으로 기울기 분석 → 임계치 도달 예측
# ═══════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 트렌드 분석 (선행 조치 핵심) — 최근 30회 deque 로 분당 변화율 계산.
# 5분 후 비상 임계 도달 예측 시 trend_detected=True. 추세 정보 텍스트 동반.
# ────────────────────────────────────────────────────────────────────
def _detect_trend(farm_id, house_id, sensor_data):
    # 임계값 동적 — DB 셋팅
    from agri_ai_core.src.control.ai_thresholds import get_thresholds
    ts = get_thresholds(farm_id, house_id)

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
        ('temp', '온도', '℃', ts.temp_critical_low, ts.temp_critical_high),
        ('humidity', '습도', '%', ts.humidity_critical_low, ts.humidity_critical_high),
        ('co2', 'CO2', 'ppm', None, ts.co2_critical_high),
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


# ═══════════════════════════════════════════════════
# 임계치 근접 판단
# 정상범위 이탈 후 비상 임계치까지 80% 이상 근접 여부
# ═══════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 임계치 근접 판단 — 정상범위 이탈 후 비상 임계까지 80%(AI_PROXIMITY_RATIO)
# 이상 근접 시 True.
# ────────────────────────────────────────────────────────────────────
def _check_threshold_proximity(sensor_data, farm_id=None, house_id=None):
    # 임계값 동적 — DB 셋팅
    from agri_ai_core.src.control.ai_thresholds import get_thresholds, get_global_default
    ts = get_thresholds(farm_id, house_id) if farm_id is not None else get_global_default()
    checks = [
        ('indoor_temperature', ts.temp_low, ts.temp_high, ts.temp_critical_low, ts.temp_critical_high),
        ('indoor_humidity', ts.humidity_low, ts.humidity_high, ts.humidity_critical_low, ts.humidity_critical_high),
        ('co2', ts.co2_low, ts.co2_high, None, ts.co2_critical_high),
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


# ════════════════════════════════════════════════════════════
# 10초 주기 AI 센서 모니터링 (긴급 개입 판단)
# 임계치 근접 OR 트렌드 급변 감지 시 True → 즉시 LLM 호출 필요
# ════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 10초 주기 AI 센서 모니터링 — 임계치 근접 OR 트렌드 급변 감지 시 True.
# True 면 즉시 LLM 호출 필요 (긴급 개입).
# ────────────────────────────────────────────────────────────────────
def monitor_ai_emergency(farm_id, house_id, order_label=""):
    scope = house_prefix(order_label, farm_id, house_id)

    sensor_data = read_current_sensor_info(farm_id, house_id)
    if not sensor_data:
        return False

    # 센서 이력 업데이트 + 트렌드 분석
    trend_detected, trend_info = _detect_trend(farm_id, house_id, sensor_data)

    # 임계치 근접 감지
    proximity_detected = _check_threshold_proximity(sensor_data, farm_id, house_id)

    if proximity_detected:
        # 5초 모니터는 결정/제어 적용 안 함. 60초 _ai_control_loop 가
        #   다음 cycle 에서 LLM 결정 + emergency_override 통합 적용. 본 로그는 가시성용.
        logger.info(f"{scope}: [AI모니터링] 임계치 근접 감지 (다음 LLM cycle 에서 처리)")
        return True

    if trend_detected:
        logger.info(f"{scope}: [AI모니터링] 트렌드 급변 감지 (다음 LLM cycle 에서 처리)")
        return True

    return False


# ══════════════════
# 시스템 프롬프트
# ts(ThresholdSet) 인자로 재배사별 동적 임계값 주입.
# None 이면 control_common 폴백 (기본값).
# ══════════════════
# ────────────────────────────────────────────────────────────────────
# 시스템 프롬프트 빌더 — ts(ThresholdSet) 인자로 재배사별 동적 임계값 주입.
# ts None 이면 control_common 폴백 (기본값).
# ────────────────────────────────────────────────────────────────────
def _build_system_prompt(growth_stage, ts=None):
    # 재배사별 동적 임계값(ts)을 control_prompt_m 뼈대 블록의 ${...} 에 치환해 합성.
    # ts None 이면 폴백(get_global_default) — control_common 임계 직접 import 금지.
    if ts is None:
        from agri_ai_core.src.control.ai_thresholds import get_global_default
        ts = get_global_default()
    from agri_ai_core.src.prompt_registry import get_control_block as _gcb
    ts_kw = dict(
        TEMP_LOW=ts.temp_low, TEMP_HIGH=ts.temp_high,
        TEMP_CRITICAL_LOW=ts.temp_critical_low, TEMP_CRITICAL_HIGH=ts.temp_critical_high,
        HUMIDITY_LOW=ts.humidity_low, HUMIDITY_HIGH=ts.humidity_high,
        HUMIDITY_CRITICAL_LOW=ts.humidity_critical_low, HUMIDITY_CRITICAL_HIGH=ts.humidity_critical_high,
        CO2_LOW=ts.co2_low, CO2_HIGH=ts.co2_high, CO2_CRITICAL_HIGH=ts.co2_critical_high,
        WATER_TEMP_LOW=ts.water_temp_low, WATER_TEMP_HIGH=ts.water_temp_high,
        WATER_TEMP_CRITICAL_LOW=ts.water_temp_critical_low, WATER_TEMP_CRITICAL_HIGH=ts.water_temp_critical_high,
        BUDDING_TEMP_LOW=ts.budding_temp_low, BUDDING_TEMP_HIGH=ts.budding_temp_high,
        GROWTH_STAGE=growth_stage,
        DEVICE_MAPPING=_device_mapping_text(),
        CIRCULATION_MODES=_circulation_modes_text(),
        PROTECTED_DEVICES=', '.join(sorted(PROTECTED_DEVICES)),
    )
    # 뼈대(2026-07-19 단순화): 결정트리 §2~§5·§7·§8 → CTRL_GUIDE 1블록으로 대체.
    # 생육단계 분기는 CTRL_GUIDE 의 ${GROWTH_STAGE} 치환으로 처리.
    block_ids = ['CTRL_ROLE', 'CTRL_SEC1', 'CTRL_SEC_SEASON', 'CTRL_GUIDE',
                 'CTRL_SEC6', 'CTRL_SEC9']
    sections = []
    for bid in block_ids:
        block = _gcb(bid, **ts_kw)
        if block:
            sections.append(block)
        else:
            logger.warning(f"[SystemPrompt] block '{bid}' DB 조회 실패 — 섹션 건너뜀")
    return "\n".join(sections)


# ══════════════════
# 유저 프롬프트
# history_block / rag_block 인자가 default 값으로 추가됨 — 기존 호출자
# (시그니처 5번째까지만 위치인자) 와 호환 유지. 빈 문자열이면 섹션 자체 생략.
# ══════════════════
# ────────────────────────────────────────────────────────────────────
# 유저 프롬프트 빌더 — 센서·릴레이·생육·최적조건·트렌드+추가 블록 합성.
# history_block / rag_block / extra_blocks 인자 추가 — 빈 문자열
# 이면 섹션 자체 생략. 기존 호출자(5번째 위치인자) 와 호환 유지.
# ────────────────────────────────────────────────────────────────────
def _build_user_prompt(sensor_data, current_relay, growth_stage, optimal, trend_info, house_id,
                       history_block: str = "", rag_block: str = "",
                       extra_blocks=None, farm_id=None):
    from agri_ai_core.src.prompt_registry import get_control_block as _gcb
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

    def _relay_semantic_on(semantic_name: str) -> bool:
        """현재 relay row의 pin 컬럼을 semantic 장치명으로 변환한다."""
        pin_key = pin_map.get(semantic_name)
        if pin_key and pin_key in current_relay:
            return bool(current_relay.get(pin_key))
        return bool(current_relay.get(semantic_name))

    # 결함필터(reader.py)가 None 처리한 센서를 "None℃" 대신
    # "측정불가(센서장애)" 로 명시 — LLM 이 'None' 을 임의 해석하지 않도록
    # 장애 사실과 판단 근거를 함께 제공한다(정보 축소가 아닌 명확화).
    def _sv(key, unit):
        _v = sensor_data.get(key)
        return f"{_v}{unit}" if _v is not None else "측정불가(센서장애)"
    _wt = sensor_data.get('water_temperature')
    parts = [
        f"현재 센서값: "
        f"내부온도={_sv('indoor_temperature', '℃')}, "
        f"내부습도={_sv('indoor_humidity', '%')}, "
        f"CO2={_sv('co2', 'ppm')}, "
        f"외부온도={_sv('outdoor_temperature', '℃')}, "
        f"외부습도={_sv('outdoor_humidity', '%')}, "
        f"수온={_sv('water_temperature', '℃')}",
        f"생육단계: {growth_stage}",
    ]
    if _wt is None:
        parts.append(
            "※ 수온 센서 장애로 현재 수온을 알 수 없음 — 수온히터/포그 등 수온 관련 "
            "룰은 실내온도(적정범위 대비)와 외기온도를 근거로 판단하라."
        )
    _faulty = [lbl for k, lbl in (('indoor_temperature', '실내온도'),
                                  ('outdoor_temperature', '외부온도'),
                                  ('indoor_humidity', '실내습도'),
                                  ('outdoor_humidity', '외부습도'),
                                  ('co2', 'CO2'))
               if sensor_data.get(k) is None]
    if _faulty:
        parts.append(
            f"※ {', '.join(_faulty)} 센서 장애(순간 결함) — 해당 값에 근거한 판단은 "
            "보류하고 나머지 정상 센서와 직전 결정 이력을 근거로 보수적으로 판단하라."
        )

    # 관리자 강제 지시 — 활성 지시가 있으면 LLM 판단보다 최우선.
    # (relay_manager 최종 관문에서도 하드 강제되지만, LLM 이 지시를 인지하고
    #  일관된 결정·사유를 내도록 프롬프트에도 주입 — LLM 100% 원칙과의 조화)
    # ⛔ farm_id 는 0(시스템농장)이 유효값 — `if farm_id:` 로 검사하면 0 이 탈락한다.
    if farm_id is not None:
        try:
            from agri_ai_core.src.control.admin_directive import format_prompt_block
            _adm_block = format_prompt_block(farm_id, house_id)
            if _adm_block:
                parts.append(_adm_block)
        except Exception as e:
            # ⛔ 조용한 pass 금지. 2026-07-17 까지 farm_id 미전달로 NameError 가
            #    매 사이클 삼켜져, 관리자지시가 프롬프트에 한 번도 주입되지 않았다.
            logger.warning(f"[관리자지시] 프롬프트 블록 주입 실패 — {e}")

    if optimal:
        # None~None 노출 방지 — 6개 키 모두 값이 있을 때만 출력
        _opt_keys = ('온도최저', '온도최고', '습도최저', '습도최고', '수온최저', '수온최고')
        if all(optimal.get(k) is not None for k in _opt_keys):
            parts.append(
                f"최적조건: "
                f"온도={optimal.get('온도최저')}~{optimal.get('온도최고')}℃, "
                f"습도={optimal.get('습도최저')}~{optimal.get('습도최고')}%, "
                f"수온={optimal.get('수온최저')}~{optimal.get('수온최고')}℃"
            )

    # ⛔ 센서 평가(임계 비교) 블록 제거 — 2026-07-17 농장주 지시 (LLM 100% 자율).
    #   python 이 임계 비교 판정을 대신 내려 LLM 에 먹이던 57줄을 걷어냈다.
    #   LLM 은 위의 "현재 센서값" 과 "최적조건" 만으로 직접 비교·판단한다.
    #   ⛔ 되돌리지 말 것 — 복구 필요 시 농장주 지시로만.

    # 상호배타 룰 현재 상태 평가 — 실손 비용 명시.
    #   LLM 이 "현재 무엇이 ON/OFF" 만 보고 룰 관계는 추론으로만 함 → 명시적 표시 필요.
    #   위반 검출 시 "왜 위반인지" 비용·고장 인과를 함께 제공해 LLM 이 가벼운 룰로 오인 방지.
    if current_relay:
        heater_on = _relay_semantic_on('water_heater_flag')
        drain_on = _relay_semantic_on('drainage_motor_flag')
        fog_on = _relay_semantic_on('fog_occurs_flag')
        rule_lines = []
        rule_lines.append(
            _gcb('CTRL_USER_MSG_RELAY_STATUS',
                 HEATER_STATUS='ON' if heater_on else 'OFF',
                 HEATER_PIN=pin_map.get('water_heater_flag') or 'n/a',
                 FOG_STATUS='ON' if fog_on else 'OFF',
                 FOG_PIN=pin_map.get('fog_occurs_flag') or 'n/a',
                 DRAIN_STATUS='ON' if drain_on else 'OFF',
                 DRAIN_PIN=pin_map.get('drainage_motor_flag') or 'n/a')
            or f"- 릴레이: heater={'ON' if heater_on else 'OFF'} fog={'ON' if fog_on else 'OFF'} drain={'ON' if drain_on else 'OFF'}"
        )
        if heater_on and drain_on:
            rule_lines.append(_gcb('CTRL_USER_MSG_RULE1_BOTH_ON') or "- 🔴 절대 룰 1 위반: 둘 다 ON")
        elif heater_on and not drain_on:
            rule_lines.append(_gcb('CTRL_USER_MSG_RULE1_HEATER') or "- ✅ 룰 1 준수 (heater ON)")
        elif (not heater_on) and drain_on:
            rule_lines.append(_gcb('CTRL_USER_MSG_RULE1_DRAIN') or "- ✅ 룰 1 준수 (drain ON)")
        else:
            rule_lines.append(_gcb('CTRL_USER_MSG_RULE1_BOTH_OFF') or "- ⚠️ 룰 1 위반: 둘 다 OFF")
        wt2 = sensor_data.get('water_temperature')
        if wt2 is not None and wt2 >= 30.0 and heater_on:
            rule_lines.append(
                _gcb('CTRL_USER_MSG_RULE2_VIOLATION', WATER_TEMP=wt2)
                or f"- 🔴 절대 룰 2 위반: 수온 {wt2}℃ 과열"
            )
        parts.append(_gcb('CTRL_USER_LABEL_RULE_STATE') or "[절대 룰 현재 상태]")
        parts.extend(rule_lines)

    parts.append(f"현재 릴레이: {relay_str}")

    if trend_info:
        parts.append(trend_info)

    if history_block:
        parts.append(history_block)
    if rag_block:
        parts.append(rag_block)

    # 추가 신규 블록 — 비어있는 블록은 자동 제외
    for block in (extra_blocks or []):
        if block:
            parts.append(block)

    return "\n".join(parts)


# ════════════════════════════════════════════
# LLM 호출
# Ollama /api/generate 호출 → 응답 텍스트 반환
# ════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# Ollama /api/generate LLM 호출 → 응답 텍스트 반환.
# (D) JSON Schema 강제 + 확장된 토큰/컨텍스트.
# 환경제어 LLM 전용 — 사용자 대화 LLM (query_handler_simple) 과 분리.
# 1차: format=<schema> 강제 (Ollama 0.5+).
# 2차: format="json" 폴백 (구버전 호환).
# 3차: format 없이 (가장 호환성 높지만 응답 형식 무보장).
# ────────────────────────────────────────────────────────────────────
@log_and_return(default=None, logger=logger, message="[AI제어] LLM 호출 예외")
def _call_llm(system_prompt, user_prompt):
    ollama_url = get_ollama_url()
    model_name = get_model_name()
    prompt = system_prompt + "\n\n" + user_prompt

    # LLM_BACKEND=vllm 일 때 vLLM 으로 위임 — default ollama 유지.
    try:
        from agri_ai_core.src.ai import llm_backend_vllm as _vllm
        if _vllm.is_enabled():
            t0 = time.time()
            try:
                resp = _vllm.vllm_generate(
                    model=model_name, prompt=prompt,
                    options={"temperature": 0,
                             "num_predict": AI_CONTROL_NUM_PREDICT,
                             "num_ctx": AI_CONTROL_NUM_CTX},
                    format=RELAY_RESPONSE_SCHEMA,
                )
                response_text = resp.get("response", "") or ""
                elapsed = time.time() - t0
                logger.info(f"[AI제어] LLM 응답 backend=vllm ({elapsed:.1f}s, format=schema): {response_text[:200]}")
                return response_text
            except Exception as e:
                logger.error(f"[AI제어] vLLM 호출 실패 — ollama 폴백: {e}")
    except Exception:
        pass

    base_payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "keep_alive": -1,  # GPU 영구 상주 보장 (정수 -1 = infinite)
        "options": {
            "temperature": 0,
            "num_predict": AI_CONTROL_NUM_PREDICT,   # 400 (실응답 <200토큰)
            "num_ctx":     AI_CONTROL_NUM_CTX,       # 16384
        },
    }

    # 폴백 3단계 → schema 단일 — Ollama 0.5+ 가 schema 완벽 지원하며
    #   실 운영 로그상 폴백 시도들도 동일 사유(Ollama 큐 행/timeout)로 모두 실패함이
    #   확인됨. 단일 시도로 실패 시 즉시 algorithm_fallback 으로 넘겨 Ollama 큐 압박 ↓.
    attempts = [
        ("schema", {**base_payload, "format": RELAY_RESPONSE_SCHEMA}),
    ]

    logger.info(
        f"[AI제어] LLM 요청 model={model_name} num_predict={AI_CONTROL_NUM_PREDICT} "
        f"num_ctx={AI_CONTROL_NUM_CTX} timeout={AI_CONTROL_TIMEOUT}s prompt_len={len(prompt)}"
    )

    # transient 실패(503/busy, timeout, Ollama 재시작 중 connection refused 등)는
    # 즉시 fallback 으로 소모하지 않고 짧은 backoff 후 재시도한다.
    # 프롬프트/컨텍스트 크기는 변경하지 않는다.
    for stage, payload in attempts:
        backoffs = [0.0] + _control_llm_retry_backoffs()
        for retry_idx, backoff in enumerate(backoffs):
            if backoff > 0:
                logger.warning(
                    f"[AI제어] LLM {stage} transient 재시도 "
                    f"{retry_idx}/{len(backoffs) - 1} → {backoff:.1f}s 대기"
                )
                time.sleep(backoff)

            t_start = time.time()
            try:
                with llm_call_lock("ai_control", wait_sec=AI_CONTROL_LLM_LOCK_WAIT):
                    with llm_activity("ai_control", AI_CONTROL_TIMEOUT):
                        status_code, data, error_text = http_json_request(
                            method="POST",
                            url=f"{ollama_url}/api/generate",
                            json_body=payload,
                            timeout=AI_CONTROL_TIMEOUT,
                        )
            except LlmCallLockTimeout as e:
                logger.warning(f"[AI제어] LLM {stage} 호출 슬롯 대기 초과: {e}")
                break
            except Exception as e:
                # 전송 예외([Errno 22] 등 소켓/슬롯 핸드오프 일시오류)는
                #   즉시 fallback 하지 않고 backoff 재시도한다. 격리 호출은 정상 성공하므로
                #   대부분 다음 시도에서 성공하며, 재시도 동안 marker 점유가 길어져 agent
                #   양보(is_llm_busy)도 함께 유도된다. 마지막 시도까지 실패해야 fallback.
                logger.warning(f"[AI제어] LLM {stage} 호출 예외: {e}")
                if retry_idx < len(backoffs) - 1:
                    continue
                break

            elapsed = time.time() - t_start

            if status_code == 200 and data:
                response_text = data.get("response", "") if isinstance(data, dict) else ""
                tag = "재시도성공" if retry_idx > 0 else f"format={stage}"
                logger.info(
                    f"[AI제어] LLM 응답 ({elapsed:.1f}s, {tag}): {response_text[:200]}"
                )
                return response_text

            err_preview = (error_text or "")[:160]
            transient = _is_transient_control_llm_failure(status_code, error_text)
            if transient and retry_idx < len(backoffs) - 1:
                logger.warning(
                    f"[AI제어] LLM {stage} transient 실패 status={status_code} "
                    f"({elapsed:.1f}s) err={err_preview}"
                )
                continue

            logger.warning(
                f"[AI제어] LLM {stage} 실패 status={status_code} ({elapsed:.1f}s) "
                f"transient={transient} err={err_preview}"
            )
            break

    logger.error("[AI제어] LLM 호출 실패 → algorithm fallback 위임")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# (A) LLM 응답 정규화 — 다형 응답을 표준 스키마로 변환
# 실측에서 관찰된 다양한 응답 형식을 모두 표준 {action, devices, circulation, reason}
# 로 매핑. format=schema 강제(D) 가 우회되거나 일부 호환성 문제 시 폴백.
# ══════════════════════════════════════════════════════════════════════════════
_ACTION_ALIASES = {
    'change_relay': 'change', 'adjust': 'change', 'update': 'change',
    'set': 'change', 'apply': 'change', 'modify': 'change',
    'no_change': 'keep', 'maintain': 'keep', 'hold': 'keep',
}

# devices 컨테이너로 사용된 다양한 키 이름
_DEVICES_CONTAINER_ALIASES = ('devices', 'changes', 'adjustments', 'updates', 'relays', 'settings')

# 한국어 / 별칭 → 표준 영어 키
_DEVICE_KEY_MAP = {
    '수온히터': 'water_heater_flag',
    'water_heater': 'water_heater_flag',
    'heater': 'water_heater_flag',
    '포그생성': 'fog_occurs_flag',
    'fog_occurs': 'fog_occurs_flag',
    'fog': 'fog_occurs_flag',
    'mist': 'fog_occurs_flag',
    '흡입팬': 'intake_fan_flag',
    'intake_fan': 'intake_fan_flag',
    '배출팬': 'exhaust_fan_flag',
    'exhaust_fan': 'exhaust_fan_flag',
    '순환밸브': 'air_circulation_valve_flag',
    '흡입밸브': 'air_intake_valve_flag',
    '배출밸브': 'air_exhaust_valve_flag',
}

_CIRCULATION_KEY_ALIASES = ('circulation', 'circulation_mode', '순환', '순환모드', 'mode')
_REASON_KEY_ALIASES      = ('reason', 'reasoning', 'rationale', '사유', '이유', 'explanation')


# ────────────────────────────────────────────────────────────────────
# 다양한 boolean 표현(ON/TRUE/켜짐/1 등) → True/False. 모르면 None.
# ────────────────────────────────────────────────────────────────────
def _coerce_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        s = v.strip().upper()
        if s in ('ON', 'TRUE', 'YES', 'Y', '1', 'ENABLE', 'ENABLED', '켜짐', '가동'):
            return True
        if s in ('OFF', 'FALSE', 'NO', 'N', '0', 'DISABLE', 'DISABLED', '꺼짐', '정지'):
            return False
    return None


# ────────────────────────────────────────────────────────────────────
# 다양한 LLM 응답 형식을 표준 스키마로 정규화 → dict 또는 None.
# action/devices/circulation/reason 별칭, 한국어 키, target+state 등 모두 흡수.
# ────────────────────────────────────────────────────────────────────
def _normalize_llm_response(parsed):
    if not isinstance(parsed, dict):
        return None
    p = dict(parsed)  # shallow copy — 원본 보존

    # 1. action 정규화
    action = p.get('action') or p.get('command') or p.get('decision')
    if isinstance(action, str):
        action_lower = action.lower().strip()
        action = _ACTION_ALIASES.get(action_lower, action_lower)
        p['action'] = action

    # 2. reason 정규화
    if 'reason' not in p:
        for k in _REASON_KEY_ALIASES:
            if k in p:
                p['reason'] = p[k]
                break

    # 3. circulation 정규화
    if 'circulation' not in p:
        for k in _CIRCULATION_KEY_ALIASES:
            if k in p and k != 'circulation':
                p['circulation'] = p[k]
                break

    # 4. devices 컨테이너 정규화
    if 'devices' not in p:
        for k in _DEVICES_CONTAINER_ALIASES:
            if k in p and isinstance(p[k], dict) and k != 'devices':
                p['devices'] = p.pop(k)
                break

    # 5. {"action":"change","target":"water_heater","state":"OFF"} 형태
    if 'target' in p and 'state' in p:
        flag = _DEVICE_KEY_MAP.get(p['target'], p['target'])
        if flag.endswith('_flag'):
            v = _coerce_bool(p['state'])
            if v is not None:
                p.setdefault('devices', {})[flag] = v
        p.pop('target', None)
        p.pop('state', None)

    # 6. devices 안의 한국어/별칭 키 → 표준 키 + 값 boolean 변환
    devices = p.get('devices')
    if isinstance(devices, dict):
        norm_dev = {}
        for k, v in devices.items():
            std_k = _DEVICE_KEY_MAP.get(k, k)
            v_bool = _coerce_bool(v)
            if v_bool is not None:
                norm_dev[std_k] = v_bool
            elif isinstance(v, bool):
                norm_dev[std_k] = v
        p['devices'] = norm_dev

        # devices 안에 circulation 들어간 경우
        if 'circulation' not in p:
            circ = devices.get('circulation') if isinstance(devices, dict) else None
            if circ:
                p['circulation'] = circ

    # 7. 최상위에 직접 장치 키 (예: {"수온히터":"OFF","사유":"..."}) → devices 객체로
    if 'devices' not in p or not p['devices']:
        top_dev = {}
        for k in list(p.keys()):
            std_k = _DEVICE_KEY_MAP.get(k)
            if std_k and std_k.endswith('_flag'):
                v_bool = _coerce_bool(p[k])
                if v_bool is not None:
                    top_dev[std_k] = v_bool
                    p.pop(k, None)
        if top_dev:
            p['devices'] = top_dev

    # 8. action 누락 시 추정
    if not p.get('action'):
        if p.get('devices'):
            p['action'] = 'change'
        else:
            p['action'] = 'keep'

    return p


# ══════════════════
# JSON 응답 파싱
# LLM JSON 응답 파싱 — _normalize_llm_response 우선 적용
# ══════════════════
# ────────────────────────────────────────────────────────────────────
# LLM JSON 응답 파싱 — _normalize_llm_response 우선 적용.
# 정규화 후 action/devices/circulation 검증해 dict 반환. 실패 시 None.
# ────────────────────────────────────────────────────────────────────
def _parse_relay_response(response_text):
    if not response_text:
        return None

    # 중첩 1단계 JSON 매칭 (devices:{...} 포함)
    match = re.search(r'\{(?:[^{}]|\{[^{}]*\})*\}', response_text, re.DOTALL)
    if not match:
        logger.error(f"[AI제어] JSON 패턴 없음: {response_text[:100]}")
        return None

    raw_parsed = safe_json_load(match.group())
    if raw_parsed is None:
        logger.error(f"[AI제어] JSON 파싱 실패: {match.group()[:200]}")
        return None

    # (A) 다형 응답 정규화 — change_relay/adjust/update/한국어 키/target+state 등 흡수
    parsed = _normalize_llm_response(raw_parsed)
    if parsed is None:
        logger.error(f"[AI제어] 응답 정규화 실패")
        return None

    if parsed != raw_parsed:
        logger.info(
            f"[AI제어] 응답 정규화 적용: "
            f"raw_keys={list(raw_parsed.keys())[:6]} → "
            f"std_keys={list(parsed.keys())[:6]}"
        )

    action = parsed.get("action", "keep")
    reason = parsed.get("reason", "")

    if action == "keep":
        return {"action": "keep", "reason": reason}

    if action != "change":
        logger.error(f"[AI제어] 알 수 없는 action: {action}")
        return None

    devices = parsed.get("devices")
    circulation = parsed.get("circulation")

    # LLM이 circulation을 devices 안에 넣은 경우 보정
    if isinstance(devices, dict) and not circulation:
        circulation = devices.pop("circulation", None)

    if not isinstance(devices, dict) or not circulation:
        logger.error(f"[AI제어] devices 또는 circulation 누락: {json.dumps(parsed, ensure_ascii=False)[:150]}")
        return None

    if circulation not in VALID_CIRCULATIONS:
        logger.error(f"[AI제어] 잘못된 순환모드: {circulation}")
        return None

    normalized_devices = {
        'water_heater_flag': bool(devices.get('water_heater_flag', False)),
        'fog_occurs_flag': bool(devices.get('fog_occurs_flag', False)),
    }
    # drainage 는 LLM 이 devices 에 명시한 경우에만 normalized 에 포함 —
    # 미명시 시 _build_relay_values 가 current_relay 값을 보존한다.
    if 'drainage_motor_flag' in devices:
        normalized_devices['drainage_motor_flag'] = bool(devices.get('drainage_motor_flag'))

    return {
        "action": "change",
        "reason": reason,
        "devices": normalized_devices,
        "circulation": circulation,
    }


def _relay_semantic_on(current_relay, house_id, semantic_name, default=False):
    if not current_relay:
        return bool(default)
    pin_key = get_pin_map(house_id).get(semantic_name)
    if pin_key and pin_key in current_relay:
        return bool(current_relay.get(pin_key))
    return bool(current_relay.get(semantic_name, default))


def _current_llm_devices(current_relay, house_id):
    return {
        'water_heater_flag': _relay_semantic_on(current_relay, house_id, 'water_heater_flag'),
        'fog_occurs_flag': _relay_semantic_on(current_relay, house_id, 'fog_occurs_flag'),
        'drainage_motor_flag': _relay_semantic_on(current_relay, house_id, 'drainage_motor_flag'),
    }


# ────────────────────────────────────────────────────────────────────
# keep(현상유지) 결정에도 수온계 안전 3케이스를 적용 — 보정 발생 시 change 전환.
# ────────────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────────────
# 마지막 '유효 change' 결정(순환모드 명시)을 조회 — keep 시 전체 재구성 기준.
# ────────────────────────────────────────────────────────────────────
def _get_last_change_target(farm_id, house_id):
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            r = d.fetch_one(
                "SELECT circulation, water_heater, fog_occurs, drainage_motor "
                "FROM ai_decision_log WHERE farm_id=%s AND house_id=%s "
                "AND action='change' AND circulation IS NOT NULL "
                "ORDER BY decided_at DESC LIMIT 1", (int(farm_id), int(house_id)))
        return dict(r) if r else None
    except Exception as e:
        logger.debug(f"[AI제어] 마지막 change 조회 실패: {e}")
        return None


def _build_keep_safety_repair(current_relay, sensor_data, farm_id, house_id):
    if not current_relay:
        return None
    current_devices = _current_llm_devices(current_relay, house_id)
    fixed, corrections = apply_water_safety(
        dict(current_devices), sensor_data, farm_id, house_id, scope="[AI-keep]"
    )
    if not corrections:
        return None
    return {
        "action": "change",
        "reason": "[keep 안전보정] " + " / ".join(corrections),
        "devices": fixed,
        "corrections": corrections,
    }


# ═════════════════════════════════════════════════════════════════
# 안전 검증
# LLM 응답 안전 검증 — 비상조건 위반·쿨다운 위반·외부순환 제한 거부
# ═════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# LLM 응답 안전 검증 — 환경 판단은 전량 LLM 자율.
# ⛔ [필수 주의] 코드 개입은 2가지뿐: 수온계 안전 3케이스(apply_water_safety —
#   농장주 지정) · 순환모드 유효성(무효 시 keep).
#   비상 임계 판단·외부순환 가부·습도 대응 등은 LLM 이 직접 결정한다.
# ────────────────────────────────────────────────────────────────────
def _validate_safety(parsed, sensor_data, farm_id, house_id, growth_stage='생육기'):
    devices = parsed.get("devices", {})
    circulation = parsed.get("circulation", "")

    # 수온계 안전 3케이스 (혹한 락아웃 / 온난 히터금지 / 혹서 냉각)
    devices, water_corrections = apply_water_safety(
        devices, sensor_data, farm_id, house_id, scope="[AI안전보정]"
    )
    for correction in water_corrections:
        logger.warning(f"[AI제어] 수온계 안전 보정: {correction}")

    # 순환모드 유효성
    if circulation not in VALID_CIRCULATIONS:
        logger.warning(f"[AI제어] 안전 거부: 잘못된 순환모드 {circulation}")
        return None

    return {
        "action": "change",
        "reason": parsed.get("reason", ""),
        "devices": devices,
        "circulation": circulation,
    }


# ════════════════════════
# 메인 AI 제어 함수
# AI 릴레이 제어 메인 함수
# ════════════════════════
# ────────────────────────────────────────────────────────────────────
# AI 릴레이 제어 메인 함수 — 14단계 LLM 흐름 (센서·릴레이·트렌드·최적조건·
# 컨텍스트 빌드·LLM 호출·파싱·안전검증·2-phase 실행).
# 결정 이력은 ai_decision_log 에 기록되어 다음 호출 prompt 에 노출됨.
# ────────────────────────────────────────────────────────────────────
def control_ai_environment(farm_id, house_id, growth_stage='생육기', order_label=""):
    # [제어중재] agent 우선 · 스케줄 failover 상태 플래그 (finally 에서 참조)
    _arb_started = False
    _arb_emergency = False
    _agent_end_at_gate = None
    try:
        scope = house_prefix(order_label, farm_id, house_id)
        # step 헤더는 단순 "0-99" scope 만 사용 — order_label 의 재배사
        # 순회 prefix(예: "[AI재배사 1/1]")는 사이클 헤더 라인에만 표시. 매 단계마다
        # 중복 출력되어 가독성 저하되는 것 방지.
        step_scope = house_prefix("", farm_id, house_id)

        # 14단계 순차 로그 — 알고리즘 모드 "[1/N]" 패턴과 동일 형식.
        # 모든 컨텍스트 수집 단계(4~12)는 try/except 보호 → 실패 시 빈 컨텍스트
        # 폴백, 기존 LLM 흐름·결과 변경 없음.
        steps = AiStepLogger(scope=step_scope, total=14)

        # ─── [AI 1/9] 센서/릴레이 조회 ───
        sensor_data = read_current_sensor_info(farm_id, house_id)
        if not sensor_data:
            steps.skip("센서/릴레이 조회", reason="센서 데이터 없음")
            return {"success": False, "message": "센서 데이터 없음"}

        # ─── [제어 중재] agent 우선 · 스케줄 30분 failover ───
        # agent 릴레이 제어를 기본으로 하고, agent 가 최근(유예분 내) 제어했다면 스케줄
        # 제어는 skip. 단 비상(임계 초과) 시에는 안전 우선으로 항상 진행(예외).
        try:
            from agri_ai_core.src.control import control_arbitration as _arb
            from agri_ai_core.src.control.environment_logic import _check_emergency as _chk_emg
            from agri_ai_core.src.control.ai_thresholds import get_thresholds as _get_ts_arb
            try:
                _emg = bool(_chk_emg(sensor_data, _get_ts_arb(farm_id, house_id))[0])
            except Exception:
                _emg = False
            if not _emg:
                _allow, _why = _arb.should_run_schedule(farm_id, house_id)
                if not _allow:
                    logger.debug(f"{scope}: [제어중재] 스케줄 제어 skip — {_why}")
                    steps.skip("제어 중재", reason=_why)
                    return {"success": True, "action": "arbitration_skip",
                            "message": f"스케줄 제어 중재 skip: {_why}"}
                logger.info(f"{scope}: [제어중재] failover 스케줄 제어 실행 — {_why}")
            else:
                logger.info(f"{scope}: [제어중재] 비상 감지 — 스케줄 제어 예외 진행")
                _arb_emergency = True
            _arb.stamp_schedule_start(farm_id, house_id)
            _arb_started = True
            _st_gate = _arb.get_state(farm_id, house_id)
            _agent_end_at_gate = _st_gate.get('last_agent_ctrl_end_dttm') if _st_gate else None
        except Exception as _e:
            logger.warning(f"{scope}: [제어중재] 게이트 예외 — 제어 진행: {_e}")

        current_relay = read_latest_relay_info(farm_id, house_id)
        steps.step("센서/릴레이 조회",
                   extra=f"내부 {sensor_data.get('indoor_temperature')}℃/"
                         f"{sensor_data.get('indoor_humidity')}% · "
                         f"CO2 {sensor_data.get('co2')}ppm · "
                         f"수온 {sensor_data.get('water_temperature')}℃")
        steps.detail(
            f"센서: 내부 {sensor_data.get('indoor_temperature')}℃ / "
            f"{sensor_data.get('indoor_humidity')}% / CO2 {sensor_data.get('co2')}ppm / "
            f"외부 {sensor_data.get('outdoor_temperature')}℃ / "
            f"{sensor_data.get('outdoor_humidity')}% / 수온 {sensor_data.get('water_temperature')}℃",
            f"릴레이 ON: [{format_relay_on_str(current_relay or {}, house_id)}]",
            f"릴레이 OFF: [{format_relay_off_str(current_relay or {}, house_id)}]",
        )
        _log_ai_status(scope, sensor_data, current_relay, house_id)

        # ─── [AI 2/14] 트렌드 분석 (인메모리 deque) ───
        _trend_detected, trend_info = _detect_trend(farm_id, house_id, sensor_data)
        if trend_info:
            steps.step("트렌드 분석", extra=trend_info[:80])
            steps.detail(trend_info)
        else:
            steps.skip("트렌드 분석", reason="이력 부족(샘플 < 3)")

        # ─── [AI 3/14] 최적조건 DB 조회 ───
        optimal = read_optimal_condition(farm_id, house_id) or {}
        if optimal:
            steps.step("최적조건 조회",
                       extra=f"온도 {optimal.get('온도최저')}~{optimal.get('온도최고')}℃ · "
                             f"습도 {optimal.get('습도최저')}~{optimal.get('습도최고')}%")
            steps.detail(
                f"온도 {optimal.get('온도최저')}~{optimal.get('온도최고')}℃ "
                f"(적정 {optimal.get('온도적정')})",
                f"습도 {optimal.get('습도최저')}~{optimal.get('습도최고')}% "
                f"(적정 {optimal.get('습도적정')})",
                f"CO2 {optimal.get('co2최저')}~{optimal.get('co2최고')}ppm "
                f"(적정 {optimal.get('co2적정')})",
                f"수온 {optimal.get('수온최저')}~{optimal.get('수온최고')}℃ "
                f"(적정 {optimal.get('수온적정')})",
            )
        else:
            steps.skip("최적조건 조회", reason="SENSOR_M_SETTING 행 없음")

        # ─── [AI 4/14] 최근 2개월 + 1년 전 기준점 (M1) ───
        history_block = ""
        try:
            history_block = format_history_block(farm_id, house_id)
            if history_block:
                first_line = history_block.splitlines()[0]
                steps.step("최근 2개월·1년 전 기준점", extra=first_line[:80])
                steps.detail(history_block)
            else:
                steps.skip("최근 2개월·1년 전 기준점", reason="데이터 부족")
        except Exception as e:
            steps.warn("최근 2개월·1년 전 기준점", reason=f"실패 — 빈 컨텍스트: {e}")
            history_block = ""

        # ⛔ [AI 5/14] 알고리즘 참조 결정(M5) 제거 — 2026-07-17 농장주 지시.
        #   python 64케이스 분기가 결정 전체를 계산해 LLM 프롬프트에 앵커로 꽂던 단계.
        #   LLM 이 알고리즘 결론에 끌려가 자율 판단이 훼손되므로 걷어냈다.
        #   ⛔ 알고리즘 본체(_determine_environment_action)는 manual_control 의
        #      알고리즘 모드·LLM 3회연속실패 폴백·비상 경로에서 그대로 살아있다 — 제거 금지.

        # ─── [AI 6/14] LLM 자기결정 이력 (M6) ───
        recent_decisions_block = ""
        try:
            recent_decisions = _get_recent_ai_decisions(farm_id, house_id, limit=5)
            recent_decisions_block = _format_recent_decisions_block(recent_decisions)
            if recent_decisions_block:
                steps.step("자기결정 이력", extra=f"최근 {len(recent_decisions)}건")
                steps.detail(recent_decisions_block)
            else:
                steps.skip("자기결정 이력", reason="ai_decision_log 기록 없음(첫 호출일 수 있음)")
        except Exception as e:
            steps.warn("자기결정 이력", reason=f"실패 — 빈 컨텍스트: {e}")
            recent_decisions_block = ""

        # ─── [AI 7/14] 재배사간 동시점 비교 (M7) ───
        peer_block = ""
        try:
            peer_snap = get_peer_snapshot(farm_id, house_id)
            peer_block = format_peer_block(peer_snap)
            if peer_block:
                steps.step("재배사간 비교",
                           extra=f"동일 농장 {len(peer_snap.get('sensors', []))}개 재배사 비교")
                steps.detail(peer_block)
            else:
                steps.skip("재배사간 비교", reason="10분 이내 동일 농장 다른 재배사 데이터 없음")
        except Exception as e:
            steps.warn("재배사간 비교", reason=f"실패 — 빈 컨텍스트: {e}")
            peer_block = ""

        # ─── [AI 8/14] 수확 임박 + 이상사건 직전 환경 (M8 + M9) ───
        harvest_anomaly_block = ""
        try:
            h_ctx = get_harvest_context(farm_id, house_id)
            h_block = format_harvest_block(h_ctx)
            anomalies = get_anomaly_patterns(farm_id, house_id)
            a_block = format_anomaly_block(anomalies)
            harvest_anomaly_block = "\n".join(b for b in (h_block, a_block) if b)
            if harvest_anomaly_block:
                dr = (h_ctx or {}).get('days_remaining')
                steps.step("수확임박+이상사건",
                           extra=f"수확D-{dr if dr is not None else '?'} 이상사건={len(anomalies)}건")
                steps.detail(harvest_anomaly_block)
            else:
                steps.skip("수확임박+이상사건", reason="작기/이상사건 데이터 없음")
        except Exception as e:
            steps.warn("수확임박+이상사건", reason=f"실패 — 빈 컨텍스트: {e}")
            harvest_anomaly_block = ""

        # ─── [AI 9/14] 외부 기상예보 (M10) ───
        weather_block = ""
        try:
            wf = _get_weather_forecast(farm_id, house_id)
            weather_block = _format_weather_block(wf)
            if weather_block:
                steps.step("외부 기상예보",
                           extra=f"{len((wf or {}).get('forecast', []))} 슬롯 (KMA)")
                steps.detail(weather_block)
            else:
                steps.skip("외부 기상예보", reason="KMA_API_KEY/FARM_NX_FARM_NY 환경변수 미설정")
        except Exception as e:
            steps.warn("외부 기상예보", reason=f"실패 — 빈 컨텍스트: {e}")
            weather_block = ""

        # ─── [AI 9b/14] 외부 대기질 (M11) ───
        air_quality_block = ""
        try:
            aq = _get_air_quality(farm_id)
            air_quality_block = _format_air_quality_block(aq)
            if air_quality_block:
                steps.step("외부 대기질",
                           extra=f"측정소={aq.get('station')} PM2.5={aq.get('pm25')} "
                                 f"PM10={aq.get('pm10')} 통합={aq.get('khai_label')}")
                steps.detail(air_quality_block)
            else:
                steps.skip("외부 대기질",
                           reason="AIRKOREA_API_KEY/AIRKOREA_STATION_NAME 환경변수 미설정")
        except Exception as e:
            steps.warn("외부 대기질", reason=f"실패 — 빈 컨텍스트: {e}")
            air_quality_block = ""

        # ─── [AI 9c/14] 기상특보 (M12) ───
        weather_alert_block = ""
        try:
            wa = _get_weather_alerts(farm_id)
            weather_alert_block = _format_weather_alert_block(wa)
            if weather_alert_block:
                steps.step("기상특보",
                           extra=f"stnId={wa.get('stn_id')} 발효={len(wa.get('alerts') or [])}건")
                steps.detail(weather_alert_block)
            else:
                steps.skip("기상특보", reason="WTHR_WRN_* 미설정 또는 발효 특보 없음")
        except Exception as e:
            steps.warn("기상특보", reason=f"실패 — 빈 컨텍스트: {e}")
            weather_alert_block = ""

        # ─── [AI 9d/14] 대기정체지수 (M13) ───
        atm_stagnation_block = ""
        try:
            ag = _get_atm_stagnation(farm_id)
            atm_stagnation_block = _format_atm_stagnation_block(ag)
            if atm_stagnation_block:
                slots = ag.get('slots') or []
                steps.step("대기정체지수",
                           extra=f"areaNo={ag.get('area_no')} 슬롯={len(slots)}")
                steps.detail(atm_stagnation_block)
            else:
                steps.skip("대기정체지수", reason="ATM_STG_* 미설정 또는 KMA 전파 대기")
        except Exception as e:
            steps.warn("대기정체지수", reason=f"실패 — 빈 컨텍스트: {e}")
            atm_stagnation_block = ""

        # ─── [AI 10/14] 카메라 / 버섯 영상 분석 (M11) ───
        # 즉석 캡처(get_camera_context) 제거 — 매 5초 사이클에서
        #   60초+ 걸리는 Vision LLM 호출이 ollama 큐를 점유해 사용자 채팅 응답을
        #   지연시키던 원인. ai_camera_archive 가 매시간 정각에 캡처+Vision+RAG 처리
        #   하므로 ai_control 은 read_recent_history(DB 조회) 만 사용 — 24시간 이력의
        #   휴리스틱 추세 + 직전 Vision 묘사로 환경 결정에 충분.
        # 영향: 즉석 vision LLM 호출 제거 → ollama 큐 60s 부담 해소.
        # 채팅 품질: tools_definition.py 의 사용자 채팅 프롬프트는 그대로 유지 — 영향 없음.
        camera_block = ""
        history_camera_block = ""
        try:
            history_records = read_recent_history(farm_id, house_id, hours=24)
            history_camera_block = format_image_history_block(history_records)
            if history_camera_block:
                steps.step("재배사 영상 분석 (24시간 이력)",
                           extra=f"DB 이력 {len(history_records)}건 (Vision 분석은 매시간 정각 ai_camera_archive)")
                steps.detail(history_camera_block)
            else:
                steps.skip("재배사 영상 분석",
                           reason="이력 없음 (ai_camera_archive 매시간 정각 캡처 대기)")
        except Exception as e:
            steps.warn("재배사 영상 분석", reason=f"실패 — 빈 컨텍스트: {e}")
            history_camera_block = ""

        # ─── [AI 11/14] RAG (유사 시기 + 도메인 지식) (M2 + M12) ───
        rag_block = ""
        doc_block = ""
        try:
            similar = query_similar_periods(farm_id, house_id, sensor_data, growth_stage)
            rag_block = format_rag_block(similar) if similar else ""
            # doc_query 에 수온/현재 릴레이/상호배타 키워드 포함 —
            # 수온 관련 도메인 룰이 RAG 매칭되어 LLM 에 도달하도록 한다.
            _h_now = bool((current_relay or {}).get('water_heater_flag'))
            _d_now = bool((current_relay or {}).get('drainage_motor_flag'))
            doc_query = (
                f"생육단계 {growth_stage} 내부온도 {sensor_data.get('indoor_temperature')}℃ "
                f"수온 {sensor_data.get('water_temperature')}℃ "
                f"습도 {sensor_data.get('indoor_humidity')}% CO2 {sensor_data.get('co2')}ppm "
                f"수온히터 {'ON' if _h_now else 'OFF'} 배수밸브 {'ON' if _d_now else 'OFF'} "
                f"상호배타 가온 포그 환기 룰"
            )
            doc_items = query_domain_knowledge(doc_query, farm_id=farm_id)
            doc_block = format_doc_block(doc_items)
            steps.step("RAG (유사시기+도메인지식)",
                       extra=f"유사시기={len(similar)}건 / 도메인지식={len(doc_items)}건")
            if rag_block:
                steps.detail("--- 유사 시기 ---", rag_block)
            if doc_block:
                steps.detail("--- 도메인 지식 ---", doc_block)
            if not rag_block and not doc_block:
                steps.detail("(검색 결과 없음 — chroma 비활성/문서 미적재)")
        except Exception as e:
            steps.warn("RAG", reason=f"실패 — 빈 컨텍스트: {e}")

        # ─── [AI 12/14] 수확 결과 상관 + 단기 예측 + 계절성 + 전력 + 최근 시계열 ───
        analytics_block = ""
        try:
            yield_periods = get_high_quality_periods(farm_id, house_id)
            yield_b = format_yield_block(yield_periods)

            forecast_payload = _get_ts_forecast(farm_id, house_id)
            ts_b = _format_ts_forecast_block(forecast_payload)

            seas_rows = get_monthly_seasonality(farm_id, house_id)
            seas_b = format_seasonality_block(seas_rows)

            power_payload = get_power_usage_24h(farm_id, house_id)
            power_b = format_power_block(power_payload)

            # 최근 raw 시계열 (3분×20=60분 분량) — LLM 직접 분석용
            recent_ts = _get_recent_samples(farm_id, house_id)
            ts_raw_b = _format_recent_ts_block(recent_ts)

            analytics_block = "\n".join(
                b for b in (yield_b, ts_b, seas_b, power_b, ts_raw_b) if b
            )
            steps.step("분석/예측 (수확상관·단기예측·계절성·전력·raw 시계열)",
                       extra=f"수확={len(yield_periods)} 예측={'Y' if forecast_payload else 'N'} "
                             f"계절={len(seas_rows)}년 전력={'Y' if power_payload else 'N'} "
                             f"raw={len(recent_ts)}건")
            if analytics_block:
                steps.detail(analytics_block)
            else:
                steps.detail("(모두 데이터 부족)")
        except Exception as e:
            steps.warn("분석/예측", reason=f"실패 — 빈 컨텍스트: {e}")
            analytics_block = ""

        # ─── [AI 13/14] LLM 호출 (Ollama generate) ───
        # 재배사별 동적 임계값을 시스템 프롬프트에 주입
        from agri_ai_core.src.control.ai_thresholds import get_thresholds as _get_ts
        ts_for_prompt = _get_ts(farm_id, house_id)
        system_prompt = _build_system_prompt(growth_stage, ts_for_prompt)
        extra_blocks = [
            recent_decisions_block,
            peer_block,
            harvest_anomaly_block,
            weather_block,
            air_quality_block,      # 외부 대기질 (PM2.5/PM10/O3/NO2/SO2/CO)
            weather_alert_block,    # 기상특보 (호우/강풍/한파/폭염/건조)
            atm_stagnation_block,   # 대기정체지수 (환풍기 효율 보정)
            camera_block,
            history_camera_block,   # 24시간 카메라 이력/추세
            doc_block,
            analytics_block,
        ]
        user_prompt = _build_user_prompt(
            sensor_data, current_relay, growth_stage, optimal, trend_info, house_id,
            history_block=history_block, rag_block=rag_block,
            extra_blocks=extra_blocks, farm_id=farm_id,
        )
        # 프롬프트 길이 + 본문 미리보기를 INFO 로 노출 (로그만으로 추적)
        steps.step("LLM 호출 (Ollama generate)",
                   extra=f"system={len(system_prompt)}자 user={len(user_prompt)}자")
        steps.detail(
            "── system_prompt 미리보기 (앞 600자) ──",
            system_prompt,
            "── user_prompt 전문 ──",
            user_prompt,
        )
        # 디버그 단계로도 보관 (verbose 미설정 환경에서 truncate 회피용)
        logger.debug(f"{scope}: [AI] === 시스템 프롬프트 전문 ===\n{system_prompt}")
        logger.debug(f"{scope}: [AI] === 유저 프롬프트 전문 ===\n{user_prompt}")
        llm_result = _call_llm(system_prompt, user_prompt)

        if not llm_result:
            steps.detail("LLM 응답: (없음 — 호출 실패 또는 타임아웃)")
            _log_ai_decision(scope, "keep", "LLM 호출 실패")
            _record_ai_decision(
                farm_id, house_id, growth_stage=growth_stage,
                action="keep", circulation=None, water_heater=None, fog_occurs=None,
                reason="LLM 호출 실패", sensor_snapshot=sensor_data,
            )
            # ⛔ degraded=True: LLM 이 정상 판단을 못한 keep. manual_control 의
            #    _LLM_FAIL_COUNTER 가 이 플래그로 연속실패를 세어 3회째 algorithm 폴백.
            #    (과거 'LLM' 문자열 매칭이라 파싱·검증 실패가 안 세어졌다 — 2026-07-18)
            return {"success": True, "message": "AI 제어: LLM 실패 → 현상 유지",
                    "action": "keep", "degraded": True}

        # LLM 응답 본문 INFO 출력 (사용자 요청: "LLM 판단 내용")
        steps.detail("LLM 응답 (raw, 최대 800자):", llm_result)
        parsed = _parse_relay_response(llm_result)
        if not parsed:
            steps.detail("응답 파싱 실패 → 현상 유지")
            _log_ai_decision(scope, "keep", "응답 파싱 실패")
            _record_ai_decision(
                farm_id, house_id, growth_stage=growth_stage,
                action="keep", circulation=None, water_heater=None, fog_occurs=None,
                reason="응답 파싱 실패", sensor_snapshot=sensor_data,
            )
            return {"success": True, "message": "AI 제어: 파싱 실패 → 현상 유지",
                    "action": "keep", "degraded": True}

        if parsed.get("action") == "keep":
            reason = parsed.get('reason', '')
            steps.detail(f"파싱 결과: action=keep · 사유: {reason}")

            repair = _build_keep_safety_repair(current_relay, sensor_data, farm_id, house_id)
            if repair:
                fixed_devices = repair["devices"]
                repair_reason = f"{reason} -> {repair['reason']}" if reason else repair["reason"]
                steps.detail("⚠ keep 안전 보정 적용:", *repair.get("corrections", []))
                result = set_relay_value(farm_id, house_id, fixed_devices, raw_mode=False)
                ok = bool(result.get("success", True)) if isinstance(result, dict) else bool(result)
                _log_ai_decision(scope, "change", repair_reason, devices=fixed_devices, circulation=None)
                _record_ai_decision(
                    farm_id, house_id, growth_stage=growth_stage,
                    action="change", circulation=None,
                    water_heater=bool(fixed_devices.get('water_heater_flag')),
                    fog_occurs=bool(fixed_devices.get('fog_occurs_flag')),
                    drainage_motor=bool(fixed_devices.get('drainage_motor_flag')),
                    reason=repair_reason, sensor_snapshot=sensor_data,
                )
                return {
                    "success": ok,
                    "message": f"AI 제어: keep 안전 보정 ({repair_reason})",
                    "action": "change",
                    "devices": fixed_devices,
                    "reason": repair_reason,
                }

            # 잔재 방지 — keep 이어도 마지막 change 목표를 전체 재구성으로 재적용.
            # (조명/관수는 스케줄 재계산, 순환밸브 등은 순환모드 정의대로 정리)
            _last = _get_last_change_target(farm_id, house_id)
            if _last and _last.get('circulation'):
                _dev = {
                    'water_heater_flag': bool(_last['water_heater']) if _last['water_heater'] is not None else False,
                    'fog_occurs_flag': bool(_last['fog_occurs']) if _last['fog_occurs'] is not None else False,
                    'drainage_motor_flag': bool(_last['drainage_motor']) if _last['drainage_motor'] is not None else False,
                }
                _dev, _wc = apply_water_safety(_dev, sensor_data, farm_id, house_id, scope="[AI-keep]")
                try:
                    _execute_control(
                        farm_id, house_id, _dev, _last['circulation'],
                        current_relay, (growth_stage == '수확기'),
                        reason=f"현상유지 재구성({reason})", order_label=order_label,
                    )
                except Exception as _e:
                    logger.warning(f"{scope}: keep 재구성 실패(현상 유지로 폴백): {_e}")
                _log_ai_decision(scope, "keep", f"현상유지 재구성: {reason}")
                _record_ai_decision(
                    farm_id, house_id, growth_stage=growth_stage,
                    action="keep", circulation=_last['circulation'],
                    water_heater=_dev['water_heater_flag'], fog_occurs=_dev['fog_occurs_flag'],
                    drainage_motor=_dev['drainage_motor_flag'],
                    reason=f"현상유지 재구성: {reason}", sensor_snapshot=sensor_data,
                )
                return {"success": True, "message": f"AI 제어: 현상유지 재구성 ({reason})", "action": "keep"}

            _log_ai_decision(scope, "keep", reason)
            _record_ai_decision(
                farm_id, house_id, growth_stage=growth_stage,
                action="keep", circulation=None, water_heater=None, fog_occurs=None,
                reason=reason, sensor_snapshot=sensor_data,
            )
            return {"success": True, "message": f"AI 제어: 현상 유지 ({reason})", "action": "keep"}
        else:
            import json as _json
            steps.detail(
                f"파싱 결과: action=change · 사유: {parsed.get('reason','')}",
                f"순환={parsed.get('circulation')} 장치={parsed.get('devices')}",
            )

        # ─── [AI 14/14] 안전검증 + 2-phase 릴레이 실행 ───
        validated = _validate_safety(parsed, sensor_data, farm_id, house_id, growth_stage)
        if not validated:
            steps.warn("안전검증·실행", reason="검증 실패 → 현상 유지")
            _log_ai_decision(scope, "keep", "안전 검증 실패")
            _record_ai_decision(
                farm_id, house_id, growth_stage=growth_stage,
                action="keep", circulation=None, water_heater=None, fog_occurs=None,
                reason="안전검증 실패", sensor_snapshot=sensor_data,
            )
            return {"success": True, "message": "AI 제어: 안전 검증 실패",
                    "action": "keep", "degraded": True}

        # 안전검증 보정 후 최종 결정 — LLM 원본과 차이가 있는지 비교
        orig_devices = parsed.get('devices', {})
        if (orig_devices != validated['devices']
                or parsed.get('circulation') != validated['circulation']):
            corrected = []
            if orig_devices != validated['devices']:
                corrected.append(f"devices {orig_devices} → {validated['devices']}")
            if parsed.get('circulation') != validated['circulation']:
                corrected.append(f"circulation {parsed.get('circulation')} → {validated['circulation']}")
            steps.detail("⚠ 안전 보정 적용:", *corrected)
        else:
            steps.detail("안전검증 통과 — 보정 없음")

        # [제어중재] 스케줄 LLM 진행 중(60~120초) agent 가 개입(set_relay)했으면
        # 적용 취소하고 agent 판단을 우선한다. 비상(예외 진행) 시에는 취소하지 않음.
        if _arb_started and not _arb_emergency:
            try:
                from agri_ai_core.src.control import control_arbitration as _arb
                if _arb.agent_end_changed(farm_id, house_id, _agent_end_at_gate):
                    logger.info(f"{scope}: [제어중재] 스케줄 LLM 진행 중 agent 개입 → 적용 취소(agent 우선)")
                    steps.skip("안전검증·2-phase 실행", reason="agent 개입 — 스케줄 적용 취소")
                    return {"success": True, "action": "arbitration_yield",
                            "message": "스케줄 제어 중 agent 개입 → 적용 취소"}
            except Exception:
                pass

        _log_ai_decision(
            scope, "change", validated.get('reason', ''),
            devices=validated['devices'], circulation=validated['circulation']
        )
        # 결정 이력 DB 기록 (M6) — 다음 LLM 호출 시 prompt 에 노출
        _record_ai_decision(
            farm_id, house_id, growth_stage=growth_stage,
            action="change", circulation=validated['circulation'],
            water_heater=bool(validated['devices'].get('water_heater_flag')),
            fog_occurs=bool(validated['devices'].get('fog_occurs_flag')),
            reason=validated.get('reason', ''), sensor_snapshot=sensor_data,
            drainage_motor=bool(validated['devices'].get('drainage_motor_flag')),
        )

        steps.step(
            "안전검증·2-phase 실행",
            extra=f"통과 · {validated['circulation']} · "
                  f"히터={validated['devices'].get('water_heater_flag')} "
                  f"포그={validated['devices'].get('fog_occurs_flag')}",
        )
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

        # 16개 릴레이 비트맵을 결정 직후 INFO 로 출력 (사용자 요청 "릴레이 제어 내용")
        try:
            applied = (result or {}).get('devices') if isinstance(result, dict) else None
            if isinstance(applied, dict):
                bitmap = ", ".join(
                    f"r{i}={'ON' if applied.get(f'relay_{i}st_flag') else 'OFF'}"
                    for i in range(1, 17)
                )
                steps.detail(f"적용된 16개 릴레이: [{bitmap}]",
                             f"제어 사유: AI제어({validated.get('reason','')})",
                             f"순환모드: {validated['circulation']} · "
                             f"수확기={'Y' if harvest_mode else 'N'}")
            else:
                steps.detail(
                    f"순환모드 {validated['circulation']} 적용 · "
                    f"수온히터={validated['devices'].get('water_heater_flag')} · "
                    f"포그={validated['devices'].get('fog_occurs_flag')}"
                )
        except Exception as _e:
            steps.detail(f"(비트맵 추출 실패: {_e})")

        steps.done(summary=f"{validated['circulation']} 적용 — 결정/실행 완료")
        logger.info(f"{scope}: [AI] 제어 실행 완료")

        # 호출자가 result.get("action") 으로 라벨링하므로 명시.
        # _execute_control 은 action 키를 반환하지 않아 "unknown" 로그 발생하던 버그 수정.
        if isinstance(result, dict):
            result.setdefault("action", "change")
        return result

    except Exception as e:
        scope = house_prefix(order_label, farm_id, house_id)
        logger.error(f"AI 환경제어 오류 ({scope}): {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "message": f"AI 제어 오류: {str(e)}"}
    finally:
        # [제어중재] 스케줄 제어가 실제 진행됐으면 종료 시각 기록(어느 return 경로든)
        if _arb_started:
            try:
                from agri_ai_core.src.control import control_arbitration as _arb_fin
                _arb_fin.stamp_schedule_end(farm_id, house_id)
            except Exception:
                pass
