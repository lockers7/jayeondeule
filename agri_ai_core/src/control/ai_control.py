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
# [2026-04-28 rev2] 임계값은 ai_thresholds.get_thresholds() 또는 인자 ts 사용
from agri_ai_core.src.control.manual_control import (
    _execute_control, _apply_fog_coupling, _determine_environment_action,
)
# [2026-04-28 신규] AI 환경제어 컨텍스트 확장 — 모든 신규 모듈은 단방향 의존이며
# 모든 호출은 try/except 보호되어 실패 시 빈 문자열 반환 → 기존 LLM 흐름 보존.
from agri_ai_core.src.control.ai_history_context import format_history_block
from agri_ai_core.src.control.ai_rag_context import (
    query_similar_periods, format_rag_block,
)
from agri_ai_core.src.control.ai_step_logger import AiStepLogger
from agri_ai_core.src.control.ai_algorithm_reference import format_algorithm_reference
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
# [변경10 · 2026-04-30] ai_control 의 즉석 Vision LLM 호출 제거 — ai_camera_archive
# 가 매시간 정각에 캡처+Vision+RAG 처리하므로 read_recent_history(DB) 만 사용.
# 환경제어 사이클에서 60초 vision LLM 큐 점유 회피 → 채팅 응답 지연 해소.
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
# [2026-04-28] 최근 raw 시계열 (3분 간격 20건) — LLM 에 직접 노출
from agri_ai_core.src.control.ai_recent_timeseries import (
    get_recent_samples as _get_recent_samples,
    format_recent_block as _format_recent_ts_block,
)
# [2026-04-28 rev4] 모듈 레벨 import — _validate_safety 가드 테스트 monkeypatch 지원
from agri_ai_core.src.control.ai_thresholds import get_thresholds

logger = setup_logger(__name__)

# ══════════════════
# 설정 (환경제어 LLM 전용 — 사용자 대화 LLM 과 분리)
# [2026-04-28 rev3] 사용자 요구: "정확한 판단 우선, 시간 무관" — 토큰·컨텍스트 확장
# ══════════════════
AI_CONTROL_TIMEOUT     = int(os.getenv("AI_CONTROL_TIMEOUT",     "600"))   # [2026-05-04] 180→600s — Ollama 큐 대기 후에도 응답 수신 가능. 제어 결정 지연 허용(사용자 정책).
AI_PROXIMITY_RATIO     = float(os.getenv("AI_PROXIMITY_RATIO",   "0.8"))
AI_CONTROL_NUM_PREDICT = int(os.getenv("AI_CONTROL_NUM_PREDICT", "400"))   # [2026-05-04] 1500 → 400 (실응답 <200토큰 · GPU 점유시간 단축)
AI_CONTROL_NUM_CTX     = int(os.getenv("AI_CONTROL_NUM_CTX",     "16384")) # 모델 기본 4096 → 16k (raw 시계열 + 다중 컨텍스트 수용)

VALID_CIRCULATIONS = set(CIRCULATION_MODES.keys())

# [변경6 · 2026-04-30] PROTECTED_DEVICES 를 RELAY_FIELD_MAPPING.flags 에서 자동 도출.
# RelayDef 의 flags 에 'PROTECTED' 가 설정된 sem 만 자동 포함 — 신규 PROTECTED 릴레이
# 추가 시 mappers.py 의 _PROTECTED_SEMS 만 갱신하면 본 set 자동 반영.
from agri_ai_core.config.mappers import (
    protected_semantic_keys as _protected_semantic_keys,
    device_mapping_text as _device_mapping_text,
    circulation_modes_text as _circulation_modes_text,
)
PROTECTED_DEVICES = _protected_semantic_keys()

