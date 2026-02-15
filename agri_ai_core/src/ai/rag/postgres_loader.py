# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# RAG 적재 모듈
# PostgreSQL에서 농장 데이터를 직접 읽어 ChromaDB(source_collection)에 저장합니다.
# (기존 JSON 중간 파일 의존 제거)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import traceback
from typing import Any, Dict, List

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.chroma.client import heartbeat
from agri_ai_core.src.ai.rag.data_processor import process_unit_data, process_crop_data
from agri_ai_core.src.postgresql.reader import (
    read_farm_house_list,
    read_units_data,
    read_crops_data,
)

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Crops 행 키 정규화
# DB 쿼리 별칭과 process_crop_data 기대 키를 맞춥니다.
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _normalize_crop_row(crop: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(crop)

    # data kind / datetime
    normalized.setdefault("장치데이터", crop.get("작물데이터", "crops"))
    normalized.setdefault("기록일시", crop.get("기록일시", ""))

    # 기간/상태
    normalized.setdefault("작물시작일자", crop.get("재배시작일", ""))
    normalized.setdefault("작물종료일자", crop.get("재배종료일", ""))
    normalized.setdefault("생육상태", crop.get("생육상태", ""))

    # 수확량/가격
    normalized.setdefault("총수확량", crop.get("총수확량", 0))
    normalized.setdefault("1등급수확량", crop.get("등급1", 0))
    normalized.setdefault("2등급수확량", crop.get("등급2", 0))
    normalized.setdefault("3등급수확량", crop.get("등급3", 0))
    normalized.setdefault("4등급수확량", crop.get("등급4", 0))
    normalized.setdefault("5등급수확량", crop.get("등급5", 0))

    normalized.setdefault("1등급가격", crop.get("등급1판매가격", 0))
    normalized.setdefault("2등급가격", crop.get("등급2판매가격", 0))
    normalized.setdefault("3등급가격", crop.get("등급3판매가격", 0))
    normalized.setdefault("4등급가격", crop.get("등급4판매가격", 0))
    normalized.setdefault("5등급가격", crop.get("등급5판매가격", 0))

    normalized.setdefault("알림", crop.get("생육시기타사항", ""))

    return normalized


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# PostgreSQL에서 직접 학습 원천 데이터 조회
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def fetch_data_from_postgresql(limit: int = 100000) -> List[Dict[str, Any]]:
    try:
        farm_houses = read_farm_house_list()
        if not farm_houses:
            logger.warning("PostgreSQL에서 농장/재배사 목록을 찾지 못했습니다.")
            return []

        datas: List[Dict[str, Any]] = []
        total_units = 0
        total_crops = 0

        max_rows = limit if isinstance(limit, int) and limit > 0 else None

        for farm_house in farm_houses:
            farm_id = farm_house.get("farm_id")
            house_id = farm_house.get("hous_id")
            if farm_id is None or house_id is None:
                continue

            units = read_units_data(farm_id, house_id) or []
            crops_raw = read_crops_data(farm_id, house_id) or []
            crops = [_normalize_crop_row(crop) for crop in crops_raw]

            if max_rows is not None:
                used = total_units + total_crops
                remain = max_rows - used
                if remain <= 0:
                    break

                if len(units) >= remain:
                    units = units[:remain]
                    crops = []
                elif len(units) + len(crops) > remain:
                    crops = crops[: remain - len(units)]

            if not units and not crops:
                continue

            datas.append(
                {
                    "farm_id": str(farm_id),
                    "house_id": str(house_id),
                    "units": units,
                    "crops": crops,
                }
            )

            total_units += len(units)
            total_crops += len(crops)

            if max_rows is not None and (total_units + total_crops) >= max_rows:
                break

        logger.debug(
            "PostgreSQL 데이터 조회 완료 -> 농장/재배사: %d건, 장치: %d건, 생육: %d건",
            len(datas),
            total_units,
            total_crops,
        )
        return datas

    except Exception as e:
        logger.error(f"PostgreSQL 데이터 조회 중 오류: {e}")
        logger.error(traceback.format_exc())
        return []


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# PostgreSQL 데이터를 Vector DB(source_collection)로 적재
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def sync_postgresql_to_vcdb(data_limit: int = 100000) -> bool:
    try:
        status = heartbeat()
        if "error" in status:
            logger.error(f"ChromaDB REST API 연결 실패: {status.get('error')}")
            return False

        datas = fetch_data_from_postgresql(limit=data_limit)
        if not datas:
            logger.debug("적재할 PostgreSQL 데이터가 없습니다.")
            return False

        total_unit_success = 0
        total_unit_failure = 0
        total_crop_success = 0
        total_crop_failure = 0

        for item in datas:
            if item.get("units"):
                unit_success, unit_failure = process_unit_data(item)
                total_unit_success += unit_success
                total_unit_failure += unit_failure

            if item.get("crops"):
                crop_success, crop_failure = process_crop_data(item)
                total_crop_success += crop_success
                total_crop_failure += crop_failure

        total_success = total_unit_success + total_crop_success
        total_failure = total_unit_failure + total_crop_failure

        logger.debug(
            "PostgreSQL -> Chroma 적재 완료: 성공 %d건 (units=%d, crops=%d), 실패 %d건",
            total_success,
            total_unit_success,
            total_crop_success,
            total_failure,
        )

        if total_success == 0:
            logger.warning("적재 성공 건수가 0건입니다.")
            return False

        return True

    except Exception as e:
        logger.error(f"PostgreSQL -> Chroma 적재 중 전체 오류: {e}")
        logger.error(traceback.format_exc())
        return False
