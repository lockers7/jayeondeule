# ══════════════════════════════════════════════════════════════════════════════
# test_kis_order_block — KIS 실주문 차단(도구명 + 인자 기반 우회) 하드닝 단위테스트
#   농장주 지시: 시세·재무 조회 전용, 실주문 원천 차단(자격증명 무관, 코드 게이트).
# ══════════════════════════════════════════════════════════════════════════════
import os
from agri_ai_core.src.ai.tools_mcp_gateway import _deny_reason


def test_block_order_by_toolname():
    os.environ.pop("KIS_ALLOW_ORDER", None)
    assert _deny_reason("kis-trading", "order_cash", {}) is not None
    assert _deny_reason("kis-trading", "domestic_stock_buy", {}) is not None


def test_block_order_by_arg_apitype():
    # 범용 도구명 + api_type=order_cash 우회 시도 → 차단되어야 함
    assert _deny_reason("kis-trading", "domestic_stock", {"api_type": "order_cash"}) is not None
    assert _deny_reason("kis-trading", "domestic_stock", {"api_type": "order_credit"}) is not None
    assert _deny_reason("kis", "trade", {"tr_id": "TTTC0802U", "side": "매수"}) is not None


def test_allow_inquiry():
    # 조회는 허용(주문가능조회 inquire_psbl_order 오탐 방지 포함)
    assert _deny_reason("kis-trading", "inquire_price", {"code": "005930"}) is None
    assert _deny_reason("kis-trading", "domestic_stock", {"api_type": "inquire_psbl_order"}) is None
    assert _deny_reason("kis-trading", "inquire_balance", {}) is None


def test_non_kis_unaffected():
    # KIS 아닌 서버는 이 규칙 영향 없음
    assert _deny_reason("filesystem", "read_file", {"path": "/workspace/x"}) is None


def test_env_override_opens_order():
    # KIS_ALLOW_ORDER=1 이면 개방(관리자 명시적 해제 경로 존재)
    os.environ["KIS_ALLOW_ORDER"] = "1"
    try:
        assert _deny_reason("kis-trading", "order_cash", {}) is None
    finally:
        os.environ.pop("KIS_ALLOW_ORDER", None)