# ══════════════════════════════════════════════════════════════════════════════
# [2026-04-28 rev3] (D) Ollama format=<schema> 강제용 JSON Schema
# Ollama 0.5+ 는 이 스키마에 맞는 JSON 만 출력하도록 강제. 모델이 다른 키 못 만듦.
# ══════════════════════════════════════════════════════════════════════════════
RELAY_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["change", "keep"]},
        "reason": {"type": "string"},
        # [2026-05-01] LLM 결정 도메인 확장 — mappers.py 룰 자율 적용.
        # 추가: drainage_motor_flag (수온히터·배수밸브 상호배타 LLM 직접 판단).
        # 향후 더 많은 릴레이를 LLM 에 위임할 수 있으나 우선 가장 영향 큰 1개부터.
        "devices": {
            "type": "object",
            "properties": {
                "water_heater_flag":  {"type": "boolean"},
                "fog_occurs_flag":    {"type": "boolean"},
                "drainage_motor_flag": {"type": "boolean"},
            },
            "required": ["water_heater_flag", "fog_occurs_flag"],
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
    # [2026-04-28 rev2] 임계값 동적 — DB 셋팅
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
    # [2026-04-28 rev2] 임계값 동적 — DB 셋팅
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
        # [2026-05-04 G6] 5초 모니터는 결정/제어 적용 안 함. 60초 _ai_control_loop 가
        #   다음 cycle 에서 LLM 결정 + emergency_override 통합 적용. 본 로그는 가시성용.
        logger.info(f"{scope}: [AI모니터링] 임계치 근접 감지 (다음 LLM cycle 에서 처리)")
        return True

    if trend_detected:
        logger.info(f"{scope}: [AI모니터링] 트렌드 급변 감지 (다음 LLM cycle 에서 처리)")
        return True

    return False


# ══════════════════
# 시스템 프롬프트
# [2026-04-28] ts(ThresholdSet) 인자 추가 — 재배사별 동적 임계값 주입.
# None 이면 control_common 폴백 (기본값).
# ══════════════════
# ────────────────────────────────────────────────────────────────────
# 시스템 프롬프트 빌더 — ts(ThresholdSet) 인자로 재배사별 동적 임계값 주입.
# [2026-04-28] ts None 이면 control_common 폴백 (기본값).
# ────────────────────────────────────────────────────────────────────
def _build_system_prompt(growth_stage, ts=None):
    # [2026-04-28 rev2] ts 가 없으면 ai_thresholds.get_global_default() 폴백 —
    # control_common 임계 상수 직접 import 금지.
    if ts is None:
        from agri_ai_core.src.control.ai_thresholds import get_global_default
        ts = get_global_default()
    return _build_system_prompt_impl(
        growth_stage,
        ts.temp_low, ts.temp_high, ts.temp_critical_low, ts.temp_critical_high,
        ts.humidity_low, ts.humidity_high, ts.humidity_critical_low, ts.humidity_critical_high,
        ts.co2_low, ts.co2_high, ts.co2_critical_high,
        ts.water_temp_low, ts.water_temp_high,
        ts.water_temp_critical_low, ts.water_temp_critical_high,
        ts.budding_temp_low, ts.budding_temp_high,
        ts.source,
    )


# ────────────────────────────────────────────────────────────────────
# 시스템 프롬프트 본체 구현 — 개별 임계 상수를 인자로 받아 텍스트 합성.
# 생육단계별 가이드 + 비상 임계값 + 응답 형식 강제 룰 모두 포함.
# ────────────────────────────────────────────────────────────────────
def _build_system_prompt_impl_v2_9sec(
        growth_stage,
        TEMP_LOW, TEMP_HIGH, TEMP_CRITICAL_LOW, TEMP_CRITICAL_HIGH,
        HUMIDITY_LOW, HUMIDITY_HIGH, HUMIDITY_CRITICAL_LOW, HUMIDITY_CRITICAL_HIGH,
        CO2_LOW, CO2_HIGH, CO2_CRITICAL_HIGH,
        WATER_TEMP_LOW, WATER_TEMP_HIGH, WATER_TEMP_CRITICAL_LOW, WATER_TEMP_CRITICAL_HIGH,
        BUDDING_TEMP_LOW, BUDDING_TEMP_HIGH, ts_src):
    # [2026-05-04 New 9-Section Structure] 검토 제안서 Phase 1~6 일괄 적용.
    #   기존 15섹션(9,300자) → 9섹션(약 4,000자) 통합. 중복·모순·미치환 제거.
    #   DB 블록 lookup 제거 — 코드 inline 단일 source. prompt_block_m 의 control 관련
    #   블록은 더 이상 사용되지 않음 (다른 기능 영향 없음).
    role = "/no_think\n당신은 상황버섯 스마트팜 환경제어 AI입니다.\n\n"

    # ─── §1 시설 구조 + 5종 순환 모드 + 장치 매핑 (기존 §1+§2+§4 통합) ───
    # [2026-05-04 사용자 수정안] 지하수 평균 수온 15℃ 냉각 매개체 명시.
    section1 = (
        "## 1. 시설 구조 · 순환 모드\n"
        "공기흐름: 바닥 흡입 → 환풍기 → 열냉가습기 → 환풍기 → 상단 배출.\n"
        "열냉가습기 = 지하수 탱크 + 수온히터 + 포그생성 + 배수밸브.\n"
        "지하수 평균 수온 15℃ — 고온계절 냉각 매개체로 활용.\n\n"
        "장치 매핑: " + _device_mapping_text() + "\n\n"
        "5종 순환 모드 (밸브 ON 후 15초 → 팬 ON):\n"
        + _circulation_modes_text() + "\n"
        f"※ {', '.join(sorted(PROTECTED_DEVICES))}: 별도 스케줄 제어 (변경 금지)\n\n"
    )

    # ─── §1.5 계절 자동 판단 (사용자 정의 신규) ───
    section_season = (
        "## 계절 자동 판단 (LLM 자체 판단)\n"
        f"- 저온계절 = (내부 < {TEMP_LOW}℃) AND (외기 < 내부)\n"
        "- 고온계절 = 그 외 (내부 적정 안 또는 외기 ≥ 내부)\n"
        "저온계절: 가열 필요 → heater ON + 포그 hysteresis (§3) + 내부순환\n"
        "고온계절: 내부 > 적정 상한 시 지하수 활용 냉각, 정상 안이면 keep\n\n"
    )

    # ─── §2 결정 우선순위 (기존 §5+§10+§13 통합 + 계절 분기) ───
    if growth_stage == '발이기':
        section2 = (
            "## 2. 결정 우선순위 (발이기) — 온도 단독 제어\n"
            f"- 온도 < {BUDDING_TEMP_LOW}℃: heater ON + 내부순환\n"
            f"- 온도 > {BUDDING_TEMP_HIGH}℃: 가열 OFF + 배기순환\n"
            f"- 정상: 제어 없음\n"
            "(습도/CO2 제어 중지)\n\n"
        )
    else:
        section2 = (
            "## 2. 결정 우선순위 — 온도 > CO2 > 습도 (상위 결정 우선)\n\n"
            "[1순위 온도]\n"
            f"- 저온계절 + 내부 < {TEMP_LOW}℃ (저온):\n"
            "    heater ON + 포그 (§3 hysteresis) + 내부순환 → 재배사 가열\n"
            "    외기가 적정 범위 안 → 외부순환 가능 (가능성 희박)\n"
            f"- 고온계절 + 내부 > {TEMP_HIGH}℃ (고온):\n"
            "    heater 절대 OFF + fog ON + drainage ON + 내부순환\n"
            "    (차가운 지하수 새로 유입 + 차가운 수증기 분사 → 내부 냉각)\n"
            "    외기가 적정 범위 안 → 외부순환 가능 (가능성 희박)\n"
            f"- 고온계절 + 내부 ∈ [{TEMP_LOW}, {TEMP_HIGH}]℃: keep (장치 변경 없음)\n"
            "- 그 외 정상: 다음 순위(CO2)\n\n"
            "[2순위 CO2] (온도 결정 보존)\n"
            f"- > {CO2_HIGH}ppm (고농도): 배기순환 권장 (저온계절이면 내부순환 유지)\n"
            "- 정상: 다음 순위(습도)\n\n"
            "[3순위 습도] (상위 결정 보존)\n"
            f"- < {HUMIDITY_LOW}% (저습): 포그 ON 권장 (가열중이면 §3 hysteresis 우선)\n"
            f"- > {HUMIDITY_HIGH}% (고습): 포그 OFF, 배기순환 (상위 결정 우선)\n"
            "- 정상: 현재 모드 유지\n"
        )
        if growth_stage == '수확기':
            section2 += "\n[수확기 추가] 관수 강제 OFF, 배기순환 우선\n"
        section2 += "\n"

    # ─── §3 수온히터 + 포그 통합 룰 (사용자 수정안 — 3℃ hysteresis, 계절 분기) ───
    section3 = (
        "## 3. 수온히터 + 포그 통합 룰 (절대 준수, hysteresis +3℃)\n\n"
        f"[저온계절] (외기 < 내부 AND 내부 < {TEMP_LOW}℃)\n"
        "- 수온 < (실내 + 3℃): heater ON, fog OFF (가열 집중, 분사 손실 방지)\n"
        "- 수온 ≥ (실내 + 3℃): heater ON, fog ON (가열·가습 매개)\n"
        f"- 수온 > {WATER_TEMP_CRITICAL_HIGH}℃ OR 실내 ≥ {TEMP_HIGH}℃: heater 강제 OFF (효율)\n"
        "- 두 임계 사이 직전 상태 유지 (채터링 방지)\n"
        "- 예: 실내 22℃ → 수온 25℃ 가 토글 임계\n\n"
        "[고온계절]\n"
        "- heater 절대 OFF (안전 + 가열 불필요)\n"
        f"- 내부 > {TEMP_HIGH}℃: fog ON + drainage ON → 지하수(15℃) 분사로 냉각\n"
        f"- 내부 ∈ [{TEMP_LOW}, {TEMP_HIGH}]℃: keep (장치 변경 없음)\n\n"
        "[외기 예보 기반 선행 활용 — 2026-05-17 추가]\n"
        "[외부 기상 단기예보] 컨텍스트(향후 1~3h)가 있을 때만 적용 — 비상 룰에 절대 우선하지 않음.\n"
        f"- 낮 외기 최고 > {TEMP_HIGH}℃ 예보 + 실내 상승 추세 + 수온 ≤ 실내:\n"
        "    drainage ON 선행 (지하수 새로 유입 → 탱크 식힘), heater OFF, fog 는 hysteresis 준수.\n"
        f"- 밤 외기 최저 < {TEMP_LOW}℃ 예보 + 실내 하단 접근(하강 추세) + 수온 < (실내+3℃):\n"
        "    drainage OFF (지하수 가둠) + heater ON 선행 가온. 수온이 (실내+3℃) 도달 후 fog ON.\n"
        "- 외기가 외부순환 정상범위(§4) 안이면 외부순환 우선, 본 룰은 외기 범위 밖일 때 의의.\n\n"
        "[비상 우선] (계절 룰 무시 — 안전 강제)\n"
        f"- 내부 < {TEMP_CRITICAL_LOW}℃ (저온비상): heater 강제 ON\n"
        f"- 수온 > {WATER_TEMP_CRITICAL_HIGH}℃ (수온과열): heater 강제 OFF\n\n"
    )

    # ─── §4 외부순환 제한 (기존 §6+§10 #2/#7 외기 분기 통합) ───
    section4 = (
        "## 4. 외부순환 제한\n"
        f"외부온도 ∈ [{TEMP_LOW}, {TEMP_HIGH}]℃ 그리고 외부습도 ∈ [{HUMIDITY_LOW}, {HUMIDITY_HIGH}]% 일 때만 외부순환 가능.\n"
        "범위 밖이면 외부순환 금지 → 내부순환 또는 배기순환 사용.\n"
        "외기 활용 가능 시: 장치 제어보다 외부순환 우선.\n\n"
    )

    # ─── §5 비상 자동 오버라이드 + 선행 조치 (사용자 추세 분석 명시) ───
    section5 = (
        "## 5. 비상 자동 오버라이드 (시스템 강제 — LLM은 정상 결정만)\n"
        "LLM 결정 후 시스템이 비상 위반 항목만 자동 강제. LLM은 회피 로직 불필요:\n"
        f"- 실내 < {TEMP_CRITICAL_LOW}℃ (저온비상) → heater 강제 ON, 내부순환 강제 (계절 룰보다 우선)\n"
        f"- 실내 > {TEMP_CRITICAL_HIGH}℃ (고온비상) → heater 강제 OFF, 외부/배기순환 강제\n"
        f"- 수온 < {WATER_TEMP_CRITICAL_LOW}℃ (수온저온) → heater 강제 ON, drainage 강제 OFF\n"
        f"- 수온 > {WATER_TEMP_CRITICAL_HIGH}℃ (수온과열) → heater 강제 OFF (실내고온 시 drainage ON 추가)\n"
        f"- CO2 > {CO2_CRITICAL_HIGH}ppm (고CO2) → 외부/배기순환 강제\n"
        f"- 습도 비상 (< {HUMIDITY_CRITICAL_LOW}% 또는 > {HUMIDITY_CRITICAL_HIGH}%): 시스템 강제 없음, LLM 자율\n\n"
        "선행 조치 (LLM 자율 판단 — 60분 raw 시계열 분당 변화율 분석):\n"
        "- 수온/실내 추세의 비례·반비례 관계로 5분/1시간 후 예측.\n"
        "- 예: 수온 1℃ 상승 추세 + 실내 1℃ 하락 추세 → 실내가 적정 하한 아래로 하락 예상 시 선행 heater ON.\n"
        "- 추운 계절일수록 수온이 빨리 떨어지고 가온 시간 오래 걸림 → 선행 가열 적극 적용.\n"
        "- [외부 기상 단기예보] 컨텍스트가 있으면 시간대별 외기 추세도 동등 비중으로 활용 (§3 외기 예보 기반 선행 활용 참고).\n\n"
    )

    # ─── §6 현재 호기 임계값 (기존 §7) ───
    section6 = (
        f"## 6. 현재 호기 임계값 ({growth_stage})\n"
        f"- 적정 온도: {TEMP_LOW}~{TEMP_HIGH}℃ (임계 {TEMP_CRITICAL_LOW}~{TEMP_CRITICAL_HIGH}℃)\n"
        f"- 적정 습도: {HUMIDITY_LOW}~{HUMIDITY_HIGH}% (임계 {HUMIDITY_CRITICAL_LOW}~{HUMIDITY_CRITICAL_HIGH}%)\n"
        f"- 적정 CO2: {CO2_LOW}~{CO2_HIGH}ppm (임계 상한 {CO2_CRITICAL_HIGH}ppm)\n"
        f"- 적정 수온: {WATER_TEMP_LOW}~{WATER_TEMP_HIGH}℃ (임계 {WATER_TEMP_CRITICAL_LOW}~{WATER_TEMP_CRITICAL_HIGH}℃)\n\n"
    )

    # ─── §7 추가 컨텍스트 (기존 §14 정리 — 미발송 4종 제거) ───
    section7 = (
        "## 7. 추가 컨텍스트 (user_prompt 블록 — 가용 시 자동 포함)\n"
        "- [알고리즘 참조 결정] 같은 센서값에서 알고리즘이 내릴 결정 (다를 시 reason에 근거 명시)\n"
        "- [직전 5건 결정 이력] 5분 단위 ON↔OFF 진동 회피\n"
        "- [동일 농장 다른 재배사] 합의/이상치 검출\n"
        "- [수확 컨텍스트] D-3 이내면 보수적 결정\n"
        "- [이상사건 직전 패턴] 병해 발생 24h 전 평균 회피\n"
        "- [재배사 카메라 24h 이력] 자실체/곰팡이/결로 이상 감지\n"
        "- [유사시기 RAG / 도메인지식 RAG] 과거 사례·매뉴얼 (캐시 5분)\n"
        "- [수확 성공 패턴] 1등급률 ≥0.6 시기 환경 가능 시 유지\n"
        "- [60분 raw 시계열] 분당 변화율 직접 계산 → 임계 근접 시 사전 조치\n"
        "- [외부 기상 단기예보] 향후 1~3h 외기 온/습/강수 → §3 외기 예보 기반 선행 활용 / §4 외부순환 가부\n"
        "- [외부 대기질] 측정소 PM2.5/PM10/O3/NO2/SO2/CO + 통합대기지수 → PM '나쁨' 이상이면 외부순환 회피(분진 침착·자실체 품질 저하)\n"
        "- [기상특보] 호우/강풍/한파/폭염/건조주의보·경보 발효 시 외부순환·배수·수온히터 선제 대응\n"
        "- [대기정체지수] 시간대별 0~100 — '높음/매우높음' 시각엔 환풍기 효율 저하 → CO2 임계 근접 시 가동시간 가중\n"
        "- [전력] 동일 효과면 가동시간 짧은 옵션 우선\n\n"
        "정상 범위 안에서는 keep 적극 사용 (불필요 변경 회피).\n\n"
    )

    # ─── §8 결합 후처리 (기존 §11 + 인터록 자동 룰) ───
    section8 = (
        "## 8. 결합 후처리 (시스템 자동)\n"
        "- water_heater_flag ON ↔ drainage_motor_flag OFF (가온을 위해 물 가둠)\n"
        "- 팬 ON 시 해당 밸브 최소 10초 선행 ON (인터록)\n\n"
    )

    # ─── §9 응답 JSON 스키마 (기존 §15 압축) ───
    section9 = (
        "## 9. 응답 JSON 스키마 (절대 준수)\n"
        "JSON 한 객체만 출력. 마크다운/설명/코드블럭/이모지 금지.\n"
        "Ollama format=schema 강제 검증 → 위반 시 거부.\n\n"
        "표준:\n"
        '  {"action":"change","reason":"<사유>","devices":{"water_heater_flag":bool,"fog_occurs_flag":bool,"drainage_motor_flag":bool},"circulation":"<5종 중 1>"}\n'
        '  {"action":"keep","reason":"<사유>"}\n\n'
        "허용 값:\n"
        '- action: "change" 또는 "keep"\n'
        '- circulation: "내부순환", "외부순환", "흡입순환", "배기순환", "순환정지"\n'
        "- devices: 3개 키만 (boolean true/false)\n\n"
        "올바른 예시:\n"
        '  {"action":"change","reason":"저온+고습 → heater+fog ON, 내부순환","devices":{"water_heater_flag":true,"fog_occurs_flag":true,"drainage_motor_flag":false},"circulation":"내부순환"}\n'
        '  {"action":"keep","reason":"센서값 안정"}\n\n'
        "금지:\n"
        "- 한국어 키 (수온히터 등) → 영어만\n"
        '- "ON"/"OFF" 문자열 → boolean true/false 만\n'
        "- intake_fan_flag, exhaust_fan_flag, lighting_flag 등 출력 → 순환모드/스케줄로 자동\n"
        "- JSON 외 텍스트 (설명/이모지/공백)\n"
    )

    return (
        role + section1 + section_season + section2 + section3 + section4
        + section5 + section6 + section7 + section8 + section9
    )


def _build_system_prompt_impl(
        growth_stage,
        TEMP_LOW, TEMP_HIGH, TEMP_CRITICAL_LOW, TEMP_CRITICAL_HIGH,
        HUMIDITY_LOW, HUMIDITY_HIGH, HUMIDITY_CRITICAL_LOW, HUMIDITY_CRITICAL_HIGH,
        CO2_LOW, CO2_HIGH, CO2_CRITICAL_HIGH,
        WATER_TEMP_LOW, WATER_TEMP_HIGH, WATER_TEMP_CRITICAL_LOW, WATER_TEMP_CRITICAL_HIGH,
        BUDDING_TEMP_LOW, BUDDING_TEMP_HIGH, ts_src):
    # [2026-05-04] 9-섹션 구조로 위임 (Phase 1~6 일괄 적용).
    return _build_system_prompt_impl_v2_9sec(
        growth_stage,
        TEMP_LOW, TEMP_HIGH, TEMP_CRITICAL_LOW, TEMP_CRITICAL_HIGH,
        HUMIDITY_LOW, HUMIDITY_HIGH, HUMIDITY_CRITICAL_LOW, HUMIDITY_CRITICAL_HIGH,
        CO2_LOW, CO2_HIGH, CO2_CRITICAL_HIGH,
        WATER_TEMP_LOW, WATER_TEMP_HIGH, WATER_TEMP_CRITICAL_LOW, WATER_TEMP_CRITICAL_HIGH,
        BUDDING_TEMP_LOW, BUDDING_TEMP_HIGH, ts_src,
    )


def _build_system_prompt_impl_v1_legacy(
        growth_stage,
        TEMP_LOW, TEMP_HIGH, TEMP_CRITICAL_LOW, TEMP_CRITICAL_HIGH,
        HUMIDITY_LOW, HUMIDITY_HIGH, HUMIDITY_CRITICAL_LOW, HUMIDITY_CRITICAL_HIGH,
        CO2_LOW, CO2_HIGH, CO2_CRITICAL_HIGH,
        WATER_TEMP_LOW, WATER_TEMP_HIGH, WATER_TEMP_CRITICAL_LOW, WATER_TEMP_CRITICAL_HIGH,
        BUDDING_TEMP_LOW, BUDDING_TEMP_HIGH, ts_src):
    # [2026-05-04] 기존 15-섹션 구조 (백업용 — 더 이상 호출되지 않음).
    # 롤백 필요 시 _build_system_prompt_impl 의 위임을 본 함수로 변경.
    # [프롬프트 자동화 · Phase 3-(5)] placeholder 없는 정형 블록은 DB 우선.
    # USE_DB_BLOCKS=1 + DB 존재 시 prompt_block_m 사용, 그 외 inline 폴백.
    _role_header_inline = "/no_think\n당신은 상황버섯 스마트팜 릴레이 제어 전문 AI입니다.\n\n"
    _arch_info_inline = (
        "## 재배사 구조\n"
        "- 공기흐름: 바닥 2열 덕트 흡입 → 환풍기 → 열냉가습기 → 환풍기 → 상단 1열 덕트 배출\n"
        "- 열냉가습기: 지하수 탱크 + 수온히터 + 포그생성 → 물안개를 통과하는 공기에 물안개 온도의 습기를 더하는 장치\n\n"
    )
    _coupling_rules_inline = (
        "## 결합 규칙 [2026-04-28 rev2 — 단일 조건]\n"
        "포그생성은 \"수온이 적정 범위에 도달한 경우에만\" 가동.\n"
        f"  · 수온 ≥ {WATER_TEMP_LOW}℃ → fog_occurs_flag=true (가열된 수온의 열기를 재배사로 유입)\n"
        f"  · 수온 < {WATER_TEMP_LOW}℃ → fog_occurs_flag=false (차가운 안개는 실내 온도를 떨어뜨려 무의미)\n"
        f"  · 수온 > {WATER_TEMP_CRITICAL_HIGH}℃ → fog_occurs_flag=false (뜨거운 물 분사 방지, 안전)\n"
        "  · 수온히터 상태와 fog 결정은 분리: 실내 저온 시 수온히터를 먼저 ON 해 가열을 시작하되, "
        f"포그는 수온이 {WATER_TEMP_LOW}℃ 에 도달한 다음 ON 한다.\n"
        f"- {', '.join(sorted(PROTECTED_DEVICES))}: 별도 스케줄 제어 → 변경 금지\n\n"
    )
    _combo_examples_inline = (
        "### 복합 상황 판단 예시\n"
        "- 저온+고습: 수온히터ON + 포그생성ON + 내부순환 (온도 우선; 결합 규칙으로 포그 ON)\n"
        "- 저온+저습: 수온히터ON + 포그생성ON + 내부순환 (둘 다 가열/가습 방향 일치)\n"
        "- 고온+저습: 포그생성ON + 배기순환 (온도 우선 냉각, 습도는 포그생성으로 보완)\n"
        "- 고온+고습: 전체OFF + 배기순환 (온도·습도 모두 하강 방향 일치)\n"
        "- 정상온도+고습+고CO2: 배기순환 (습도·CO2 동시 해소)\n"
        "- 정상온도+저습+고CO2: 내부순환 + 포그생성ON (습도 우선, CO2는 차선)\n\n"
    )
    _priority_rules_inline = (
        "## 제어 우선순위 (반드시 준수) — 2026-05-03 가열 시퀀스 단일 source 위임\n"
        "온도 > 습도 > CO2 순서로 판단하고, 상위 항목의 결정을 하위 항목이 뒤집지 마세요.\n\n"
        "### 1순위: 온도\n"
        f"- 온도 < {TEMP_LOW}℃ (저온): 수온히터 ON, 내부순환 (가열 우선). "
        f"포그는 [가열 시퀀스 룰] 의 +5℃ hysteresis 따라 결정. "
        f"습도/CO2 조치가 온도를 더 낮추면 안 됨\n"
        f"- 온도 > {TEMP_HIGH}℃ (고온): 가열장치 전체 OFF, 배기순환 (냉각 우선). 습도 조치가 온도를 더 높이면 안 됨\n"
        "- 온도 정상: 다음 순위(습도)로 이동\n\n"
        "### 2순위: 습도 (온도 결정과 충돌 시 온도 우선)\n"
        f"- 습도 < {HUMIDITY_LOW}% (저습): 포그생성 ON + 내부순환 권장. "
        f"가열 페이즈 중이면 [가열 시퀀스 룰] 의 +5℃ hysteresis 가 우선. 온도가 고온이면 배기순환 유지\n"
        f"- 습도 > {HUMIDITY_HIGH}% (고습): 포그생성 OFF + 배기순환 권장. "
        f"단, 온도가 저온이면 내부순환 유지하고 수온히터 ON + 포그는 [가열 시퀀스 룰] 따름 (온도 우선)\n"
        "- 습도 정상: 다음 순위(CO2)로 이동\n\n"
        "### 3순위: CO2 (온도·습도 결정과 충돌 시 상위 우선)\n"
        f"- CO2 > {CO2_HIGH}ppm (고농도): 배기순환 권장. 단, 저온이면 내부순환 유지 (온도 우선)\n"
        "- CO2 정상: 현재 순환모드 유지\n\n"
    )
    _ext_circ_rules_inline = (
        "## 외부순환 제한 규칙\n"
        f"- 외부온도가 {TEMP_LOW}~{TEMP_HIGH}℃ 범위 밖이면 외부순환 금지\n"
        f"- 외부습도가 {HUMIDITY_LOW}~{HUMIDITY_HIGH}% 범위 밖이면 외부순환 금지\n"
        "- 위 조건 충족 시에는 장치 제어보다 외부순환을 우선 활용\n\n"
    )
    if os.getenv("USE_DB_BLOCKS", "0") == "1":
        try:
            from agri_ai_core.src.prompt_registry import get_block as _get_block
            _role_header = _get_block('CONTROL_ROLE_HEADER') or _role_header_inline
            _arch_info = _get_block('CONTROL_ARCHITECTURE_INFO') or _arch_info_inline
            _coupling_rules = _get_block(
                'CONTROL_COUPLING_RULES',
                WATER_TEMP_LOW=WATER_TEMP_LOW,
                WATER_TEMP_CRITICAL_HIGH=WATER_TEMP_CRITICAL_HIGH,
                PROTECTED_DEVICES=', '.join(sorted(PROTECTED_DEVICES)),
            ) or _coupling_rules_inline
            _combo_examples = _get_block('CONTROL_PRIORITY_COMBO_EXAMPLES') or _combo_examples_inline
            _priority_rules = _get_block(
                'CONTROL_PRIORITY_RULES',
                TEMP_LOW=TEMP_LOW, TEMP_HIGH=TEMP_HIGH,
                HUMIDITY_LOW=HUMIDITY_LOW, HUMIDITY_HIGH=HUMIDITY_HIGH,
                CO2_HIGH=CO2_HIGH,
            ) or _priority_rules_inline
            _ext_circ_rules = _get_block(
                'CONTROL_EXTERNAL_CIRCULATION_RULES',
                TEMP_LOW=TEMP_LOW, TEMP_HIGH=TEMP_HIGH,
                HUMIDITY_LOW=HUMIDITY_LOW, HUMIDITY_HIGH=HUMIDITY_HIGH,
            ) or _ext_circ_rules_inline
        except Exception:
            _role_header, _arch_info = _role_header_inline, _arch_info_inline
            _coupling_rules, _combo_examples = _coupling_rules_inline, _combo_examples_inline
            _priority_rules, _ext_circ_rules = _priority_rules_inline, _ext_circ_rules_inline
    else:
        _role_header, _arch_info = _role_header_inline, _arch_info_inline
        _coupling_rules, _combo_examples = _coupling_rules_inline, _combo_examples_inline
        _priority_rules, _ext_circ_rules = _priority_rules_inline, _ext_circ_rules_inline

    base = (
        _role_header +
        _arch_info +
        # ─── [변경7 · 2026-04-30] 장치 기능 상세는 mappers.RELAY_FIELD_MAPPING 의 desc
        # ─── 자동 생성으로 전환. mappers.py 의 _RELAY_DESCRIPTIONS 만 수정하면 본
        # ─── 시스템 프롬프트가 자동 갱신됨 (단일 진실 원천).
        # ─── [변경10 · 2026-04-30] ai_control 은 JSON(action/devices/circulation) 만
        # ─── 출력하므로 풍부한 desc 불필요 → 한 줄 매핑만 사용. 사용자 채팅
        # ─── (tools_definition.py) 은 device_detail_text 그대로 유지하여 품질 보존.
        # ─── 효과: 시스템 프롬프트 ~14kB → ~9kB, 추론 시간 60-90s → 25-40s.
        "## 제어 장치 매핑 (RELAY_FIELD_MAPPING 자동)\n"
        + f"  {_device_mapping_text()}\n\n"
        + _coupling_rules
        # ─── [변경7 · 2026-04-30] 순환 모드는 control_common.CIRCULATION_MODES 자동
        # ─── 생성. CIRCULATION_MODES 에 mode 추가/effect 변경 시 자동 반영.
        + "## 순환 모드 (CIRCULATION_MODES 자동 생성)\n"
        + f"{_circulation_modes_text()}\n\n"
        + _priority_rules
        + _combo_examples
        + _ext_circ_rules
    )

    # [프롬프트 자동화 · Phase 3-(5)-2c] 생육단계 가이드 3종 — DB 우선 / 코드 폴백.
    _stage_inline_budding = (
        "## 현재 생육단계: 발이기 (3~5일)\n"
        f"- 적정 온도: {BUDDING_TEMP_LOW}~{BUDDING_TEMP_HIGH}℃ (온도 제어에만 집중)\n"
        "- 습도/CO2 제어 중지\n"
        f"- 온도 < {BUDDING_TEMP_LOW}℃ → 수온히터ON + 내부순환\n"
        f"- 온도 > {BUDDING_TEMP_HIGH}℃ → 전체 가열OFF + 배기순환\n"
        f"- 온도 정상({BUDDING_TEMP_LOW}~{BUDDING_TEMP_HIGH}℃) → 제어 없음\n\n"
    )
    _stage_inline_harvest = (
        "## 현재 생육단계: 수확기 (2~3일)\n"
        "- 관수 강제 OFF (변경 금지)\n"
        "- 배기순환 우선\n"
        "- 이외 생육기 제어와 동일\n\n"
    )
    _stage_inline_growing = (
        "## 현재 생육단계: 생육기 (2~2.5개월)\n"
        f"- 적정 온도: {TEMP_LOW}~{TEMP_HIGH}℃ (임계: {TEMP_CRITICAL_LOW}~{TEMP_CRITICAL_HIGH}℃)\n"
        f"- 적정 습도: {HUMIDITY_LOW}~{HUMIDITY_HIGH}% (임계: {HUMIDITY_CRITICAL_LOW}~{HUMIDITY_CRITICAL_HIGH}%)\n"
        f"- 적정 CO2: {CO2_LOW}~{CO2_HIGH}ppm (최고임계: {CO2_CRITICAL_HIGH}ppm)\n"
        f"- 적정 수온: {WATER_TEMP_LOW}~{WATER_TEMP_HIGH}℃ (임계: {WATER_TEMP_CRITICAL_LOW}~{WATER_TEMP_CRITICAL_HIGH}℃)\n\n"
    )

    if growth_stage == '발이기':
        stage_guide = _stage_inline_budding
        stage_block_id = 'CONTROL_STAGE_BUDDING'
        stage_kwargs = {
            'BUDDING_TEMP_LOW': BUDDING_TEMP_LOW, 'BUDDING_TEMP_HIGH': BUDDING_TEMP_HIGH,
        }
    elif growth_stage == '수확기':
        stage_guide = _stage_inline_harvest
        stage_block_id = 'CONTROL_STAGE_HARVEST'
        stage_kwargs = {}
    else:
        stage_guide = _stage_inline_growing
        stage_block_id = 'CONTROL_STAGE_GROWING'
        stage_kwargs = {
            'TEMP_LOW': TEMP_LOW, 'TEMP_HIGH': TEMP_HIGH,
            'TEMP_CRITICAL_LOW': TEMP_CRITICAL_LOW, 'TEMP_CRITICAL_HIGH': TEMP_CRITICAL_HIGH,
            'HUMIDITY_LOW': HUMIDITY_LOW, 'HUMIDITY_HIGH': HUMIDITY_HIGH,
            'HUMIDITY_CRITICAL_LOW': HUMIDITY_CRITICAL_LOW, 'HUMIDITY_CRITICAL_HIGH': HUMIDITY_CRITICAL_HIGH,
            'CO2_LOW': CO2_LOW, 'CO2_HIGH': CO2_HIGH, 'CO2_CRITICAL_HIGH': CO2_CRITICAL_HIGH,
            'WATER_TEMP_LOW': WATER_TEMP_LOW, 'WATER_TEMP_HIGH': WATER_TEMP_HIGH,
            'WATER_TEMP_CRITICAL_LOW': WATER_TEMP_CRITICAL_LOW, 'WATER_TEMP_CRITICAL_HIGH': WATER_TEMP_CRITICAL_HIGH,
        }
    if os.getenv("USE_DB_BLOCKS", "0") == "1":
        try:
            from agri_ai_core.src.prompt_registry import get_block as _get_block
            _db_stage = _get_block(stage_block_id, **stage_kwargs)
            if _db_stage:
                stage_guide = _db_stage
        except Exception:
            pass

    # [프롬프트 자동화 · Phase 3-(5)-2d] 비상 임계값 + 선행 조치 — DB 우선 / 코드 폴백.
    _critical_thresh_inline = (
        "## 비상 임계값 처리 정책 (사용자 정의 — 절대 준수)\n"
        "\n"
        "## 🛡️ 운용모드와 비상제어의 분리 원칙 [2026-05-04]\n"
        "  · 본 LLM 결정은 항상 산출되며 비상 시에도 우회되지 않음.\n"
        "  · 시스템이 LLM 결정 후 비상 위반 항목만 자동 오버라이드함:\n"
        "      - 저온비상  → water_heater 강제 ON, 다른 장치는 LLM 결정 보존\n"
        "      - 고온비상  → water_heater 강제 OFF + circulation 강제 (외부/배기), 다른 장치 보존\n"
        "      - 수온저하 → water_heater ON + drainage OFF 강제, 다른 장치 보존\n"
        "      - 수온과열 → water_heater OFF 강제 (실내고온 시 drainage ON 추가), 다른 장치 보존\n"
        "      - 고CO2   → circulation 강제 (외부/배기), 장치는 LLM 결정 보존\n"
        "      - 습도비상 → 시스템 강제 안 함, LLM 자율 판단\n"
        "  · LLM 은 정상 결정만 출력하면 됨. 시스템이 안전 가드를 별도 적용.\n"
        "  · 따라서 LLM 응답에 비상 회피 로직을 따로 넣지 말고, 환경 최적 결정에 집중할 것.\n"
        "\n"
        "## 7개 비상 정책 (LLM 가이드 — 시스템 오버라이드도 동일 룰)\n"
        "\n"
        f"### 1) 내부온도 < {TEMP_CRITICAL_LOW}℃ (저온비상)\n"
        "  · 수온히터 ON 유지\n"
        "  · 수온이 (실내온도 + 5℃) 이상 도달 → 포그생성 ON\n"
        "    (가열된 수온의 열기를 재배사로 분사해 실내 온도를 끌어올림)\n"
        "  · 수온이 (실내온도 + 5℃) 미만으로 떨어지면 → 포그생성 OFF (수온 재가열 우선)\n"
        "  · 위 5℃ hysteresis 를 반복하며 실내 온도를 정상 범위로 복귀\n"
        "    (mappers.py 의 _RELAY_DESCRIPTIONS 가열 효율 룰 -5℃ 와 통일)\n"
        "  · 순환: 내부순환 (외부 차가운 공기 유입 차단)\n"
        "\n"
        f"### 2) 내부온도 > {TEMP_CRITICAL_HIGH}℃ (고온비상)\n"
        f"  · 외부온도가 정상 범위({TEMP_LOW}~{TEMP_HIGH}℃) 안 → 외부순환 (외기로 자연 냉각)\n"
        "  · 외부온도가 정상 범위 밖 → 배수밸브 ON + 포그생성 ON\n"
        "    (탱크의 차가운 지하수가 흘러 새 물 유입 + 차가운 수증기 분사로 능동 냉각)\n"
        "  · 수온히터는 OFF\n"
        "\n"
        f"### 3) 수온 < {WATER_TEMP_CRITICAL_LOW}℃ (수온저온비상 — 선행 가열)\n"
        "  · 직전 60분 raw 시계열에서 수온 분당 변화율과 실내온도 분당 변화율을 함께 분석\n"
        "  · 두 변화율의 비례 관계와 5분/1시간 후 예측값을 활용해\n"
        f"    실내온도가 정상 범위({TEMP_LOW}~{TEMP_HIGH}℃) 를 벗어날 시점을 추정\n"
        "  · 그 시점 도달 전에 미리 수온히터 ON + 포그생성 ON 으로 선행 가열 시작\n"
        "  · 수온이 충분히 회복되고 실내온도 안정화 → 비상 해제\n"
        "  · 단순 반응이 아니라 시계열 기반 예측·선제 대응\n"
        "\n"
        f"### 4) 수온 > {WATER_TEMP_CRITICAL_HIGH}℃ (수온과열비상) — 실내 온도 상황에 따라 분기\n"
        f"  ① 실내 가열 필요 또는 정상 (내부온도 ≤ {TEMP_HIGH}℃):\n"
        "     · 수온히터 OFF (안전)\n"
        "     · 포그/배수밸브는 직전 결정 유지 (현상유지) — LLM 자율 판단 보존\n"
        f"  ② 실내 냉각 필요 (내부온도 > {TEMP_HIGH}℃):\n"
        "     · 수온히터 OFF + 배수밸브 ON\n"
        "       (탱크에 차가운 새 지하수 주입 → 탱크 식힘 → 능동 냉각)\n"
        "     · 포그는 직전 결정 유지 (수온 식은 후 LLM 이 결정)\n"
        "\n"
        f"### 5) 습도 < {HUMIDITY_CRITICAL_LOW}% (저습비상) — 강제 처리 없음\n"
        "  · 시스템이 자동으로 강제 조치하지 않음. LLM 이 자율 판단\n"
        "  · 다른 우선순위 룰(온도 > 습도 > CO2) 준수해 결정\n"
        "\n"
        f"### 6) 습도 > {HUMIDITY_CRITICAL_HIGH}% (고습비상) — 강제 처리 없음\n"
        "  · 동일 — 시스템 강제 조치 없음. LLM 자율 판단\n"
        "\n"
        f"### 7) CO2 > {CO2_CRITICAL_HIGH}ppm (고CO2비상)\n"
        f"  · 외부온도와 내부온도 모두 정상 범위({TEMP_LOW}~{TEMP_HIGH}℃) → 외부순환 (외기로 CO2 희석)\n"
        "  · 외기/내기 중 하나라도 정상 범위 밖 → 배기순환\n"
        "\n"
        "## 일반 보조 룰 (위 비상 정책에 우선하지 않음)\n"
        f"- 수온 ≥ {WATER_TEMP_LOW}℃ 일 때 포그생성 ON 검토 (가열된 수온 열기 재배사 유입)\n"
        "- 수온히터 ON 시 포그생성도 동반 ON 권장 (열 운반 매개체)\n\n"
    )
    _proactive_inline = (
        "## 선행 조치 규칙\n"
        "- 온도/습도/CO2가 정상범위 경계에 접근 중이면, 비상 임계치 도달 전에 예방 조치를 취하세요.\n"
        f"- 예: 온도 {TEMP_HIGH - 0.5}℃ 상승 추세 → 외부순환으로 {TEMP_CRITICAL_HIGH}℃ 도달 방지\n"
        f"- 예: 습도 {HUMIDITY_LOW - 2}% 하강 추세 → 포그생성 가동으로 {HUMIDITY_CRITICAL_LOW}% 미만 방지\n"
        "- 외부 온도/습도도 고려하여 외부순환 적합 여부를 판단하세요.\n\n"
    )
    _context_guide_inline = (
        "## 추가 컨텍스트 활용 가이드 [2026-04-28]\n"
        "유저 프롬프트에는 다음 블록이 (가용한 경우) 포함될 수 있다 — 비어 있으면 무시:\n"
        "- [최근 2개월 운영 통계] 평균/표본·릴레이 가동률 — 현재가 평소 운용에서 벗어났는지 비교.\n"
        "- [1년 전 동일 시점 운영 기준점] 작년 동시기 셋팅·생육 결과 — 성공 패턴과 큰 차이 시 보수적 판단.\n"
        "- [알고리즘 참조 결정] 동일 센서값에서 알고리즘이 내릴 결정 — 크게 다른 결정 시 reason 에 근거 명시.\n"
        "- [직전 LLM 결정 이력] 최근 5회 결정 — oscillation 방지, 5분 단위 ON↔OFF 진동 회피.\n"
        "- [동일 농장 다른 재배사] 동시점 센서/릴레이 — 합의/이상치 검출.\n"
        "- [수확 컨텍스트] 작기 D-N — D-3 이내면 환경 변화 최소화·보수적 결정.\n"
        "- [이상사건 직전 환경 패턴] 병해 발생 직전 24h 평균 — 유사 환경 진입 시 회피.\n"
        "- [외부 기상 단기예보] 향후 1~3시간 외부 온/습/강수 — 외부순환 결정 시 사전 반영.\n"
        "- [재배사 영상 분석] 카메라 캡처(휴리스틱 + Vision LLM) — 자실체 형성도·곰팡이·결로 이상 감지.\n"
        "- [유사 시기 RAG 사례] 동일 재배사 과거 운영 사례 — anomaly/품질 라벨 회피.\n"
        "- [도메인 지식 RAG] 매뉴얼/논문 발췌 — 규칙의 근거 참고.\n"
        "- [수확 성공 패턴] 1등급률 ≥0.6 시기 환경 — 가능하면 유지.\n"
        "- [단기 예측] 5분/1시간 후 — 임계 근접 시 사전 조치.\n"
        "- [다년치 동월 평균] 같은 월 연도별 평균 — 큰 편차 시 사유 필요.\n"
        "- [24h 추정 가동시간/전력] 동일 효과면 가동시간 짧은 옵션 우선.\n"
        "- [최근 N분 간격 raw 시계열] 가장 최근부터 과거 순. 분당 변화율을 직접 계산해 추세 판단. "
        "deque 기반 단기 트렌드보다 우선 사용 — 센서 미연결 직후 0.0 → 정상 회복 같은 급변 직후 "
        "노이즈에 휘둘리지 않도록.\n\n"
    )
    _heater_policy_inline = (
        "## ⚠ 수온히터 가동 정책 [2026-04-28 rev4 — 핵심 원칙]\n"
        "수온히터의 목적은 \"실내 환경 조절(가열·가습)\"이며 포그를 매개체로 한다. "
        "즉 수온 자체의 정상화가 목적이 아님. 다음 원칙을 엄격히 준수하라:\n\n"
        "✅ 수온히터 ON 사유 (하나라도 만족 시):\n"
        f"  1. 실내 온도 < {TEMP_LOW}℃ (저온 — 가열 필요)\n"
        f"  2. 실내 온도 < {TEMP_CRITICAL_LOW}℃ (저온비상 — 가열 강제)\n"
        f"  3. 실내 습도 < {HUMIDITY_CRITICAL_LOW}% (저습비상 — 가열·가습 동시)\n"
        f"  4. 수온 < {WATER_TEMP_CRITICAL_LOW}℃ (수온저하 비상 — 안전상 가열)\n"
        f"  5. 실내 온도 하강 추세로 5분 후 < {TEMP_CRITICAL_LOW}℃ 도달 예측\n\n"
        "❌ 수온히터 가동 금지 케이스:\n"
        f"  · 실내 온도 ∈ [{TEMP_LOW}, {TEMP_HIGH}]℃ 정상범위 + 수온 ≥ {WATER_TEMP_CRITICAL_LOW}℃\n"
        "    → 위 ON 사유에 해당 안 하면 수온히터=false. \"수온 미달\"만으로는 가열 사유 부족.\n"
        "    [2026-05-04] 외부 온도는 OFF 조건에서 제외 — §외부순환 제한 규칙이 외기 유입을 이미 차단하므로 외부 비정상이라도 내부순환 유지 시 OFF 안전.\n"
        f"  · 실내 습도 정상범위 안 + 1시간 후에도 비상 미도달 예측\n"
        "    → 미래 가습 준비 목적의 사전 가열은 금지. keep 우선.\n\n"
        "💡 알고리즘 참조 결정과 다를 경우: 명확한 비상 임계 도달 사유 (위 5개 중 하나) 명시 필수.\n"
        "💡 \"외부순환 금지\" 조건은 가열 사유가 아님. 가습은 수온 25℃ 도달 후 포그로만 진행.\n\n"
    )
    _response_format_inline = (
        "## 응답 형식 — 절대 위반 금지 [2026-04-28 rev3 강화]\n"
        "출력은 오직 단일 JSON 오브젝트. 마크다운·설명·코드블럭(```)·접두사·접미사 모두 금지.\n"
        "스키마는 Ollama format=schema 로 강제 검증되며, 위반 시 응답이 거부된다.\n\n"
        "✅ 표준 스키마 (반드시 정확히 이 키만 사용):\n"
        '  {"action":"change","reason":"<사유 텍스트>","devices":{"water_heater_flag":<true|false>,"fog_occurs_flag":<true|false>,"drainage_motor_flag":<true|false>},"circulation":"<5종 중 1>"}\n'
        '  {"action":"keep","reason":"<사유>"}                              ← 변경 없음 시\n\n'
        "✅ action 은 정확히 \"change\" 또는 \"keep\" 두 값만 허용.\n"
        "✅ devices 는 다음 키만 허용 (값은 boolean true/false 소문자):\n"
        "    · water_heater_flag (수온히터)\n"
        "    · fog_occurs_flag (포그생성)\n"
        "    · drainage_motor_flag (배수밸브) — [선택] mappers.py 의 수온히터·배수밸브 상호배타 룰 본인이 판단 적용\n"
        "✅ circulation 은 정확히 다음 5종 중 하나: \"내부순환\", \"외부순환\", \"흡입순환\", \"배기순환\", \"순환정지\"\n\n"
        "🧠 [자율 판단 가이드 — 2026-05-01]\n"
        "  · mappers.py 의 _RELAY_DESCRIPTIONS 에 명시된 상호배타·의존성 룰을 본인이 직접 적용.\n"
        "  · 수온히터 ON ↔ 배수밸브 OFF 는 가온을 위해 물을 가두는 룰. drainage_motor_flag 를 함께 결정.\n"
        "  · 외기·실내·수온·습도·CO2 종합 판단:\n"
        "      - 외기 > 실내 + 가열 필요 + 외기 ≤ 정상상한 → 외부순환 고려 (외기 열원 활용)\n"
        "      - 외기 < 실내 또는 외기 비상 → 내부순환 (보수적)\n"
        "      - 고습/고CO2 → 배기순환\n"
        "  · 정상 범위 안에서는 keep 도 적극 활용 (불필요한 변경 회피).\n"
        "\n"
        "🔥 [가열 시퀀스 룰 — 사용자 정의·반드시 준수 · 2026-05-03 통일]\n"
        "  실내 저온으로 수온히터 가열이 필요할 때, 포그가 동시 ON 이면 미스트 분사 손실 때문에\n"
        "  탱크 수온이 잘 안 오른다. fog_occurs_flag 는 실내온도 기준 +5℃ 히스테리시스로 결정:\n"
        "  (1) 수온 < (실내온도 + 5℃)  → fog_occurs_flag = false (가열 집중, 분사 손실 방지)\n"
        "  (2) 수온 ≥ (실내온도 + 5℃)  → fog_occurs_flag = true  (가습·가온 재배사 전달)\n"
        "  (3) 두 임계 사이는 직전 상태 유지 (채터링 방지).\n"
        "  예: 실내 22℃ 일 때 — 수온 27℃ 가 토글 임계.\n"
        "  이 +5℃ 실내 기준 히스테리시스는 비상정책 #1 의 5℃ hysteresis 와 통일.\n\n"
        "❌ 사용 금지 키 (모두 반려됨):\n"
        "    change_relay, adjust, update, command, target, state, changes, adjustments, updates, settings, modify\n"
        "❌ 한국어 키 사용 금지: 수온히터, 포그생성, 사유, 순환모드 등 → 영어 표준 키만\n"
        "❌ 값에 \"ON\"/\"OFF\" 문자열 사용 금지 → 반드시 boolean true/false\n"
        "❌ 위에 명시되지 않은 장치(intake_fan_flag, exhaust_fan_flag, lighting_flag 등) 출력 금지 — 순환모드/스케줄로 자동 결정\n"
        "❌ JSON 외 어떤 텍스트도 출력 금지 (전후 빈 줄·설명·이모지 모두 금지)\n\n"
        "✅ 올바른 예시:\n"
        '  {"action":"change","reason":"저온비상 — 수온히터+포그 가열, 배수밸브 OFF로 물 가둠","devices":{"water_heater_flag":true,"fog_occurs_flag":true,"drainage_motor_flag":false},"circulation":"내부순환"}\n'
        '  {"action":"change","reason":"외기(22℃)>실내(19℃)+가열필요 → 외부순환으로 가열보조","devices":{"water_heater_flag":true,"fog_occurs_flag":false,"drainage_motor_flag":false},"circulation":"외부순환"}\n'
        '  {"action":"change","reason":"수온정상+실내정상 — 가열중지+자연수 흐름","devices":{"water_heater_flag":false,"fog_occurs_flag":true,"drainage_motor_flag":true},"circulation":"내부순환"}\n'
        '  {"action":"change","reason":"고습 배기","devices":{"water_heater_flag":false,"fog_occurs_flag":false,"drainage_motor_flag":true},"circulation":"배기순환"}\n'
        '  {"action":"keep","reason":"센서값 안정"}\n\n'
        "❌ 잘못된 예시 (모두 반려됨):\n"
        '  {"action":"change_relay", ...}                  ← change 만 허용\n'
        '  {"수온히터":"ON","포그생성":"OFF"}                ← 한국어/문자열 금지\n'
        '  {"action":"change","target":"water_heater","state":"OFF"}  ← target+state 금지\n'
    )
    _critical_thresh = _critical_thresh_inline
    _proactive = _proactive_inline
    _context_guide = _context_guide_inline
    _heater_policy = _heater_policy_inline
    _response_format = _response_format_inline
    if os.getenv("USE_DB_BLOCKS", "0") == "1":
        try:
            from agri_ai_core.src.prompt_registry import get_block as _get_block
            _critical_thresh = _get_block(
                'CONTROL_CRITICAL_THRESHOLDS',
                TEMP_CRITICAL_LOW=TEMP_CRITICAL_LOW, TEMP_CRITICAL_HIGH=TEMP_CRITICAL_HIGH,
                HUMIDITY_CRITICAL_LOW=HUMIDITY_CRITICAL_LOW, HUMIDITY_CRITICAL_HIGH=HUMIDITY_CRITICAL_HIGH,
                CO2_CRITICAL_HIGH=CO2_CRITICAL_HIGH,
                WATER_TEMP_CRITICAL_LOW=WATER_TEMP_CRITICAL_LOW,
                WATER_TEMP_CRITICAL_HIGH=WATER_TEMP_CRITICAL_HIGH,
                WATER_TEMP_LOW=WATER_TEMP_LOW,
            ) or _critical_thresh_inline
            _proactive = _get_block(
                'CONTROL_PROACTIVE_ACTIONS',
                TEMP_HIGH_PRE=TEMP_HIGH - 0.5, TEMP_CRITICAL_HIGH=TEMP_CRITICAL_HIGH,
                HUMIDITY_LOW_PRE=HUMIDITY_LOW - 2, HUMIDITY_CRITICAL_LOW=HUMIDITY_CRITICAL_LOW,
            ) or _proactive_inline
            _context_guide = _get_block('CONTROL_CONTEXT_GUIDE') or _context_guide_inline
            _heater_policy = _get_block(
                'CONTROL_HEATER_POLICY',
                TEMP_LOW=TEMP_LOW, TEMP_HIGH=TEMP_HIGH,
                TEMP_CRITICAL_LOW=TEMP_CRITICAL_LOW,
                HUMIDITY_CRITICAL_LOW=HUMIDITY_CRITICAL_LOW,
                WATER_TEMP_CRITICAL_LOW=WATER_TEMP_CRITICAL_LOW,
            ) or _heater_policy_inline
            _response_format = _get_block('CONTROL_RESPONSE_FORMAT') or _response_format_inline
        except Exception:
            pass

    rules = (
        _critical_thresh
        + _proactive
        + _heater_policy
        + _context_guide
        + _response_format
    )

    return base + stage_guide + rules


# ══════════════════
# 유저 프롬프트
# [2026-04-28] history_block / rag_block 인자가 default 값으로 추가됨 — 기존 호출자
# (시그니처 5번째까지만 위치인자) 와 호환 유지. 빈 문자열이면 섹션 자체 생략.
# ══════════════════
# ────────────────────────────────────────────────────────────────────
# 유저 프롬프트 빌더 — 센서·릴레이·생육·최적조건·트렌드+추가 블록 합성.
# [2026-04-28] history_block / rag_block / extra_blocks 인자 추가 — 빈 문자열
# 이면 섹션 자체 생략. 기존 호출자(5번째 위치인자) 와 호환 유지.
# ────────────────────────────────────────────────────────────────────
def _build_user_prompt(sensor_data, current_relay, growth_stage, optimal, trend_info, house_id,
                       history_block: str = "", rag_block: str = "",
                       extra_blocks=None):
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
        # [2026-05-04] None~None 노출 방지 — 6개 키 모두 값이 있을 때만 출력
        _opt_keys = ('온도최저', '온도최고', '습도최저', '습도최고', '수온최저', '수온최고')
        if all(optimal.get(k) is not None for k in _opt_keys):
            parts.append(
                f"최적조건: "
                f"온도={optimal.get('온도최저')}~{optimal.get('온도최고')}℃, "
                f"습도={optimal.get('습도최저')}~{optimal.get('습도최고')}%, "
                f"수온={optimal.get('수온최저')}~{optimal.get('수온최고')}℃"
            )

    # [2026-05-05 옵션 B] 센서 평가 사전 처리 — LLM 의 임계 비교 한계 보완.
    #   gemma3:27b 가 "27.0 vs 28.0" 같은 미세 비교를 헐겁게 해석하는 패턴 보완.
    #   각 항목별 임계 비교 결과를 명시적으로 제공하여 LLM 이 추론 없이 정확 판단.
    #   §2 우선순위 (온도>CO2>습도) 의 "1순위 통과/2순위 트립/3순위 트립" 단계를
    #   비교 결과로 직접 표시.
    if optimal:
        eval_lines = []
        in_t = sensor_data.get('indoor_temperature')
        in_h = sensor_data.get('indoor_humidity')
        co2v = sensor_data.get('co2')
        t_lo = optimal.get('온도최저')
        t_hi = optimal.get('온도최고')
        h_lo = optimal.get('습도최저')
        h_hi = optimal.get('습도최고')
        co2_hi = optimal.get('co2최고') or optimal.get('CO2최고')
        if in_t is not None and t_lo is not None and t_hi is not None:
            if in_t < t_lo:
                eval_lines.append(f"- 온도 {in_t}℃ < 적정하한 {t_lo}℃ → 저온 (1순위 트립)")
            elif in_t > t_hi:
                eval_lines.append(f"- 온도 {in_t}℃ > 적정상한 {t_hi}℃ → 고온 (1순위 트립)")
            else:
                eval_lines.append(
                    f"- 온도 {in_t}℃ ∈ [{t_lo}, {t_hi}]℃ → 정상 (1순위 통과 — 다음 순위 평가)"
                )
        if co2v is not None and co2_hi is not None:
            if co2v > co2_hi:
                eval_lines.append(f"- CO2 {co2v}ppm > 적정상한 {co2_hi}ppm → 고농도 (2순위 트립)")
            else:
                eval_lines.append(
                    f"- CO2 {co2v}ppm ≤ 적정상한 {co2_hi}ppm → 정상 (2순위 통과 — 다음 순위 평가)"
                )
        if in_h is not None and h_lo is not None and h_hi is not None:
            if in_h < h_lo:
                eval_lines.append(f"- 습도 {in_h}% < 적정하한 {h_lo}% → 저습 (3순위 트립)")
            elif in_h > h_hi:
                eval_lines.append(f"- 습도 {in_h}% > 적정상한 {h_hi}% → 고습 (3순위 트립)")
            else:
                eval_lines.append(f"- 습도 {in_h}% ∈ [{h_lo}, {h_hi}]% → 정상 (3순위 통과)")
        if eval_lines:
            parts.append("[센서 평가 — 임계 비교 결과 (1순위 트립 시에만 1순위 룰 적용, 통과 시 다음 순위)]")
            parts.extend(eval_lines)

    parts.append(f"현재 릴레이: {relay_str}")

    if trend_info:
        parts.append(trend_info)

    if history_block:
        parts.append(history_block)
    if rag_block:
        parts.append(rag_block)

    # [2026-04-28] 추가 신규 블록 — 비어있는 블록은 자동 제외
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
# [2026-04-28 rev3] (D) JSON Schema 강제 + 확장된 토큰/컨텍스트.
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

    base_payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "keep_alive": -1,  # GPU 영구 상주 보장 (정수 -1 = infinite)
        "options": {
            "temperature": 0,
            "num_predict": AI_CONTROL_NUM_PREDICT,   # [2026-05-04] 400 (실응답 <200토큰)
            "num_ctx":     AI_CONTROL_NUM_CTX,       # 16384
        },
    }

    # [2026-05-04] 폴백 3단계 → schema 단일 — Ollama 0.5+ 가 schema 완벽 지원하며
    #   실 운영 로그상 폴백 시도들도 동일 사유(Ollama 큐 행/timeout)로 모두 실패함이
    #   확인됨. 단일 시도로 실패 시 즉시 algorithm_fallback 으로 넘겨 Ollama 큐 압박 ↓.
    attempts = [
        ("schema", {**base_payload, "format": RELAY_RESPONSE_SCHEMA}),
    ]

    logger.info(
        f"[AI제어] LLM 요청 model={model_name} num_predict={AI_CONTROL_NUM_PREDICT} "
        f"num_ctx={AI_CONTROL_NUM_CTX} timeout={AI_CONTROL_TIMEOUT}s prompt_len={len(prompt)}"
    )

    for stage, payload in attempts:
        t_start = time.time()
        try:
            status_code, data, error_text = http_json_request(
                method="POST",
                url=f"{ollama_url}/api/generate",
                json_body=payload,
                timeout=AI_CONTROL_TIMEOUT,
            )
        except Exception as e:
            logger.warning(f"[AI제어] LLM {stage} 호출 예외: {e}")
            continue

        elapsed = time.time() - t_start

        if status_code == 200 and data:
            response_text = data.get("response", "") if isinstance(data, dict) else ""
            logger.info(
                f"[AI제어] LLM 응답 ({elapsed:.1f}s, format={stage}): {response_text[:200]}"
            )
            return response_text

        # [2026-05-04] 단일 시도(schema) 실패 → algorithm_fallback 위임
        logger.warning(
            f"[AI제어] LLM {stage} 실패 status={status_code} ({elapsed:.1f}s) "
            f"err={(error_text or '')[:120]}"
        )

    logger.error("[AI제어] LLM 호출 실패 → algorithm fallback 위임")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# [2026-04-28 rev3] (A) LLM 응답 정규화 — 다형 응답을 표준 스키마로 변환
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
# LLM JSON 응답 파싱 — [2026-04-28 rev3] _normalize_llm_response 우선 적용
# ══════════════════
# ────────────────────────────────────────────────────────────────────
# LLM JSON 응답 파싱 — [2026-04-28 rev3] _normalize_llm_response 우선 적용.
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

    return {
        "action": "change",
        "reason": reason,
        "devices": normalized_devices,
        "circulation": circulation,
    }


