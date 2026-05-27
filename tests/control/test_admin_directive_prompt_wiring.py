# ══════════════════════════════════════════════════════════════════════════════
# test_admin_directive_prompt_wiring — 관리자 강제지시가 LLM 프롬프트에 실제 도달하는지
#
# 배경(2026-07-17 실측): _build_user_prompt 는 farm_id 파라미터가 없는데 본문
#   966행이 format_prompt_block(farm_id, house_id) 를 호출 → 매 사이클 NameError.
#   그 예외를 `except Exception: pass` 가 조용히 삼켜, 관리자 강제지시가 제어 LLM
#   프롬프트에 단 한 번도 주입된 적이 없었다.
#   relay_manager 하드강제는 살아 있어 농장은 안전했으나, LLM 은 지시를 모른 채
#   결정하고 최종 관문에서 뒤집히므로 결정·사유·실제동작이 계속 어긋났다.
#
#   format_prompt_block 자체의 단위테스트(test_admin_directive.py:55)는 있었다.
#   공백은 "배선" — 블록이 프롬프트까지 도달하는지 아무도 검증하지 않았다.
#
# 파일 시작 함수 목록:
#   test_build_user_prompt_accepts_farm_id : 시그니처에 farm_id 존재 (NameError 원인)
#   test_directive_block_reaches_prompt    : 활성 지시 → 프롬프트 본문에 주입
#   test_system_farm_zero_not_dropped      : ⛔ farm_id=0(시스템농장) 탈락 금지
#   test_farm_id_none_is_safe              : farm_id 미지정 → 예외 없이 생략
#   test_no_directive_no_block             : 활성 지시 없으면 아무것도 안 붙음
#   test_caller_passes_farm_id             : control_ai_environment 가 실제로 전달
# ══════════════════════════════════════════════════════════════════════════════
import inspect
from unittest.mock import patch

from agri_ai_core.src.control import admin_directive, ai_control

_SENSOR = {'indoor_temperature': 28.5, 'indoor_humidity': 80, 'co2': 900,
           'outdoor_temperature': 22, 'outdoor_humidity': 65,
           'water_temperature': 42}
_OPTIMAL = {'온도최저': 27, '온도최고': 30, '습도최저': 75, '습도최고': 85}

_FAKE_DIRECTIVE = {
    "배출팬": {"forced_value": True, "note": "곰팡이 억제",
               "created_by": "admin", "created_at": "2026-07-17 10:00"},
}


def _build(farm_id=None):
    return ai_control._build_user_prompt(
        _SENSOR, {}, '생육기', _OPTIMAL, '', 1, farm_id=farm_id)


# ⛔ 회귀 방지: farm_id 가 시그니처에서 빠지면 966행이 다시 NameError 를 낸다.
def test_build_user_prompt_accepts_farm_id():
    params = inspect.signature(ai_control._build_user_prompt).parameters
    assert 'farm_id' in params, (
        "farm_id 파라미터 없음 — format_prompt_block(farm_id, ...) 가 NameError")
    # 기존 6 위치인자 호출자를 깨지 않도록 keyword+기본값이어야 한다
    assert params['farm_id'].default is None


def test_directive_block_reaches_prompt():
    with patch.object(admin_directive, 'get_active', return_value=_FAKE_DIRECTIVE):
        out = _build(farm_id=1)
    assert '관리자 강제 지시' in out, "활성 지시가 프롬프트에 주입되지 않음"
    assert '배출팬' in out and 'ON' in out


# ⛔ 회귀 방지: 시스템농장은 farm_id=0 이다. `if farm_id:` 로 검사하면 0 이 falsy 라
#    시스템농장 지시만 조용히 사라진다 — 반드시 `is not None` 으로 검사할 것.
def test_system_farm_zero_not_dropped():
    with patch.object(admin_directive, 'get_active', return_value=_FAKE_DIRECTIVE):
        out = _build(farm_id=0)
    assert '관리자 강제 지시' in out, "farm_id=0(시스템농장) 지시가 탈락함"


def test_farm_id_none_is_safe():
    # 구 호출자(farm_id 미전달)도 예외 없이 동작하고, 지시 블록만 생략된다
    with patch.object(admin_directive, 'get_active', return_value=_FAKE_DIRECTIVE):
        out = _build(farm_id=None)
    assert '관리자 강제 지시' not in out
    assert '내부온도=28.5' in out          # 프롬프트 본체는 정상 생성


def test_no_directive_no_block():
    with patch.object(admin_directive, 'get_active', return_value={}):
        out = _build(farm_id=1)
    assert '관리자 강제 지시' not in out


# 시그니처만 맞고 호출부가 안 넘기면 여전히 dead path — 실제 전달을 소스로 확인.
# (control_ai_environment 는 DB/LLM 의존이라 단위 호출이 불가능해 소스 검증)
def test_caller_passes_farm_id():
    src = inspect.getsource(ai_control.control_ai_environment)
    assert '_build_user_prompt(' in src, "호출부를 찾지 못함 — 테스트 갱신 필요"
    call = src[src.index('_build_user_prompt('):]
    call = call[:call.index(')')]
    assert 'farm_id=farm_id' in call, (
        "control_ai_environment 가 farm_id 를 전달하지 않음 — 지시 블록이 다시 죽는다")
