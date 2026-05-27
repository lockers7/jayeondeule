# ══════════════════════════════════════════════════════════════════════════════
# test_atm_stagnation_v5 — 대기정체지수 V5 엔드포인트 회귀 가드
#
# data.go.kr 활용신청(생활기상지수 조회서비스 3.0)의 승인 엔드포인트는
# LivingWthrIdxServiceV5. V4 로 되돌아가면 403 Forbidden 재발.
#
# 파일 시작 함수 목록:
#   test_default_url_is_v5 : 기본 URL V5 + https 유지
# ══════════════════════════════════════════════════════════════════════════════


def test_default_url_is_v5():
    from agri_ai_core.src.control.ai_atm_stagnation import _DEFAULT_URL
    assert "LivingWthrIdxServiceV5/getAirDiffusionIdxV5" in _DEFAULT_URL
    assert _DEFAULT_URL.startswith("https://")
