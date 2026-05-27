# ══════════════════════════════════════════════════════════════════════════════
# 제어 프롬프트 필수 내용 가드 — 단순화 과정에서 안전·핵심 요소가 사라지지 않게.
# LLM 없이 조립된 프롬프트 텍스트만 검사(빠름). 매 프롬프트 변경 시 실행.
# ══════════════════════════════════════════════════════════════════════════════
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path: sys.path.insert(0, ROOT)
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, ".env"))
import pytest
from agri_ai_core.src.control.ai_control import _build_system_prompt, _build_user_prompt
from agri_ai_core.src.control.ai_thresholds import get_thresholds


def _sys(growth="생육기"):
    return _build_system_prompt(growth, get_thresholds(1, 1))


def test_system_prompt_has_absolute_safety():
    # 절대 안전(수온히터↔배수 상호배타)은 어떤 단순화에도 반드시 생존
    sp = _sys()
    assert "water_heater" in sp or "수온히터" in sp
    assert "drainage" in sp or "배수" in sp
    assert "상호배타" in sp or "동시" in sp  # 동시 ON 금지 개념


def test_system_prompt_has_circulation_modes():
    sp = _sys()
    for mode in ("내부순환", "외부순환", "배기순환"):
        assert mode in sp, f"순환모드 {mode} 누락"


def test_system_prompt_has_output_schema():
    sp = _sys()
    assert "action" in sp and "keep" in sp and "change" in sp
    assert "JSON" in sp or "json" in sp


def test_system_prompt_growth_variants_build():
    for g in ("발이기", "생육기", "수확기"):
        sp = _build_system_prompt(g, get_thresholds(1, 1))
        assert len(sp) > 500, f"{g} 시스템 프롬프트 비정상"


def test_user_prompt_has_sensor_and_relay():
    sd = {'indoor_temperature': 25, 'indoor_humidity': 80, 'co2': 900,
          'outdoor_temperature': 22, 'outdoor_humidity': 70, 'water_temperature': 20}
    up = _build_user_prompt(sd, {}, "생육기", {}, "", 1,
                            history_block="", rag_block="", extra_blocks=[], farm_id=1)
    assert "현재 센서값" in up
    assert "25" in up  # 실제 센서값 주입
    assert "릴레이" in up
