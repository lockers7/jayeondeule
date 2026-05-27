# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 컨텍스트 확장 모듈 단위테스트 (M5~M17)
# DB/외부 API 의존 함수는 monkeypatch 로 mock 하고, 포맷터·격리·
# 시그니처·로깅 등 순수 영역만 검증. ai_control._build_user_prompt 의 기존
# 시그니처 호환성도 회귀 검사.
# ══════════════════════════════════════════════════════════════════════════════
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ════════════════════════════════════════════════════════════════════════════
# 격리 검증 — 새 모듈은 동급 control 모듈을 import 하지 않음
# (ai_decision_log → postgresql 만, ai_feedback → ai_decision_log 만 예외)
# ════════════════════════════════════════════════════════════════════════════
def test_isolation_no_cross_import_to_control():
    targets = [
        'ai_peer_compare', 'ai_harvest_context',
        'ai_anomaly_history', 'ai_weather_forecast', 'ai_camera_vision',
        'ai_doc_rag', 'ai_yield_correlation', 'ai_forecast',
        'ai_seasonality', 'ai_power_usage', 'ai_history_context',
        'ai_rag_context', 'ai_step_logger',
    ]
    forbidden = (
        'from agri_ai_core.src.control.manual_control',
        'from agri_ai_core.src.control.environment_logic',
        'from agri_ai_core.src.control.ai_control',
    )
    for name in targets:
        path = os.path.join(ROOT, 'agri_ai_core', 'src', 'control', f'{name}.py')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        for forbid in forbidden:
            assert forbid not in content, f"{name}.py가 {forbid}를 import함 (격리 위반)"


# ⛔ M5 ai_algorithm_reference 는 2026-07-17 농장주 지시로 모듈째 제거됐다.
#   (python 64케이스 결정을 LLM 프롬프트에 앵커로 꽂아 자율 판단을 훼손)
#   재발 방지 검증은 tests/control/test_llm_autonomy_no_anchors.py 로 이관.


# ════════════════════════════════════════════════════════════════════════════
# M3 ai_step_logger — 단계 카운터
# ════════════════════════════════════════════════════════════════════════════
def test_step_logger_counter():
    from agri_ai_core.src.control.ai_step_logger import AiStepLogger
    s = AiStepLogger("[테스트]", total=5)
    s.step("a")
    s.skip("b", reason="x")
    s.warn("c", reason="y")
    s.step("d")
    assert s.idx == 4
    s.done(summary="end")  # idx 증가 없음


# ════════════════════════════════════════════════════════════════════════════
# AiStepLogger prefix 인자 — AI / ALGO / LLM 모두 동일 클래스로 호출 가능
# ════════════════════════════════════════════════════════════════════════════
def test_step_logger_prefix_variants():
    from agri_ai_core.src.control.ai_step_logger import AiStepLogger
    ai = AiStepLogger("[1/3]", total=14)
    assert ai.prefix == "AI"
    algo = AiStepLogger("[2/4]", total=5, prefix="ALGO")
    assert algo.prefix == "ALGO"
    llm = AiStepLogger("[대화]", total=4, prefix="llm")  # 소문자도 허용
    assert llm.prefix == "LLM"
    # head() 동작
    ai.step("x")
    assert "[AI 1/14]" in ai._head()


# ════════════════════════════════════════════════════════════════════════════
# apply_water_safety — 3케이스 밖에서는 LLM 결정 완전 보존 (상세는 tests/control/)
# ════════════════════════════════════════════════════════════════════════════
def test_water_safety_preserves_llm_outside_cases():
    from agri_ai_core.src.control.environment_logic import apply_water_safety, _WS_HEATER_LOCKOUT
    _WS_HEATER_LOCKOUT.clear()
    devices = {'water_heater_flag': True, 'fog_occurs_flag': True}
    _, corr = apply_water_safety(devices, {'water_temperature': 30, 'indoor_temperature': 24,
                                           'outdoor_temperature': 5.0}, 0, 99)
    assert corr == []
    assert devices['fog_occurs_flag'] is True and devices['water_heater_flag'] is True
    # 센서 결함(외부 None) — 개입 없음
    devices2 = {'water_heater_flag': True, 'fog_occurs_flag': True}
    _, corr2 = apply_water_safety(devices2, {'water_temperature': 65, 'outdoor_temperature': None}, 0, 99)
    assert corr2 == [] and devices2 == {'water_heater_flag': True, 'fog_occurs_flag': True}


