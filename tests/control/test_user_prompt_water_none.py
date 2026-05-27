# ══════════════════════════════════════════════════════════════════════════════
# test_user_prompt_water_none — 수온 None 프롬프트 표기 단위 테스트
#
# 대상: agri_ai_core/src/control/ai_control.py :: _build_user_prompt
#   · 수온센서 결함필터(reader.py)가 None 처리 시 "수온=None℃" 노출 금지
#   · "측정불가(수온센서 장애)" 명시 + 판단 근거 안내 문구 포함
#   · 수온 정상값은 기존과 동일 표기 (회귀 방지)
#
# 파일 시작 함수 목록:
#   test_water_none_no_none_text   : None℃ 미노출 + 측정불가 표기
#   test_water_none_guidance_line  : 판단 근거 안내 문구 포함
#   test_water_normal_unchanged    : 정상값 기존 표기 유지
# ══════════════════════════════════════════════════════════════════════════════
import pytest

from agri_ai_core.src.control.ai_control import _build_user_prompt


def _sensor(water):
    return {
        'indoor_temperature': 25.5, 'indoor_humidity': 80.0, 'co2': 900,
        'outdoor_temperature': 28.0, 'outdoor_humidity': 60.0,
        'water_temperature': water,
    }


def test_water_none_no_none_text():
    prompt = _build_user_prompt(_sensor(None), {}, '생육기', {}, '', 1)
    assert "수온=None" not in prompt
    assert "수온=측정불가(센서장애)" in prompt


def test_water_none_guidance_line():
    prompt = _build_user_prompt(_sensor(None), {}, '생육기', {}, '', 1)
    assert "수온 센서 장애" in prompt
    assert "실내온도" in prompt  # 판단 근거 안내


def test_water_normal_unchanged():
    prompt = _build_user_prompt(_sensor(20.5), {}, '생육기', {}, '', 1)
    assert "수온=20.5℃" in prompt
    assert "측정불가" not in prompt
    assert "수온 센서 장애" not in prompt
