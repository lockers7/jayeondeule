# ══════════════════════════════════════════════════════════════════════════════
# LLM 제어 도구 권한/안전 검증 모듈 (L5 계층, 동급 tools_*.py 와 상호 호출 금지).
# 관리 도구·제어 도구에서 공통으로 쓰이는 가드(0호 제외, 농장 접근권 검증)를 모아둔다.
# --->
# require_non_zero_house:   통합재배사(0호) 제어 거부 가드 (하드웨어 미존재)
# check_farm_access:        요청 farm_id 가 auth_farm_id 권한 내인지 검증
# check_house_control_access: 위 두 가드를 합친 관리/제어 도구 공통 진입 검증
# ══════════════════════════════════════════════════════════════════════════════
from typing import Any, Dict, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.tools_utils import normalize_id as _normalize_id

logger = setup_logger(__name__)


# ═════════════════════════════════════════════════
# 0호(통합/공통 재배사) 제어 거부 — 물리 장치 없음
# ═════════════════════════════════════════════════
def require_non_zero_house(house_id: Any) -> Optional[Dict[str, Any]]:
    hid = str(house_id or "").strip().lower()
    if not hid:
        return {"success": False, "error": "house_id 가 지정되지 않았습니다. 구체적 재배사 번호 또는 'all' 을 사용하세요."}
    if hid in ("0", "통합", "통합재배사", "공통", "공통재배사"):
        return {
            "success": False,
            "error": "house_id='0'(통합/공통 재배사)은 제어 대상이 아닙니다. "
                     "이전 대화 맥락의 구체적 재배사 번호(예: '1','2','3') 또는 'all' 을 사용하세요.",
        }
    return None


# ═════════════════════════════════════════════════
# 농장 접근권 검증 — 농장관리자는 자기 농장만, 시스템관리자는 전체
# ═════════════════════════════════════════════════
def check_farm_access(auth_farm_id: Any, target_farm_id: Any) -> Optional[Dict[str, Any]]:
    auth_norm = _normalize_id(auth_farm_id)
    target_norm = _normalize_id(target_farm_id)

    # 시스템관리자: auth_farm_id 가 미지정 또는 '0' → 전체 허용
    if not auth_norm or auth_norm == "0":
        return None

    # 농장관리자: target_farm_id 가 자기 농장이 아니면 거부
    if target_norm and target_norm != "0" and target_norm != auth_norm:
        logger.warning(
            f"[권한거부] auth_farm_id={auth_norm} 가 farm_id={target_norm} 제어 시도"
        )
        return {
            "success": False,
            "error": f"농장 접근 권한 없음: 본인 소속 농장(farm_id={auth_norm})만 조작 가능합니다. "
                     f"요청한 farm_id={target_norm}은 권한 범위 밖입니다.",
        }
    return None


# ═════════════════════════════════════════════════
# 관리·제어 도구 공통 진입 가드
# ═════════════════════════════════════════════════
def check_house_control_access(
    auth_farm_id: Any,
    target_farm_id: Any,
    target_house_id: Any,
    allow_all: bool = True,
) -> Optional[Dict[str, Any]]:
    hid = str(target_house_id or "").strip().lower()
    # 'all' 은 기본 허용, allow_all=False 이면 거부
    if hid in ("all", "전체", "모든", "모든재배사", "전재배사", "전체재배사", "모두"):
        if not allow_all:
            return {
                "success": False,
                "error": "이 도구는 특정 재배사만 지원합니다. 'all' 대신 구체적 재배사 번호를 사용하세요.",
            }
    else:
        # 0호 거부
        zero_err = require_non_zero_house(target_house_id)
        if zero_err:
            return zero_err

    # 농장 접근권
    farm_err = check_farm_access(auth_farm_id, target_farm_id)
    if farm_err:
        return farm_err
    return None