# ════════════════════════════════════════════════════════════════════════════
# ai_thresholds — DB 동적 로드 + 자동 비상 도출
# ════════════════════════════════════════════════════════════════════════════
def test_thresholds_last_resort_fallback():
    """DB 미연결/행 부재 시 last_resort 폴백."""
    from agri_ai_core.src.control.ai_thresholds import get_global_default
    ts = get_global_default()
    assert ts.source == "last_resort"
    # 폴백 값은 control_common 의 deprecated 상수와 동일 (역호환 보장)
    from agri_ai_core.src.control import control_common as cc
    assert ts.temp_low == cc.TEMP_LOW
    assert ts.temp_critical_high == cc.TEMP_CRITICAL_HIGH
    assert ts.water_temp_critical_low == cc.WATER_TEMP_CRITICAL_LOW
    assert ts.budding_temp_high == cc.BUDDING_TEMP_HIGH


def test_thresholds_db_row_direct_columns():
    """DB 비상/발이기 컬럼이 직접 사용됨 (자동 도출 아님)."""
    from agri_ai_core.src.control.ai_thresholds import _from_db_row
    row = {
        '저장일자': '2026-04-28',
        '온도최저': 27, '온도적정': 28.5, '온도최고': 30,
        '온도비상최저': 24, '온도비상최고': 34,
        '습도최저': 75, '습도적정': None, '습도최고': 85,
        '습도비상최저': 68, '습도비상최고': 96,
        'co2최저': 300, 'co2적정': None, 'co2최고': 1200,
        'co2비상최고': 1600,
        '수온최저': 40, '수온적정': None, '수온최고': 55,
        '수온비상최저': 33, '수온비상최고': 62,
        '발이기최저': 30, '발이기최고': 34,
    }
    ts = _from_db_row(row)
    assert ts is not None
    # DB 비상 컬럼이 그대로 반영 (자동 도출 아님)
    assert ts.temp_critical_low == 24
    assert ts.temp_critical_high == 34
    assert ts.humidity_critical_low == 68
    assert ts.humidity_critical_high == 96
    assert ts.co2_critical_high == 1600
    assert ts.water_temp_critical_low == 33
    assert ts.water_temp_critical_high == 62
    # 발이기도 DB 직접
    assert ts.budding_temp_low == 30
    assert ts.budding_temp_high == 34
    # 적정값 (otml)
    assert ts.temp_optimal == 28.5


def test_thresholds_partial_db_row_fallback():
    """필수 컬럼 결손이면 None → 호출자가 폴백."""
    from agri_ai_core.src.control.ai_thresholds import _from_db_row
    bad = {'온도최저': None, '온도최고': None}
    assert _from_db_row(bad) is None


