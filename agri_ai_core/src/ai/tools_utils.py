# ════════════════════════════════════════════════════════════════
# 도구 실행 공용 유틸 — tools_executor.py에서 분리된 pure helper
# ID 정규화, JSON 직렬화 fallback, AI vs 사용자 상태 충돌 비교 등.
# --->
# normalize_id: LLM이 준 ID 문자열에서 순수 숫자만 추출
# json_default: Decimal/datetime 등 json.dumps 미지원 타입 변환
# build_ai_conflict: AI 권장 릴레이 vs 사용자 수동 설정 차이 비교
# parse_positive_int: 양의 정수 파싱 (실패 시 default)
# parse_positive_float: 양의 실수 파싱 (실패 시 default)
# parse_optional_int: 빈 값/None 허용 정수 파싱
# to_chroma_where: 다중 키 dict → ChromaDB $and 형식 변환
# ════════════════════════════════════════════════════════════════
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional


def normalize_id(value: Any) -> Optional[str]:
    """LLM이 전달한 ID에서 숫자만 추출. 숫자가 없으면 None.
    예: '자연들에 농장' → None, '1' → '1', '상황버섯1호재배사' → '1'
    """
    if value is None:
        return None
    s = str(value).strip()
    # 이미 순수 숫자면 그대로
    try:
        int(s)
        return s
    except (ValueError, TypeError):
        pass
    # 한글 등이 섞여 있으면 첫 숫자만 추출
    digits = re.findall(r'\d+', s)
    return digits[0] if digits else None


def json_default(value: Any) -> Any:
    """json.dumps의 default 인자로 사용. Decimal/datetime 타입 변환."""
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return str(value)
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def build_ai_conflict(ai_judgment: Optional[Dict[str, Any]],
                      user_relay_settings: Optional[Dict[str, Any]]) -> Optional[List[str]]:
    """AI 권장 릴레이 상태와 사용자 수동 제어의 차이점을 한국어 문자열 리스트로 반환.
    차이 없거나 입력 부족 시 None 반환.
    """
    if not ai_judgment or not user_relay_settings:
        return None
    ai_devices = ai_judgment.get("devices") or {}
    if not ai_devices:
        return None

    from agri_ai_core.src.control.control_common import SEMANTIC_LABELS
    conflicts = []
    for device_name, user_value in user_relay_settings.items():
        if device_name in ai_devices:
            ai_value = ai_devices[device_name]
            if bool(user_value) != bool(ai_value):
                label = SEMANTIC_LABELS.get(device_name, device_name)
                user_str = "ON" if user_value else "OFF"
                ai_str = "ON" if ai_value else "OFF"
                conflicts.append(f"{label}: 수동={user_str}, AI권장={ai_str}")

    return conflicts or None


def parse_positive_int(value: Any, default: int) -> int:
    """양의 정수 파싱. 실패하거나 0 이하면 default 반환."""
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (ValueError, TypeError):
        return default


def parse_positive_float(value: Any, default: float) -> float:
    """양의 실수 파싱. 실패하거나 0 이하면 default 반환."""
    try:
        parsed = float(value)
        return parsed if parsed > 0 else default
    except (ValueError, TypeError):
        return default


def parse_optional_int(value: Any) -> Optional[int]:
    """빈 값/None 허용 정수 파싱. 실패/빈값 시 None."""
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except (ValueError, TypeError):
        return None


def to_chroma_where(where_dict: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """다중 키 where 딕셔너리를 ChromaDB $and 형식으로 변환."""
    if not where_dict:
        return None
    if len(where_dict) == 1:
        k, v = next(iter(where_dict.items()))
        return {k: {"$eq": v}} if not isinstance(v, dict) else where_dict
    conditions = []
    for k, v in where_dict.items():
        if isinstance(v, dict):
            conditions.append({k: v})
        else:
            conditions.append({k: {"$eq": v}})
    return {"$and": conditions}
