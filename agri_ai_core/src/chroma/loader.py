# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ChromaDB 데이터 로더 모듈
# 처리된 데이터를 ChromaDB에 벡터 형태로 저장하고,
# 임베딩 생성 및 인덱싱을 수행합니다.
# --->
# update_learned_last_status: 최종 학습 완료 시간 저장 (PostgreSQL)
# get_unlearned_data: 미학습 데이터 가져오기 (PostgreSQL 직접 조회)
# search_similar_data: Vector DB에서 유사 데이터 검색
# generate_document_text: 문서 텍스트 생성
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import re
import traceback
from datetime import datetime, timedelta

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.chroma.collections import farm_knowledge_collection
from agri_ai_core.src.chroma.operations import query_documents
from agri_ai_core.src.utils.conversion import extract_relay_data
from agri_ai_core.src.ai.rag.embedder import embed_text
from agri_ai_core.src.postgresql.connection import db_session
from agri_ai_core.src.postgresql import queries as dbQry

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 최종 학습 완료 시간 저장 (PostgreSQL)
# 학습 완료 시점을 ai_learning_status 테이블에 기록
#
# Returns:
#     str: 현재 시간 문자열
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 미학습 데이터 가져오기 (PostgreSQL 직접 조회)
# PostgreSQL에서 마지막 학습 시점 이후의 센서/릴레이/작물 데이터를 직접 조회
#
# Args:
#     after_date: 조회 시작 일시 ('all' 또는 datetime)
#     top_cnt: 최대 반환 건수 (0이면 기본 500건)
#
# Returns:
#     list: 미학습 데이터 목록 (영문 키 dict)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _parse_after_date(after_date) -> datetime:
    """after_date 파라미터를 datetime으로 변환하는 공통 헬퍼"""
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Vector DB에서 유사 데이터 검색
# farm_knowledge 컬렉션에서 유사 데이터 검색
#
# Args:
#     query_text: 검색 쿼리
#     farm_id: 농장 ID (선택)
#     hour: 시간 필터 (미사용)
#     top_count: 최대 반환 건수
#     date_range: 날짜 범위 필터
#
# Returns:
#     list: 유사 문서 목록
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def search_similar_data(query_text, farm_id=None, hour=None, top_count=5, date_range=None):
    try:
        if farm_id is None:
            farm_id_pattern = re.compile(r'농장\s*ID[:\s=]*(\d+)|농장\s*(\d+)\s*번|(\d+)\s*번\s*농장')
            match = farm_id_pattern.search(query_text)
            if match:
                groups = match.groups()
                farm_id = next((g for g in groups if g), "default_farm_id")
            else:
                farm_id = "default_farm_id"
            logger.info(f"농장코드가 지정되지 않아 추출한 ID {farm_id} 사용")

        if not date_range:
            one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
            today = datetime.now().strftime("%Y-%m-%d")
            date_range = {
                "start_date": one_year_ago,
                "end_date": today
            }
            logger.info(f"Similar 날짜 범위가 지정되지 않아 기본 범위 사용: {date_range['start_date']} ~ {date_range['end_date']}")

        try:
            where_clause = {}
            if farm_id:
                where_clause["farm_id"] = farm_id

            query_embedding = embed_text(query_text)
            if not query_embedding:
                logger.warning("쿼리 임베딩 생성 실패")
                return []

            results = query_documents(
                collection_name=farm_knowledge_collection(),
                query_embeddings=[query_embedding],
                n_results=max(top_count, 5),
                where=where_clause if where_clause else None
            )
            similar_docs = []

            if "error" not in results and results.get("matches"):
                for match in results["matches"]:
                    metadata = match.get("metadata", {})

                    # 날짜 범위 필터링 로직
                    if date_range and "record_datetime" in metadata:
                        record_date = metadata["record_datetime"]
                        is_in_range = False

                        if isinstance(record_date, str):
                            try:
                                record_date_str = datetime.strptime(record_date, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
                                if date_range["start_date"] <= record_date_str <= date_range["end_date"]:
                                    is_in_range = True
                            except:
                                try:
                                    record_date_str = datetime.strptime(record_date, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
                                    if date_range["start_date"] <= record_date_str <= date_range["end_date"]:
                                        is_in_range = True
                                except:
                                    pass

                        if not is_in_range:
                            continue

                    relay_data = extract_relay_data(metadata)
                    if relay_data:
                        metadata["standardized_relay_data"] = relay_data

                    similar_docs.append(metadata)

                    if len(similar_docs) >= top_count:
                        break

            logger.info(f"쿼리 실행 결과: {len(similar_docs)}건")
            return similar_docs

        except Exception as e:
            logger.info(f"벡터DB 검색 오류: {e}")
            logger.error(traceback.format_exc())
            return []

    except Exception as e:
        logger.info(f"벡터DB 검색 오류: {e}")
        return []


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 문서 텍스트 생성
# 센서/릴레이 메타데이터로부터 요약 텍스트 생성
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def generate_document_text(meta: dict) -> str:
    def get(key):
        val = meta.get(key)
        return val if val not in [None, ""] else "정보 없음"

    return (
        f"{get('record_datetime')} 기준 환경 데이터: 농장 '{get('farm_name')}', 재배사 '{get('house_name')}'. "
        f"온도 {get('indoor_temperature_value')}°C, 습도 {get('indoor_humidity_value')}%, "
        f"co₂농도 {get('co2_concentration_value')}ppm, 급수: {get('fog_occurs_flag')}, "
        f"난방: {get('indoor_heater_flag')}, 조명토글: {get('lighting_flag')}, "
        f"환기: {get('exhaust_fan_flag')}, 관수밸브: {get('irrigation_flag')}."
    )