# ──────────────────────────────────────────────────────────────────────────
# emergency guard 전체 skip — _check_emergency 가 운용모드
# 무관 항상 (False, None, None, False) 반환. 본 테스트는 그 *불변식* 을 잠금
# 한다. 만약 비상 가드 복귀를 결정하면:
#   1) environment_logic.py:275 early return 제거
#   2) 본 두 테스트의 expected 를 *과거 동작* (트립 시 True) 로 환원
#   3) 메모리 project_emergency_guard_disabled.md 갱신
# 참고: 정책 시행 이전 테스트 본문은 git blame 으로 복구 가능.
# ──────────────────────────────────────────────────────────────────────────
def test_check_emergency_critical_low_temp_triggers():
    """실내온도 < temp_critical_low(25) → emergency=True."""
    from agri_ai_core.src.control.environment_logic import _check_emergency
    from agri_ai_core.src.control.ai_thresholds import _from_db_row
    ts = _from_db_row({
        '온도최저': 27, '온도최고': 30,
        '습도최저': 75, '습도최고': 85,
        'co2최저': 300, 'co2최고': 1200,
        '수온최저': 40, '수온최고': 55,
    })
    # temp_critical_low 기본값=25.0, indoor_temperature=24 < 25 → 비상 발동
    sd = {'indoor_temperature': 24, 'indoor_humidity': 80, 'co2': 800, 'water_temperature': 42}
    is_em, dev, circ, wo = _check_emergency(sd, ts)
    assert is_em is True
    assert circ == '내부순환'
    assert wo is False


def test_check_emergency_normal_range_no_trigger():
    """모든 센서값이 정상 범위 → emergency=False."""
    from agri_ai_core.src.control.environment_logic import _check_emergency
    # 기본 폴백 임계값: temp_critical_low=25, temp_critical_high=33, co2_critical_high=1500
    # 수온 임계 기본값: water_temp_critical_low=35, water_temp_critical_high=60
    sd = {'indoor_temperature': 28, 'indoor_humidity': 80, 'co2': 1000, 'water_temperature': 45}
    is_em, dev, circ, wo = _check_emergency(sd, None)
    assert is_em is False
    assert dev is None
    assert circ is None
    assert wo is False


def test_house_prefix_format_dash():
    """'농장 N, 재배사 M' → 'N-M'"""
    from agri_ai_core.src.control.control_common import house_prefix
    assert house_prefix("[테스트]", 1, 2) == "[테스트] 1-2"
    assert house_prefix("", 0, 99) == "0-99"
    assert house_prefix("[테스트]") == "[테스트]"


# ════════════════════════════════════════════════════════════════════════════
# LLM 응답 정규화 — 다형 응답이 표준 스키마로 매핑되는지
# 실측 99호 로그에서 관찰된 5가지 형식을 모두 표준화 검증
# ════════════════════════════════════════════════════════════════════════════
def test_normalize_action_change_relay():
    from agri_ai_core.src.control.ai_control import _normalize_llm_response
    p = _normalize_llm_response({
        "action": "change_relay",
        "changes": {"수온히터": "ON", "포그생성": "OFF"},
        "reason": "수온 미달",
    })
    assert p["action"] == "change"
    assert p["devices"] == {"water_heater_flag": True, "fog_occurs_flag": False}


def test_normalize_action_adjust():
    from agri_ai_core.src.control.ai_control import _normalize_llm_response
    p = _normalize_llm_response({
        "action": "adjust",
        "adjustments": {"water_heater": "ON", "fog": False},
        "reason": "test",
    })
    assert p["action"] == "change"
    assert p["devices"]["water_heater_flag"] is True
    assert p["devices"]["fog_occurs_flag"] is False


def test_normalize_korean_top_level_keys():
    from agri_ai_core.src.control.ai_control import _normalize_llm_response
    p = _normalize_llm_response({
        "수온히터": "OFF", "포그생성": "OFF", "사유": "안정",
        "circulation": "내부순환",
    })
    assert p["devices"] == {"water_heater_flag": False, "fog_occurs_flag": False}
    assert p["reason"] == "안정"
    assert p["action"] == "change"  # devices 변경이 있으면 자동 추정


def test_normalize_target_state_form():
    from agri_ai_core.src.control.ai_control import _normalize_llm_response
    p = _normalize_llm_response({
        "action": "change", "target": "water_heater", "state": "OFF",
        "reason": "test",
    })
    assert p["devices"]["water_heater_flag"] is False
    assert "target" not in p and "state" not in p


