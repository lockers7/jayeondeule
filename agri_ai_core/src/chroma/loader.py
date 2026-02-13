# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ChromaDB 데이터 로더 모듈
# 처리된 데이터를 ChromaDB에 벡터 형태로 저장하고,
# 임베딩 생성 및 인덱싱을 수행합니다.
# --->
# update_learned_last_status: 최종 학습 시작 시간 저장
# get_learned_data: 기존 학습된 데이터 가져오기
# get_unlearned_data: 신규 데이터 가져오기 (is_learned=False)
# search_similar_data: Vector DB에서 유사 데이터 검색
# clean_metadata: 메타데이터 정리
# generate_document_text: 문서 텍스트 생성
# update_learned_source_data: 학습 데이터 플래그 업데이트
# get: 기능 설명 필요
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import re
import json
import traceback
from datetime import datetime, timedelta

from agri_ai_core.src.logs import setup_logger
from agri_ai_core.config import (
    source_collection,
    learned_collection,
    job_status_collection
)
from agri_ai_core.shared_modules.utils.conversion import extract_relay_data
from agri_ai_core.src.chroma.operations import (
    get_documents,
    upsert_collection_data,
    query_documents,
    generate_doc_id
)
from agri_ai_core.data_pipeline.vectorization.embedder import embed_text

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 최종 학습 시작 시간 저장
# 최종 학습 완료 시간 저장
#
# Returns:
#     str: 현재 시간 문자열
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def update_learned_last_status():
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info(f"학습 완료 일자 셋팅 -> {current_datetime}")
    result = upsert_collection_data(
        "update_learned_last_status",
        job_status_collection(),
        "last_learned_datetime",
        "최종 학습일자",
        {"last_learned_datetime": current_datetime}
    )
    if "error" not in result:
        logger.info(f"학습완료 시간: {current_datetime} 저장 성공")
    else:
        logger.error(f"학습완료 시간 저장 실패: {result['error']}")

    return current_datetime


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 기존 학습된 데이터 가져오기
# 기존 학습된 데이터 조회
#
# Args:
#     after_date: 조회 시작 일시
#     hour: 시간 필터 (미사용)
#
# Returns:
#     list: 학습된 데이터 목록
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_learned_data(after_date=None, hour=None):
    default_dt = datetime.now() - timedelta(days=3*365)

    if after_date is None:
        after_date_obj = default_dt
    elif isinstance(after_date, str):
        try:
            if len(after_date) == 8 and after_date.isdigit():
                after_date_obj = datetime.strptime(after_date, "%Y%m%d")
            else:
                after_date_obj = datetime.strptime(after_date, "%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logger.warning(f"after_date 파싱 실패: {after_date} - {e}")
            after_date_obj = default_dt
    elif isinstance(after_date, datetime):
        after_date_obj = after_date
    else:
        logger.warning(f"지원되지 않는 after_date 타입: {type(after_date)}")
        after_date_obj = default_dt

    result = get_documents(
        collection_name=learned_collection(),
        limit=100
    )

    if "error" in result or not result.get("documents"):
        logger.info(f"기존 학습 데이터 없음 또는 오류: {result.get('error', '데이터 없음')}")
        return []

    all_data = result.get("metadatas", [])
    filtered_data = []

    for item in all_data:
        dt_str = item.get("record_datetime")
        if not dt_str:
            continue
        try:
            item_date = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            if item_date >= after_date_obj:
                filtered_data.append(item)
        except Exception as e:
            logger.warning(f"record_datetime 파싱 오류: {dt_str} - {e}")
            continue

    sorted_data = sorted(filtered_data, key=lambda x: x.get("record_datetime", ""), reverse=False)
    logger.info(f"기존 학습 데이터 읽기 종료 - 처리완료: {len(sorted_data)}건")

    return sorted_data


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 신규 데이터 가져오기 (is_learned=False)
# 학습되지 않은 신규 데이터 조회
#
# Args:
#     after_date: 조회 시작 일시 ('all' 또는 datetime)
#     top_cnt: 최대 반환 건수 (0이면 제한 없음)
#
# Returns:
#     list: 학습되지 않은 데이터 목록
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_unlearned_data(after_date=None, top_cnt=0):
    try:
        logger.info(f"Source 신규 학습 데이터 읽기 시작 - 시작일자: {after_date}, 건수: {top_cnt}")
        start_time = datetime.now()

        if isinstance(after_date, str) and after_date.lower() == "all":
            after_date_dt = datetime(2000, 1, 1)
        elif isinstance(after_date, str):
            try:
                if len(after_date) == 8:
                    after_date_dt = datetime.strptime(after_date, "%Y%m%d")
                elif "/" in after_date:
                    after_date_dt = datetime.strptime(after_date, "%Y/%m/%d")
                else:
                    after_date_dt = datetime.strptime(after_date, "%Y-%m-%d")
            except Exception as e:
                logger.warning(f"after_date 문자열 변환 실패 → 기본값 사용: {e}")
                after_date_dt = datetime.now() - timedelta(days=365 * 3)
        elif isinstance(after_date, datetime):
            after_date_dt = after_date
        else:
            after_date_dt = datetime.now() - timedelta(days=365 * 3)

        after_date_str = after_date_dt.strftime("%Y-%m-%d 00:00:00")
        logger.info(f"설정된 검색 시작 날짜: {after_date_str}")

        fetch_limit = max(top_cnt * 2, 500) if top_cnt and top_cnt > 0 else 500
        result = get_documents(collection_name=source_collection(), limit=fetch_limit)
        metadatas = result.get("metadatas") if isinstance(result, dict) else None
        if not isinstance(metadatas, list) or not metadatas:
            logger.warning(f"source_collection 조회 실패 또는 빈 응답: {result}")
            return []

        logger.info(f"조회된 메타데이터 수: {len(metadatas)}")
        first_meta = metadatas[0] if isinstance(metadatas[0], dict) else None
        if first_meta and "is_learned_flag" in first_meta:
            logger.info(f"is_learned_flag 필드 존재: {first_meta['is_learned_flag']}")
        else:
            logger.info("is_learned_flag 필드가 존재하지 않음")

        filtered = []
        for item in metadatas:
            if not isinstance(item, dict):
                continue

            is_learned = str(item.get("is_learned_flag", "False")).lower() == "true"
            record_dt_str = item.get("record_datetime")

            if not is_learned and record_dt_str:
                try:
                    record_dt = datetime.strptime(record_dt_str, "%Y-%m-%d %H:%M:%S")
                    if record_dt >= after_date_dt:
                        filtered.append(item)
                except Exception as e:
                    logger.warning(f"record_datetime 파싱 실패: {record_dt_str} → {e}")

        if top_cnt > 0:
            filtered = filtered[:top_cnt]

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Source 신규 학습 데이터 읽기 종료: 전체 {len(metadatas)}건 중 {len(filtered)}건 (처리시간: {elapsed:.3f}초)")

        return filtered
    except Exception as e:
        logger.error(f"학습 데이터 검색 중 오류: {e}")
        logger.error(traceback.format_exc())
        return []


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Vector DB에서 유사 데이터 검색
# Vector DB에서 유사 데이터 검색
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
                collection_name=learned_collection(),
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
# 메타데이터 정리
# 메타데이터 정리
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def clean_metadata(metadata: dict) -> dict:
    cleaned = {}
    for k, v in metadata.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            cleaned[k] = v
        else:
            cleaned[k] = str(v)
    return cleaned


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 문서 텍스트 생성
# 문서 텍스트 생성
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 학습 데이터 플래그 업데이트
# 소스 데이터의 학습 플래그 업데이트
#
# Args:
#     datas: 업데이트할 데이터 목록
#
# Returns:
#     dict: 업데이트 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def update_learned_source_data(datas):
    try:
        if not datas:
            logger.info("업데이트할 소스 데이터가 없습니다.")
            return {"error": "입력 데이터 없음"}

        ids, documents, metadatas = [], [], []

        for idx, item in enumerate(datas):
            try:
                doc_id = generate_doc_id(
                    item.get("data_kind"),
                    item.get("farm_id"),
                    item.get("house_id"),
                    item.get("record_datetime")
                )
                if not doc_id:
                    logger.warning(f"[스킵] doc_id 생성 실패 → index={idx}")
                    continue

                # 학습 상태 및 타임스탬프 기록
                learning_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                item["is_learned_flag"] = True
                item["learning_date"] = learning_time
                item["doc_id"] = doc_id

                # 최종 입력값 구성
                ids.append(doc_id)
                documents.append(generate_document_text(item))
                metadatas.append(clean_metadata(item))

            except Exception as ie:
                logger.warning(f"[스킵] doc_id 생성 중 오류 → index={idx}, error={str(ie)}")
                continue

        if not (ids and documents and metadatas):
            logger.error("문서 형식 오류 - list 내 유효 문서 없음")
            return {"error": "문서 형식 오류 - list 내 유효 문서 없음"}

        logger.info(f"[Chroma] 총 {len(ids)}건의 학습 플래그 업데이트 시작")

        result = upsert_collection_data(
            calledby="update_learned_source_data",
            collection=source_collection(),
            doc_id=ids,
            document=documents,
            metadata=metadatas
        )

        logger.info(f"[Chroma] 학습 플래그 업데이트 완료: {result}")

        if result and isinstance(result, dict) and "error" in result:
            logger.error("[분석] 오류 발생 - ChromaDB 업서트 실패")
            logger.error(f"오류 메시지: {result['error']}")
            logger.error(f"대상 컬렉션: {source_collection()}")
            logger.error(f"총 doc_id 수: {len(ids)}")
            logger.error(f"총 document 수: {len(documents)}")
            logger.error(f"총 metadata 수: {len(metadatas)}")
            for i in range(min(5, len(ids))):
                logger.error(f"--- 문서 {i+1} ---")
                logger.error(f"doc_id: {ids[i]}")
                logger.error(f"document: {documents[i]}")
                logger.error(f"metadata: {json.dumps(metadatas[i], ensure_ascii=False)[:1000]}")

        return result

    except Exception as e:
        logger.error(f"update_learned_source_data 오류: {e}")
        logger.error(traceback.format_exc())
        return {"error": str(e)}
