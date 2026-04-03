"""ChromaDB 데이터 로더: 미학습 데이터 조회 및 학습 상태 관리."""
import traceback
from datetime import datetime, timedelta

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
from agri_ai_core.src.postgresql import queries as dbQry

logger = setup_logger(__name__)


# ════════════════════════════════════════════════════════════
# 최종 학습 완료 시간 저장 (PostgreSQL)
# 학습 완료 시점을 ai_learning_status 테이블에 기록
# ════════════════════════════════════════════════════════════
def update_learned_last_status():
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info(f"학습 완료 일자 셋팅 -> {current_datetime}")
    try:
        with db_session() as database:
            database.execute_query(
                dbQry.UPSERT_AI_LEARNING_STATUS,
                ("last_learned_datetime", current_datetime)
            )
        logger.info(f"학습완료 시간: {current_datetime} 저장 성공")
    except Exception as e:
        logger.error(f"학습완료 시간 저장 실패: {e}")

    return current_datetime


# ════════════════════════════════════════════════════════════
# 미학습 데이터 가져오기 (PostgreSQL 직접 조회)
# PostgreSQL에서 마지막 학습 시점 이후의 센서/릴레이/작물 데이터를 직접 조회
# ════════════════════════════════════════════════════════════
def _parse_after_date(after_date) -> datetime:
    _DEFAULT_RANGE = timedelta(days=365 * 3)

    if isinstance(after_date, str) and after_date.lower() == "all":
        return datetime(2000, 1, 1)

    if isinstance(after_date, str):
        try:
            if len(after_date) == 8:
                return datetime.strptime(after_date, "%Y%m%d")
            elif "/" in after_date:
                return datetime.strptime(after_date, "%Y/%m/%d")
            else:
                return datetime.strptime(after_date, "%Y-%m-%d")
        except Exception as e:
            logger.warning(f"after_date 문자열 변환 실패 → 기본값 사용: {e}")
            return datetime.now() - _DEFAULT_RANGE

    if isinstance(after_date, datetime):
        return after_date

    # after_date 미지정 시 ai_learning_status에서 마지막 학습 시점 조회
    try:
        with db_session() as database:
            row = database.fetch_one(
                query=dbQry.GET_AI_LEARNING_STATUS,
                vals=("last_learned_datetime",)
            )
            if row and row.get("status_value"):
                dt = datetime.strptime(row["status_value"], "%Y-%m-%d %H:%M:%S")
                logger.info(f"마지막 학습 시점: {dt}")
                return dt
            logger.info("학습 이력 없음 → 3년 전부터 조회")
            return datetime.now() - _DEFAULT_RANGE
    except Exception as e:
        logger.warning(f"학습 상태 조회 실패 → 기본값 사용: {e}")
        return datetime.now() - _DEFAULT_RANGE


def get_unlearned_data(after_date=None, top_cnt=0):
    try:
        logger.info(f"미학습 데이터 읽기 시작 (PostgreSQL 직접 조회) - 시작일자: {after_date}, 건수: {top_cnt}")
        start_time = datetime.now()

        after_date_str = _parse_after_date(after_date).strftime("%Y-%m-%d %H:%M:%S")
        fetch_limit = max(top_cnt, 500) if top_cnt and top_cnt > 0 else 500
        logger.info(f"설정된 검색 시작 날짜: {after_date_str}, 최대 건수: {fetch_limit}")

        combined_data = []

        # Units 데이터 (센서 + 릴레이) 조회
        try:
            with db_session() as database:
                units_rows = database.fetch_all(
                    query=dbQry.GET_UNLEARNED_UNITS_DATA,
                    vals=(after_date_str, fetch_limit),
                    as_dict=True
                )
                if units_rows:
                    combined_data.extend(units_rows)
                    logger.info(f"Units 데이터 조회: {len(units_rows)}건")
        except Exception as e:
            logger.warning(f"Units 데이터 조회 실패: {e}")

        # Crops 데이터 조회
        try:
            with db_session() as database:
                crops_rows = database.fetch_all(
                    query=dbQry.GET_UNLEARNED_CROPS_DATA,
                    vals=(after_date_str, fetch_limit),
                    as_dict=True
                )
                if crops_rows:
                    combined_data.extend(crops_rows)
                    logger.info(f"Crops 데이터 조회: {len(crops_rows)}건")
        except Exception as e:
            logger.warning(f"Crops 데이터 조회 실패: {e}")

        if top_cnt > 0:
            combined_data = combined_data[:top_cnt]

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"미학습 데이터 읽기 종료: {len(combined_data)}건 (처리시간: {elapsed:.3f}초)")

        return combined_data
    except Exception as e:
        logger.error(f"미학습 데이터 검색 중 오류: {e}")
        logger.error(traceback.format_exc())
        return []