def test_normalize_command_updates():
    from agri_ai_core.src.control.ai_control import _normalize_llm_response
    p = _normalize_llm_response({
        "command": "update",
        "updates": {"수온히터": True, "포그생성": False},
        "reason": "x",
    })
    assert p["action"] == "change"
    assert p["devices"]["water_heater_flag"] is True


def test_normalize_keep_action():
    from agri_ai_core.src.control.ai_control import _normalize_llm_response
    p = _normalize_llm_response({"action": "keep", "reason": "안정"})
    assert p["action"] == "keep"


def test_normalize_invalid_input():
    from agri_ai_core.src.control.ai_control import _normalize_llm_response
    assert _normalize_llm_response(None) is None
    assert _normalize_llm_response("not a dict") is None


def test_parse_relay_response_with_changed_relay_format():
    """기존 _parse_relay_response 가 정규화된 응답을 정상 처리"""
    from agri_ai_core.src.control.ai_control import _parse_relay_response
    response = (
        '{"action": "change_relay", "changes": {"수온히터": "ON", '
        '"포그생성": "OFF"}, "reason": "수온 미달", "circulation": "내부순환"}'
    )
    parsed = _parse_relay_response(response)
    assert parsed is not None
    assert parsed["action"] == "change"
    assert parsed["devices"]["water_heater_flag"] is True
    assert parsed["devices"]["fog_occurs_flag"] is False
    assert parsed["circulation"] == "내부순환"


def test_parse_relay_response_with_top_level_korean():
    from agri_ai_core.src.control.ai_control import _parse_relay_response
    response = '{"수온히터":"ON","포그생성":"OFF","사유":"가열","circulation":"내부순환"}'
    parsed = _parse_relay_response(response)
    assert parsed is not None
    assert parsed["action"] == "change"
    assert parsed["devices"]["water_heater_flag"] is True


# ════════════════════════════════════════════════════════════════════════════
# JSON Schema 강제 검증 (D)
# ════════════════════════════════════════════════════════════════════════════
def test_relay_response_schema_structure():
    from agri_ai_core.src.control.ai_control import RELAY_RESPONSE_SCHEMA
    assert RELAY_RESPONSE_SCHEMA["type"] == "object"
    assert "action" in RELAY_RESPONSE_SCHEMA["properties"]
    assert RELAY_RESPONSE_SCHEMA["properties"]["action"]["enum"] == ["change", "keep"]
    devices = RELAY_RESPONSE_SCHEMA["properties"]["devices"]
    assert "water_heater_flag" in devices["properties"]
    assert "fog_occurs_flag" in devices["properties"]
    circ = RELAY_RESPONSE_SCHEMA["properties"]["circulation"]
    assert set(circ["enum"]) == {"내부순환", "외부순환", "흡입순환", "배기순환", "순환정지"}


def test_ai_control_extended_token_limits():
    # num_predict 1500→400 default — 환경변수로 조정 가능.
    # 제어 응답은 실제 <200토큰이지만 최소 100 이상은 보장해야 함.
    from agri_ai_core.src.control import ai_control as ac
    assert ac.AI_CONTROL_NUM_PREDICT >= 100  # env var override 허용 (default=400)
    assert ac.AI_CONTROL_NUM_CTX     >= 8192
    assert ac.AI_CONTROL_TIMEOUT     >= 120


