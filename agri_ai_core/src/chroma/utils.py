# ════════════════════════════════════════════
# ChromaDB 유틸리티: 메타데이터 변환, JSON 직렬화, 문서 ID 생성.
# ════════════════════════════════════════════
import json
import pandas as pd
from decimal import Decimal
from datetime import datetime

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import settings

logger = setup_logger(__name__)


# 임베딩 차원 반환
# ══════════════════
def _embedding_dim() -> int:
    return settings.embedding_dim


# JSON 직렬화를 위한 데이터 정리
# 값을 JSON 직렬화 가능한 형태로 변환
#
# Args:
#     value: 변환할 값
#
# Returns:
#     JSON 직렬화 가능한 값
# ══════════════════
def _sanitize_for_json(value):
    if isinstance(value, Decimal):
        return int(value) if value == int(value) else float(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, dict):
        return {k: _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_json(v) for v in value]
    return value


# 메타데이터를 ChromaDB 호환 형식으로 변환
# 메타데이터를 ChromaDB 호환 형식으로 변환
# 문자열, 숫자, 불린값은 그대로 유지
# 복잡한 객체(dict, list 등)는 JSON 문자열로 직렬화
#
# Args:
#     metadata: 원본 메타데이터
#
# Returns:
#     dict: ChromaDB 호환 메타데이터
# ═══════════════════════════
def prepare_metadata_for_chroma(metadata: dict) -> dict:
    if not isinstance(metadata, dict):
        return {}

    clean_metadata = {}

    for key, value in metadata.items():
        if value is None:
            continue

        if isinstance(value, (str, int, float, bool, Decimal)):
            clean_metadata[key] = value if not isinstance(value, Decimal) else _sanitize_for_json(value)
        else:
            try:
                sanitized = _sanitize_for_json(value)
                if isinstance(sanitized, (dict, list, tuple, set)):
                    clean_metadata[key] = json.dumps(sanitized, ensure_ascii=False)
                    clean_metadata[f"{key}_is_json"] = True
                else:
                    clean_metadata[key] = sanitized
                    if isinstance(value, (dict, list, tuple, set)):
                        clean_metadata[f"{key}_is_json"] = True
            except Exception as e:
                logger.warning(f"메타데이터 '{key}' 직렬화 실패: {e}")
                clean_metadata[key] = str(value)

    return clean_metadata


# 메타데이터 정리 (prepare_metadata_for_chroma 별칭)
# ═════════════════════════════════════════
def clean_metadata(metadata: dict) -> dict:
    return prepare_metadata_for_chroma(metadata)


# ChromaDB에서 조회한 metadata를 원래 형태로 복원
# ChromaDB에서 조회한 메타데이터를 원래 형태로 복원
#
# Args:
#     metadata: ChromaDB 메타데이터
#
# Returns:
#     dict: 복원된 메타데이터
# ═══════════════════
def restore_metadata_from_chroma(metadata: dict) -> dict:
    if not isinstance(metadata, dict):
        return {}

    json_flags = {key[:-8] for key, value in metadata.items()
                  if key.endswith('_is_json') and value is True}

    restored_metadata = {}
    for key, value in metadata.items():
        if key.endswith('_is_json'):
            continue
        if key in json_flags:
            try:
                restored_metadata[key] = json.loads(value)
            except Exception as e:
                logger.warning(f"메타데이터 '{key}' 역직렬화 실패: {e}")
                restored_metadata[key] = value
        else:
            restored_metadata[key] = value

    return restored_metadata


# 문서 ID 생성기
# 문서 ID 생성
#
# Args:
#     kind: 문서 종류 (farm, units, crops, stats, optimal, settings, learned, document, last)
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#     timestamp: 타임스탬프
#
# Returns:
#     str: 생성된 문서 ID
# ══════════════════
def generate_doc_id(kind=None, farm_id=None, house_id=None, timestamp=None):
    try:
        if timestamp is None:
            dt = datetime.now()
        elif isinstance(timestamp, (datetime, pd.Timestamp)):
            dt = timestamp if isinstance(timestamp, datetime) else timestamp.to_pydatetime()
        elif isinstance(timestamp, str):
            try:
                dt = pd.to_datetime(timestamp).to_pydatetime()
            except Exception:
                dt = datetime.now()
        else:
            dt = datetime.now()

        # kind별 시간 버킷팅
        if kind == "units":
            # 3분 단위로 버킷팅
            dt = dt.replace(second=0, microsecond=0)
            minute = (dt.minute // 3) * 3
            dt = dt.replace(minute=minute)
        elif kind in ["stats", "optimal", "learned"]:
            # 10분 단위로 버킷팅
            dt = dt.replace(second=0, microsecond=0)
            minute = (dt.minute // 10) * 10
            dt = dt.replace(minute=minute)
        else:
            # 초 단위로 버킷팅
            dt = dt.replace(microsecond=0)

        ts = dt.strftime("%Y%m%d%H%M%S")

        # ID 생성
        if kind and farm_id is not None and house_id is not None:
            doc_id = f"{kind}_{farm_id}_{house_id}_{ts}"
        elif kind and farm_id is not None:
            doc_id = f"{kind}_{farm_id}_{ts}"
        elif kind:
            doc_id = f"{kind}_{ts}"
        else:
            doc_id = ts

        return doc_id

    except Exception as e:
        logger.error(f"문서 ID 생성 중 오류: {e}")
        return datetime.now().strftime("%Y%m%d%H%M%S")


__all__ = [
    "_embedding_dim",
    "_sanitize_for_json",
    "prepare_metadata_for_chroma",
    "clean_metadata",
    "restore_metadata_from_chroma",
    "generate_doc_id",
]