# ═════════════════════════════════════════════════════════════════
# 안전 검증
# LLM 응답 안전 검증 — 비상조건 위반·쿨다운 위반·외부순환 제한 거부
# ═════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# LLM 응답 안전 검증 — 비상 임계 위반·외부순환 제한·수온히터 정책 등 보정.
# 위반 시 강제 OFF/ON 또는 순환모드 강제 전환. 잘못된 모드는 None 반환.
# ────────────────────────────────────────────────────────────────────
def _validate_safety(parsed, sensor_data, farm_id, house_id, growth_stage='생육기'):
    devices = parsed.get("devices", {})
    circulation = parsed.get("circulation", "")

    indoor_temp = sensor_data.get('indoor_temperature')
    indoor_humidity = sensor_data.get('indoor_humidity')
    co2 = sensor_data.get('co2')
    water_temp = sensor_data.get('water_temperature')
    outdoor_temp = sensor_data.get('outdoor_temperature')
    outdoor_humidity = sensor_data.get('outdoor_humidity')

    # [2026-04-28] 재배사별 동적 임계값 — DB SENSOR_M_SETTING 우선 (모듈 레벨 import 사용)
    ts = get_thresholds(farm_id, house_id)
    TEMP_CRITICAL_LOW = ts.temp_critical_low
    TEMP_CRITICAL_HIGH = ts.temp_critical_high
    HUMIDITY_CRITICAL_LOW = ts.humidity_critical_low
    HUMIDITY_CRITICAL_HIGH = ts.humidity_critical_high
    WATER_TEMP_CRITICAL_LOW = ts.water_temp_critical_low
    WATER_TEMP_CRITICAL_HIGH = ts.water_temp_critical_high
    TEMP_LOW = ts.temp_low
    TEMP_HIGH = ts.temp_high
    HUMIDITY_LOW = ts.humidity_low
    HUMIDITY_HIGH = ts.humidity_high

    # (1) 비상 온도 위반 방지
    if indoor_temp is not None:
        if indoor_temp > TEMP_CRITICAL_HIGH:
            # 고온 비상 시 가열 장치 ON 거부
            if devices.get('water_heater_flag'):
                logger.warning(f"[AI제어] 안전 보정: 고온비상({indoor_temp}℃) → 가열장치 강제 OFF")
                devices['water_heater_flag'] = False
            if circulation not in ('배기순환', '외부순환'):
                circulation = '배기순환'
                logger.warning(f"[AI제어] 안전 보정: 고온비상 → 배기순환 강제")

        elif indoor_temp < TEMP_CRITICAL_LOW:
            # 저온 비상 시 가열 OFF 거부
            if not devices.get('water_heater_flag'):
                logger.warning(f"[AI제어] 안전 보정: 저온비상({indoor_temp}℃) → 수온히터 강제 ON")
                devices['water_heater_flag'] = True

    # (2) [2026-05-04 Phase D] 사용자 정책 #5/#6 — 습도 비상 강제 가드 제거.
    # 습도 단독 비상은 LLM 자율 판단 영역. _emergency_override 도 처리 안 함.

    # (3) 수온 비상 위반 방지
    if water_temp is not None:
        if water_temp > WATER_TEMP_CRITICAL_HIGH and devices.get('water_heater_flag'):
            logger.warning(f"[AI제어] 안전 보정: 수온과열({water_temp}℃) → 수온히터 강제 OFF")
            devices['water_heater_flag'] = False
        elif water_temp < WATER_TEMP_CRITICAL_LOW and not devices.get('water_heater_flag'):
            logger.warning(f"[AI제어] 안전 보정: 수온저하({water_temp}℃) → 수온히터 강제 ON")
            devices['water_heater_flag'] = True

    # (4) 외부순환 제한 검증
    if circulation == '외부순환':
        ext_temp_bad = outdoor_temp is not None and (outdoor_temp < TEMP_LOW or outdoor_temp > TEMP_HIGH)
        ext_hum_bad = outdoor_humidity is not None and (outdoor_humidity < HUMIDITY_LOW or outdoor_humidity > HUMIDITY_HIGH)
        if ext_temp_bad or ext_hum_bad:
            logger.warning(f"[AI제어] 안전 보정: 외부환경 부적합(외부온도={outdoor_temp}, 외부습도={outdoor_humidity}) → 내부순환 전환")
            circulation = '내부순환'

    # (5) 포그생성 결합 규칙 — environment_logic.apply_fog_coupling 위임
    # [2026-04-28] (a) 수온히터 ON ⟹ 포그 ON, (b) 수온 ≥ WATER_TEMP_LOW(40℃) ⟹
    # 포그 ON. 단 indoor_temp > TEMP_CRITICAL_HIGH 고온비상은 안전 우선으로 보류.
    # 온도 제어가 실내습도보다 우선이므로 (2) 고습비상에서 fog OFF 로 강제됐더라도
    # heater ON 또는 수온이 충분하면 여기서 다시 ON 으로 덮어쓴다.
    _apply_fog_coupling(devices, sensor_data, scope="[AI안전보정]")

    # (6) [2026-05-01] 수온히터 정책 보정 코드 제거.
    # 사유: LLM 이 mappers.py 의 _RELAY_DESCRIPTIONS (수온히터 의존성, 외기/실내 비교
    #   가이드) 를 종합 판단해 결정한 결과를 정책으로 강제 OFF 하던 코드가 LLM 자율성을
    #   가장 크게 제한하던 부분. 이제 critical 임계 안전 가드(_validate_safety)만 유지하고
    #   정상 범위 결정은 LLM 에 위임. 외기·실내 컨텍스트(예: 외기>실내+가열필요→외부순환)
    #   는 LLM 이 직접 판단해 reason 으로 설명한다.

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
    try:
        scope = house_prefix(order_label, farm_id, house_id)
        # [2026-04-28] step 헤더는 단순 "0-99" scope 만 사용 — order_label 의 재배사
        # 순회 prefix(예: "[AI재배사 1/1]")는 사이클 헤더 라인에만 표시. 매 단계마다
        # 중복 출력되어 가독성 저하되는 것 방지.
        step_scope = house_prefix("", farm_id, house_id)

        # [2026-04-28] 14단계 순차 로그 — 알고리즘 모드 "[1/N]" 패턴과 동일 형식.
        # 모든 컨텍스트 수집 단계(4~12)는 try/except 보호 → 실패 시 빈 컨텍스트
        # 폴백, 기존 LLM 흐름·결과 변경 없음.
        steps = AiStepLogger(scope=step_scope, total=14)

        # ─── [AI 1/9] 센서/릴레이 조회 ───
        sensor_data = read_current_sensor_info(farm_id, house_id)
        if not sensor_data:
            steps.skip("센서/릴레이 조회", reason="센서 데이터 없음")
            return {"success": False, "message": "센서 데이터 없음"}

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

        # ─── [AI 5/14] 알고리즘 참조 결정 (M5) ───
        algo_block = ""
        try:
            algo_action = _determine_environment_action(sensor_data, growth_stage, farm_id, house_id)
            algo_block = format_algorithm_reference(algo_action) if algo_action else ""
            if algo_block and algo_action:
                steps.step("알고리즘 참조 결정",
                           extra=f"{algo_action.get('reason','')[:30]} → "
                                 f"{algo_action.get('circulation','-')}")
                steps.detail(
                    f"reason={algo_action.get('reason','')}",
                    f"circulation={algo_action.get('circulation')}",
                    f"devices={algo_action.get('devices')}",
                    f"is_emergency={algo_action.get('is_emergency')} "
                    f"water_temp_only={algo_action.get('water_temp_only')}",
                )
            else:
                steps.skip("알고리즘 참조 결정", reason="알고리즘 판단 불가")
        except Exception as e:
            steps.warn("알고리즘 참조 결정", reason=f"실패 — 빈 컨텍스트: {e}")
            algo_block = ""

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

        # ─── [AI 9b/14] 외부 대기질 (M11) [2026-05-17 신규] ───
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

        # ─── [AI 9c/14] 기상특보 (M12) [2026-05-19 신규] ───
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

        # ─── [AI 9d/14] 대기정체지수 (M13) [2026-05-19 신규] ───
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
        # [변경10 · 2026-04-30] 즉석 캡처(get_camera_context) 제거 — 매 5초 사이클에서
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
            doc_query = (
                f"생육단계 {growth_stage} 내부온도 {sensor_data.get('indoor_temperature')}℃ "
                f"습도 {sensor_data.get('indoor_humidity')}% CO2 {sensor_data.get('co2')}ppm"
            )
            doc_items = query_domain_knowledge(doc_query)
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

            # [2026-04-28] 최근 raw 시계열 (3분×20=60분 분량) — LLM 직접 분석용
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
        # [2026-04-28] 재배사별 동적 임계값을 시스템 프롬프트에 주입
        from agri_ai_core.src.control.ai_thresholds import get_thresholds as _get_ts
        ts_for_prompt = _get_ts(farm_id, house_id)
        system_prompt = _build_system_prompt(growth_stage, ts_for_prompt)
        extra_blocks = [
            algo_block,
            recent_decisions_block,
            peer_block,
            harvest_anomaly_block,
            weather_block,
            air_quality_block,      # [2026-05-17] 외부 대기질 (PM2.5/PM10/O3/NO2/SO2/CO)
            weather_alert_block,    # [2026-05-19] 기상특보 (호우/강풍/한파/폭염/건조)
            atm_stagnation_block,   # [2026-05-19] 대기정체지수 (환풍기 효율 보정)
            camera_block,
            history_camera_block,   # [변경8 · 2026-04-30] 24시간 카메라 이력/추세
            doc_block,
            analytics_block,
        ]
        user_prompt = _build_user_prompt(
            sensor_data, current_relay, growth_stage, optimal, trend_info, house_id,
            history_block=history_block, rag_block=rag_block,
            extra_blocks=extra_blocks,
        )
        # [2026-04-28] 프롬프트 길이 + 본문 미리보기를 INFO 로 노출 (로그만으로 추적)
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
            return {"success": True, "message": "AI 제어: LLM 실패 → 현상 유지", "action": "keep"}

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
            return {"success": True, "message": "AI 제어: 파싱 실패 → 현상 유지", "action": "keep"}

        if parsed.get("action") == "keep":
            reason = parsed.get('reason', '')
            steps.detail(f"파싱 결과: action=keep · 사유: {reason}")
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
            return {"success": True, "message": "AI 제어: 안전 검증 실패", "action": "keep"}

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

        # [2026-05-04 G5] 호출자가 result.get("action") 으로 라벨링하므로 명시.
        # _execute_control 은 action 키를 반환하지 않아 "unknown" 로그 발생하던 버그 수정.
        if isinstance(result, dict):
            result.setdefault("action", "change")
        return result

    except Exception as e:
        scope = house_prefix(order_label, farm_id, house_id)
        logger.error(f"AI 환경제어 오류 ({scope}): {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "message": f"AI 제어 오류: {str(e)}"}