# ════════════════════════════════════════════════════════════════════════════
# 수온히터 정책 보정 코드 제거 — LLM 자율 판단 보존 검증
# 정상 환경(critical 미트립)에서는 LLM 의 heater=True 결정을 강제 OFF 하지 않음.
# critical 임계 안전 가드만 유지, 정상 범위 결정은 LLM 에 위임.
# ════════════════════════════════════════════════════════════════════════════
def test_validate_safety_heater_kept_when_indoor_normal(monkeypatch):
    """정상 환경에서도 LLM 의 heater=ON 결정을 그대로 보존 (정책 보정 미발동)."""
    from agri_ai_core.src.control import ai_control as ac
    # ts 모킹 — 99호 시나리오와 유사 (정상 20~25)
    class _TS:
        temp_low, temp_high = 20.0, 25.0
        temp_critical_low, temp_critical_high = 18.0, 28.0
        humidity_low, humidity_high = 30.0, 60.0
        humidity_critical_low, humidity_critical_high = 25.0, 70.0
        water_temp_low, water_temp_high = 25.0, 30.0
        water_temp_critical_low, water_temp_critical_high = 20.0, 35.0
        co2_critical_high = 1500.0
    monkeypatch.setattr(ac, 'get_thresholds', lambda f, h: _TS())

    parsed = {
        "action": "change",
        "reason": "수온 미달 가열",
        "devices": {"water_heater_flag": True, "fog_occurs_flag": False},
        "circulation": "내부순환",
    }
    sensor = {
        'indoor_temperature': 21.9,    # 정상 (20~25 안)
        'indoor_humidity': 39.7,       # 정상 (30~60 안)
        'co2': 480,
        'water_temperature': 22.4,     # 비상 미트립 (≥20)
        'outdoor_temperature': 8.0,    # 케이스 B(≥10℃) 미발동 범위
        'outdoor_humidity': 50,
    }
    out = ac._validate_safety(parsed, sensor, 0, 99, growth_stage='생육기')
    assert out is not None
    # 정상범위 가온 판단은 LLM 전담 — 코드가 heater 결정을 덮어쓰지 않는다.
    # (보정은 수온 과열 ≥ ABSOLUTE_WATER_HEATER_MAX_C, 히터·배수 동시 ON 두 경우뿐)
    assert out['devices']['water_heater_flag'] is True, \
        "정상 환경에서 LLM 의 heater=ON 결정 보존 (가온 필요성은 LLM 판단 영역)"


def test_validate_safety_heater_kept_when_indoor_low(monkeypatch):
    """실내 저온 시 LLM 의 heater=ON 결정 유지 (가드 미발동)."""
    from agri_ai_core.src.control import ai_control as ac
    class _TS:
        temp_low, temp_high = 20.0, 25.0
        temp_critical_low, temp_critical_high = 18.0, 28.0
        humidity_low, humidity_high = 30.0, 60.0
        humidity_critical_low, humidity_critical_high = 25.0, 70.0
        water_temp_low, water_temp_high = 25.0, 30.0
        water_temp_critical_low, water_temp_critical_high = 20.0, 35.0
        co2_critical_high = 1500.0
    monkeypatch.setattr(ac, 'get_thresholds', lambda f, h: _TS())

    parsed = {
        "action": "change", "reason": "저온 가열",
        "devices": {"water_heater_flag": True, "fog_occurs_flag": False},
        "circulation": "내부순환",
    }
    # 실내 저온 (정상범위 미만)
    sensor = {'indoor_temperature': 19.0, 'indoor_humidity': 40, 'co2': 480,
              'water_temperature': 22.4, 'outdoor_temperature': 8, 'outdoor_humidity': 50}
    out = ac._validate_safety(parsed, sensor, 0, 99, growth_stage='생육기')
    assert out['devices']['water_heater_flag'] is True, "저온이면 heater 유지"


