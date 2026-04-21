# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 알고리즘 결정값 참조 모듈 (M5)
# [2026-04-28 신규] 동일 센서값에 대해 알고리즘 모드가 어떤 결정을 했을지 미리
# 계산해 LLM 에 reference 로 제공. LLM 이 알고리즘과 크게 다른 결정을 할 때
# 사유를 제시하도록 유도 → oscillation·일탈 억제.
#
# 호출 룰 (반드시 준수):
#   • 본 모듈은 control_ai_environment 에서만 import.
#   • 동급 control 모듈(manual_control / environment_logic) 직접 import 금지 —
#     호출자(ai_control)가 manual_control._determine_environment_action 결과를
#     이미 보유하므로, 본 모듈은 그 dict 를 인자로만 받음 (순수 포맷터).
# --->
# format_algorithm_reference: dict → user prompt 한 줄 텍스트
# ══════════════════════════════════════════════════════════════════════════════
from typing import Any, Dict, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# 알고리즘이 같은 센서값에 대해 내릴 결정을 LLM 참조용 텍스트로 변환.
# action 이 None/빈값이면 "" 반환 — 호출 측이 섹션 생략.
# ────────────────────────────────────────────────────────────────────
def format_algorithm_reference(action: Optional[Dict[str, Any]]) -> str:
    if not action or not isinstance(action, dict):
        logger.info("[AI알고리즘참조] action 없음 — 참조 블록 생략")
        return ""

    devices = action.get("devices") or {}
    circ = action.get("circulation") or "(미지정)"
    reason = action.get("reason") or ""
    is_emerg = bool(action.get("is_emergency"))
    water_only = bool(action.get("water_temp_only"))

    heater = "ON" if devices.get("water_heater_flag") else "OFF"
    fog = "ON" if devices.get("fog_occurs_flag") else "OFF"

    tag = "비상" if is_emerg else ("수온비상" if water_only else "일반")
    text = (
        f"[알고리즘 참조 결정] {tag} · 사유={reason} · 순환={circ} · "
        f"수온히터={heater} · 포그={fog}"
        f" — 큰 차이로 다른 결정을 할 경우 reason 에 근거를 명시할 것."
    )
    logger.info(f"[AI알고리즘참조] {tag} · {circ} · 히터={heater} 포그={fog} · {reason[:30]}")
    return text
