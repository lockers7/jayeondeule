# ══════════════════════════════════════════════════════════════════════════════
# test_llm_autonomy_no_anchors — 제어 프롬프트에 python 판정 앵커가 없음을 보증
#
# 배경(2026-07-17 농장주 지시): LLM 100% 자율 원칙에 따라 앵커 2종을 제거했다.
#   ① [센서 평가 — 임계 비교 결과] : python 이 임계 비교 판정(정상/고온/트립순위)을
#      대신 내려 LLM 에 먹이던 57줄. "gemma3:27b 가 27.0 vs 28.0 을 헐겁게 본다"는
#      실측 보완책이었으나, LLM 이 추론 없이 결론만 받아 자율 판단이 훼손됐다.
#   ② [알고리즘 참조 결정] : python 64케이스 분기가 결정 전체를 계산해 제시.
#      LLM 이 알고리즘 결론에 끌려갔다.
#
#   ⛔ 알고리즘 본체(_determine_environment_action)는 제거 대상이 아니다.
#      manual_control 의 알고리즘 모드 · LLM 3회연속실패 폴백 · 비상 경로에서
#      그대로 살아있어야 한다. 앵커(프롬프트 주입)만 제거한 것이다.
#
# 판단 재료는 유지된다 — LLM 은 "현재 센서값"(원시값)과 "최적조건"(임계값)을
#   그대로 받아 직접 비교한다. 없어진 것은 python 이 내린 '판정'뿐이다.
#
# 파일 시작 함수 목록:
#   test_no_threshold_verdict_in_prompt : ⛔ 임계 비교 판정 문구 부재
#   test_no_algorithm_anchor_in_prompt  : ⛔ 알고리즘 참조 결정 앵커 부재
#   test_raw_material_still_present     : 센서값·최적조건은 유지 (판단 재료)
#   test_anchor_module_gone             : ai_algorithm_reference 모듈 제거됨
#   test_fallback_algorithm_preserved   : ⛔ 알고리즘 본체·폴백 경로 보존
# ══════════════════════════════════════════════════════════════════════════════
import importlib
import inspect
import os

import pytest

from agri_ai_core.src.control import ai_control

_SENSOR = {'indoor_temperature': 28.5, 'indoor_humidity': 100, 'co2': 1141,
           'outdoor_temperature': 22, 'outdoor_humidity': 65,
           'water_temperature': 24}
_OPTIMAL = {'온도최저': 27, '온도최고': 30, '습도최저': 75, '습도최고': 85,
            'co2최고': 1000, '수온최저': 20, '수온최고': 28}


def _prompt():
    return ai_control._build_user_prompt(
        _SENSOR, {}, '생육기', _OPTIMAL, '', 1, farm_id=1)


# ⛔ 회귀 방지: python 이 임계 비교 '판정'을 내려 프롬프트에 넣으면 안 된다.
def test_no_threshold_verdict_in_prompt():
    p = _prompt()
    for banned in ('센서 평가', '1순위 통과', '2순위 트립', '3순위 트립',
                   '→ 정상', '고농도', '고습'):
        assert banned not in p, f"python 임계 판정 '{banned}' 이 프롬프트에 재유입됨"


def _code_only(fn):
    # inspect.getsource 는 주석까지 준다. 제거 사유를 적은 ⛔ 주석이 함수명을
    # 언급하므로, 주석을 걷어내고 '실제 코드' 만 검사해야 한다.
    lines = []
    for ln in inspect.getsource(fn).split("\n"):
        head = ln.split("#", 1)[0]
        if head.strip():
            lines.append(head)
    return "\n".join(lines)


# ⛔ 회귀 방지: 알고리즘 결정을 앵커로 제시하면 LLM 이 그 결론에 끌려간다.
def test_no_algorithm_anchor_in_prompt():
    p = _prompt()
    assert '알고리즘 참조' not in p, "알고리즘 앵커가 프롬프트에 재유입됨"
    code = _code_only(ai_control.control_ai_environment)
    assert 'format_algorithm_reference' not in code, "앵커 포맷터 호출이 부활함"
    assert '_determine_environment_action' not in code, (
        "ai_control 이 알고리즘 결정을 다시 계산함 — 앵커 부활 경로")
    # extra_blocks 에 앵커 텍스트를 리터럴로 꽂아도 부활이다 — 호출명 검사만으로는
    # 못 잡으므로(돌연변이 검증으로 확인) 문자열 자체를 막는다.
    assert '알고리즘 참조' not in code, "앵커 텍스트가 소스에 리터럴로 재유입됨"


def test_raw_material_still_present():
    # 앵커는 없애되 LLM 이 스스로 비교할 재료는 반드시 남아야 한다
    p = _prompt()
    assert '28.5' in p and '100' in p and '1141' in p, "원시 센서값이 사라짐"
    assert '27' in p and '30' in p, "최적조건(임계값)이 사라짐"


def test_anchor_module_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module('agri_ai_core.src.control.ai_algorithm_reference')
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(ai_control.__file__))))
    path = os.path.join(root, 'src', 'control', 'ai_algorithm_reference.py')
    assert not os.path.exists(path), f"dead 모듈 파일이 남아있음: {path}"


# ⛔ 앵커 제거가 알고리즘 본체까지 지우면 폴백·비상 경로가 무너진다.
def test_fallback_algorithm_preserved():
    from agri_ai_core.src.control import manual_control
    assert hasattr(manual_control, '_determine_environment_action'), (
        "알고리즘 본체가 사라짐 — LLM 3회연속실패 폴백·비상 경로 붕괴")
    src = inspect.getsource(manual_control)
    assert src.count('_determine_environment_action(') >= 3, (
        "manual_control 의 알고리즘 호출부가 줄었음 — 폴백 경로 확인 필요")