def test_validate_safety_heater_kept_in_budding_stage(monkeypatch):
    """발이기 단계에서는 가드 발동 금지 (BUDDING_TEMP_LOW 미달 보호)."""
    from agri_ai_core.src.control import ai_control as ac
    class _TS:
        temp_low, temp_high = 20.0, 25.0
        temp_critical_low, temp_critical_high = 18.0, 28.0
        humidity_low, humidity_high = 30.0, 60.0
        humidity_critical_low, humidity_critical_high = 25.0, 70.0
        water_temp_low, water_temp_high = 25.0, 30.0
        water_temp_critical_low, water_temp_critical_high = 20.0, 35.0
        co2_critical_high = 1500.0
    monkeypatch.setattr(ac, 'get_thresholds', lambda f, h: _TS())

    parsed = {
        "action": "change", "reason": "발이기 가열",
        "devices": {"water_heater_flag": True, "fog_occurs_flag": False},
        "circulation": "내부순환",
    }
    sensor = {'indoor_temperature': 28.0, 'indoor_humidity': 40, 'co2': 480,
              'water_temperature': 22.4, 'outdoor_temperature': 8, 'outdoor_humidity': 50}
    out = ac._validate_safety(parsed, sensor, 0, 99, growth_stage='발이기')
    # 가온 필요성 판단은 생육단계 포함 컨텍스트를 아는 LLM 전담 — 코드 미개입.
    # (수온 22.4℃ 는 과열 임계 미만이므로 장비보호 보정도 미발동)
    assert out['devices']['water_heater_flag'] is True, \
        "발이기 가열 결정 보존 — 가온 판단은 LLM 자율 영역"


def test_step_logger_detail_method_exists():
    from agri_ai_core.src.control.ai_step_logger import AiStepLogger
    s = AiStepLogger("[테스트]", total=3)
    s.step("first")
    # detail 호출이 예외 없이 끝나야 함 (None/빈입력도 허용)
    s.detail()
    s.detail(None, "")
    s.detail("a single line")
    s.detail("multi\nline\nblock")
    s.detail("very long" * 200, max_chars=80)  # truncate 동작


# ════════════════════════════════════════════════════════════════════════════
# M1 ai_history_context — 빈 입력 안전
# ════════════════════════════════════════════════════════════════════════════
def test_history_context_empty_input():
    from agri_ai_core.src.control.ai_history_context import (
        format_recent_2month, format_year_ago,
    )
    assert format_recent_2month({}) == ""
    assert format_recent_2month({"sensor": {}}) == ""
    assert format_year_ago({}) == ""
    assert format_year_ago({"optimal": {}, "growth": {}}) == ""


# ════════════════════════════════════════════════════════════════════════════
# M2 ai_rag_context — 빈 결과 안전
# ════════════════════════════════════════════════════════════════════════════
def test_rag_context_empty():
    from agri_ai_core.src.control.ai_rag_context import format_rag_block
    assert format_rag_block([]) == ""
    out = format_rag_block([{"document": "doc", "metadata": {"category": "x"},
                            "distance": 0.123}])
    assert "1건" in out


# ════════════════════════════════════════════════════════════════════════════
# M7 ai_peer_compare — 빈 스냅샷
# ════════════════════════════════════════════════════════════════════════════
def test_peer_compare_format_empty():
    from agri_ai_core.src.control.ai_peer_compare import format_peer_block
    assert format_peer_block({}) == ""
    assert format_peer_block({"sensors": []}) == ""
    out = format_peer_block({
        "sensors": [{"hous_id": 1, "record_datetime": "2026-04-28 10:00:00",
                     "indoor_temp": 28, "indoor_humidity": 80, "co2": 800,
                     "water_temp": 42}],
        "relays": {1: {"relay_1st_flag": True}},
    })
    assert "재배사 1" in out


# ════════════════════════════════════════════════════════════════════════════
# M8 ai_harvest_context — 잔여일 / 없음 처리
# ════════════════════════════════════════════════════════════════════════════
def test_harvest_format_empty_and_advice():
    from agri_ai_core.src.control.ai_harvest_context import format_harvest_block
    assert format_harvest_block({}) == ""
    assert format_harvest_block({"days_remaining": None, "days_since_start": None}) == ""

    out_d3 = format_harvest_block({"days_remaining": 2, "days_since_start": 60,
                                    "crop_strt": "2026-02-27", "crop_end": "2026-04-30"})
    assert "D-2" in out_d3 and "D-3" in out_d3
    out_d10 = format_harvest_block({"days_remaining": 10, "days_since_start": 30,
                                     "crop_strt": "2026-03-29", "crop_end": "2026-05-08"})
    assert "D-10" in out_d10
    assert "수확 임박" not in out_d10


# ════════════════════════════════════════════════════════════════════════════
# M9 ai_anomaly_history — 빈 결과
# ════════════════════════════════════════════════════════════════════════════
def test_anomaly_format_empty():
    from agri_ai_core.src.control.ai_anomaly_history import format_anomaly_block
    assert format_anomaly_block([]) == ""
    out = format_anomaly_block([{
        "event_time": "2026-04-15 13:00:00", "pest_type": "푸른곰팡이",
        "pest_severity": "중", "memo": "x", "crop_lvel": "fruit",
        "avg_24h": {"avg_indoor_temp": 30.5, "avg_indoor_humidity": 90,
                    "avg_co2": 1200, "avg_water_temp": 45},
    }])
    assert "푸른곰팡이" in out


# ════════════════════════════════════════════════════════════════════════════
# M10 ai_weather_forecast — 키 미설정 시 빈 결과
# ════════════════════════════════════════════════════════════════════════════
def test_weather_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("KMA_API_KEY", raising=False)
    monkeypatch.delenv("FARM_NX_DEFAULT", raising=False)
    monkeypatch.delenv("FARM_NY_DEFAULT", raising=False)
    from agri_ai_core.src.control.ai_weather_forecast import get_forecast, format_forecast_block
    assert get_forecast(1, 1) == {}
    assert format_forecast_block({}) == ""


def test_weather_format_with_data():
    from agri_ai_core.src.control.ai_weather_forecast import format_forecast_block
    payload = {"forecast": [
        {"time": "20260428 1200", "TMP": "23", "REH": "60", "POP": "10",
         "PTY": "0", "WSD": "1.8", "SKY": "1"},
    ]}
    out = format_forecast_block(payload)
    assert "23℃" in out and "강수확률" in out


# ════════════════════════════════════════════════════════════════════════════
# M11 ai_camera_vision — 영상 소스 부재 시 안전
# ════════════════════════════════════════════════════════════════════════════
def test_camera_no_source_returns_empty(monkeypatch):
    for k in list(os.environ):
        if k.startswith("FARM_USB_CAM_") or k.startswith("FARM_RPI_CAM_URL_") or k.startswith("FARM_STATIC_IMG_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("FARM_USB_CAM_DEFAULT", raising=False)
    from agri_ai_core.src.control.ai_camera_vision import (
        capture_image, format_camera_block,
    )
    assert capture_image(1, 1) is None
    assert format_camera_block({}) == ""


# ════════════════════════════════════════════════════════════════════════════
# M12 ai_doc_rag — 빈 결과
# ════════════════════════════════════════════════════════════════════════════
def test_doc_rag_format_empty():
    from agri_ai_core.src.control.ai_doc_rag import format_doc_block
    assert format_doc_block([]) == ""


# ════════════════════════════════════════════════════════════════════════════
# M13 ai_yield_correlation — 빈 결과
# ════════════════════════════════════════════════════════════════════════════
def test_yield_format_empty():
    from agri_ai_core.src.control.ai_yield_correlation import format_yield_block
    assert format_yield_block([]) == ""


# ════════════════════════════════════════════════════════════════════════════
# M14 ai_forecast — 선형회귀 단위
# ════════════════════════════════════════════════════════════════════════════
def test_forecast_linear_predict_handles_constant():
    from agri_ai_core.src.control.ai_forecast import _linear_predict
    pts = [(0, 25), (60, 25), (120, 25), (180, 25), (240, 25)]
    pred = _linear_predict(pts, 300)
    assert pred is not None and abs(pred - 25.0) < 0.01


def test_forecast_format_empty():
    from agri_ai_core.src.control.ai_forecast import format_forecast_block
    assert format_forecast_block({}) == ""
    assert format_forecast_block({"metrics": {}}) == ""


# ════════════════════════════════════════════════════════════════════════════
# M15 ai_feedback — 라벨 검증
# ════════════════════════════════════════════════════════════════════════════
def test_feedback_invalid_label():
    from agri_ai_core.src.control.ai_feedback import submit_feedback
    res = submit_feedback(1, "neutral")
    assert res["success"] is False


# ════════════════════════════════════════════════════════════════════════════
# M16 ai_seasonality — 빈/부족
# ════════════════════════════════════════════════════════════════════════════
def test_seasonality_format_empty():
    from agri_ai_core.src.control.ai_seasonality import format_seasonality_block
    assert format_seasonality_block([]) == ""
    # 1년치만 있으면 비교 의미 없으므로 ""
    assert format_seasonality_block([{"yr": 2026, "avg_indoor_temp": 28}]) == ""


# ════════════════════════════════════════════════════════════════════════════
# M17 ai_power_usage — 빈 결과 + 정격 미설정 안전
# ════════════════════════════════════════════════════════════════════════════
def test_power_format_empty():
    from agri_ai_core.src.control.ai_power_usage import format_power_block
    assert format_power_block({}) == ""
    out = format_power_block({"sample_count": 100, "devices": [
        {"label": "수온히터", "hours": 5.2, "watt": None, "wh": None},
    ], "total_wh": None})
    assert "수온히터" in out and "5.2h" in out


# ════════════════════════════════════════════════════════════════════════════
# ai_control._build_user_prompt — 기존 시그니처 호환
# ════════════════════════════════════════════════════════════════════════════
def test_build_user_prompt_legacy_signature():
    from agri_ai_core.src.control import ai_control
    sensor = {'indoor_temperature': 28.5, 'indoor_humidity': 80, 'co2': 900,
              'outdoor_temperature': 22, 'outdoor_humidity': 65, 'water_temperature': 42}
    optimal = {'온도최저': 27, '온도최고': 30, '습도최저': 75, '습도최고': 85}

    # 6 위치인자 호출 (기존)
    out = ai_control._build_user_prompt(sensor, {}, '생육기', optimal, '', 1)
    assert '내부온도=28.5' in out

    # 신규 keyword 인자
    out2 = ai_control._build_user_prompt(
        sensor, {}, '생육기', optimal, '', 1,
        history_block='[H]', rag_block='[R]',
        extra_blocks=['[알고리즘 참조]', '', '[수확임박]'],
    )
    assert '[H]' in out2 and '[R]' in out2
    assert '[알고리즘 참조]' in out2 and '[수확임박]' in out2


# ════════════════════════════════════════════════════════════════════════════
# 신규 모듈 import 그래프 — 14단계 모두 import 가능
# ════════════════════════════════════════════════════════════════════════════
def test_all_new_modules_importable():
    import importlib
    names = [
        'agri_ai_core.src.control.ai_decision_log',
        'agri_ai_core.src.control.ai_peer_compare',
        'agri_ai_core.src.control.ai_harvest_context',
        'agri_ai_core.src.control.ai_anomaly_history',
        'agri_ai_core.src.control.ai_weather_forecast',
        'agri_ai_core.src.control.ai_camera_vision',
        'agri_ai_core.src.control.ai_doc_rag',
        'agri_ai_core.src.control.ai_yield_correlation',
        'agri_ai_core.src.control.ai_forecast',
        'agri_ai_core.src.control.ai_seasonality',
        'agri_ai_core.src.control.ai_power_usage',
        'agri_ai_core.src.control.ai_feedback',
        'agri_ai_core.api.ai_feedback_router',
    ]
    for n in names:
        m = importlib.import_module(n)
        assert m is not None
