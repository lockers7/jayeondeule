import os
import re
import sys
sys.path.append("/workspace/llm")
import json
import pandas as pd
import tempfile
from datetime import datetime, timedelta

import config                  as cfg
import modules.chroma_rest_api as cra
import modules.pattern_other   as otp

# Removed unused imports from modules.postgre_query
from modules.chorma_handler       import search_similar_data
from modules.log_handler          import setup_logger
from modules.chorma_handler       import embed_text
from modules.postgre_handler      import db_session
from modules.llm_document_process import llm_document_process
from modules.llm_rag_ref_web      import search_supplementary_weather_data, get_weather_info

logger = setup_logger(__name__)

# -----------------------------------------------------------
# ** 최신 농장 데이터 가져오기
# -----------------------------------------------------------
def get_latest_farm_data(farm_id=None, hour=None):
    try:
        logger.info(f"learned_collection에서 농장 데이터 조회 시도: farm_id={farm_id}, hour={hour}")

        where_clause = {
            "farm_id": str(farm_id),
        }

        result = cra.get_documents(
            collection_name=cfg.learned_collection(),
            where=where_clause
        )

        learned_data = result.get("metadatas", [])
        filtered_data = []
        latest_learned_time = None

        for meta in learned_data:
            if meta.get("data_kind", "").upper() != "UNITS":
                continue
            if str(meta.get("farm_id")) != str(farm_id):
                continue
            dt_str = meta.get("record_datetime")
            if not dt_str:
                continue
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            if hour is not None and dt.hour != hour:
                continue
            filtered_data.append(meta)
            if latest_learned_time is None or dt > latest_learned_time:
                latest_learned_time = dt

        stats_result = cra.get_documents(collection_name=cfg.stats_collection())
        stats_datetimes = []
        for meta in stats_result.get("metadatas", []):
            dt_str = meta.get("record_datetime")
            if dt_str:
                try:
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                    stats_datetimes.append(dt)
                except Exception:
                    pass
        latest_stats_time = max(stats_datetimes) if stats_datetimes else None

        time_candidates = [latest_learned_time, latest_stats_time]
        valid_times = [t for t in time_candidates if t is not None]
        reference_time = max(valid_times) if valid_times else None

        logger.info(f"최종 필터링된 데이터 {len(filtered_data)}건")

        sorted_data = sorted(
            filtered_data,
            key=lambda x: x.get("record_datetime", ""),
            reverse=True
        )

        return {
            "current_data": sorted_data[:cfg.QUERY_SOURCE_CNT],
            "latest_stats_time": latest_stats_time,
            "latest_learned_time": latest_learned_time,
            "reference_time": reference_time,
            "source_filtered_total": len(filtered_data)
        }

    except Exception as e:
        logger.error(f"get_latest_farm_data 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "current_data": [],
            "latest_stats_time": None,
            "latest_learned_time": None,
            "reference_time": None,
            "source_filtered_total": 0
        }

# -----------------------------------------------------------
# ** 통계 데이터 가져오기
#    ChromaDB stats_collection에서 통계 데이터를 조회
# -----------------------------------------------------------
def get_statistical_data(farm_id=None, hour=None, date_range=None):
    try:
        fallback_applied = False

        logger.info(f" ##### stats data_range: {date_range}")
        if not date_range:
            one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
            today = datetime.now().strftime("%Y-%m-%d")
            date_range = {
                "start_date": one_year_ago,
                "end_date": today
            }
            logger.info(f" Stats 날짜 범위가 지정되지 않아 기본 범위 사용: {date_range['start_date']} ~ {date_range['end_date']}")

        logger.info(f" ##### stats data_range: {date_range}")
        try:
            # 전체 데이터 조회
            result = cra.get_documents(collection_name=cfg.stats_collection(), limit=300)
            logger.info(f" where 없이 전체 데이터 조회: {len(result.get('metadatas', []))}건")

            if farm_id is None:
                farm_id = result.get("farm_id")

            filtered_metadatas = []
            for metadata in result.get("metadatas", []):
                if farm_id is not None and str(metadata.get("farm_id")) != farm_id:
                    continue

                meta_hour = metadata.get("hour_of_day")
                try:
                    meta_hour = int(meta_hour)
                except:
                    continue

                if hour is not None and meta_hour != int(hour):
                    continue

                if date_range and "record_datetime" in metadata:
                    record_date_obj = cfg.parse_datetime(metadata["record_datetime"])
                    if not record_date_obj:
                        continue
                    record_date = record_date_obj.strftime("%Y-%m-%d")
                    if not (date_range["start_date"] <= record_date <= date_range["end_date"]):
                        continue

                filtered_metadatas.append(metadata)

            result["metadatas"] = filtered_metadatas
            logger.info(f" 수동 필터링 후 데이터: {len(filtered_metadatas)}건")

        except Exception as e:
            logger.info(f" ChromaDB where 쿼리 실패, 전체 데이터 조회 후 필터링: {e}")

        if not result or not result.get("metadatas"):
            logger.info(f" stats_collection에 데이터가 없습니다.")
            return []

        filtered_metadatas = result["metadatas"]

        # fallback 조건 적용
        if hour is not None and not filtered_metadatas:
            logger.info(f" [Fallback] hour={hour} 조건에 맞는 데이터가 없어 대체 시간대 검색 시도")
            all_with_hour = [
                meta for meta in result["metadatas"]
                if meta.get("data_type") in ("hourly_stats", "daily_stats")
            ]
            if all_with_hour:
                fallback_hour = all_with_hour[0].get("hour_of_day", "알수없음")
                logger.info(f" [Fallback] 대체로 선택된 시간대: {fallback_hour}")
                filtered_metadatas = all_with_hour
                fallback_applied = True

        if hour is not None and not fallback_applied:
            filtered_metadatas = [
                meta for meta in filtered_metadatas
                if meta.get("hour_of_day") == hour or str(meta.get("hour_of_day")) == str(hour)
            ]

        # 날짜 필터 재적용 (fallback 이후도 포함)
        if date_range:
            date_filtered = []
            for meta in filtered_metadatas:
                if "record_datetime" in meta:
                    try:
                        record_date_obj = datetime.strptime(meta["record_datetime"], "%Y-%m-%d %H:%M:%S")
                        record_date = record_date_obj.strftime("%Y-%m-%d")
                        if date_range["start_date"] <= record_date <= date_range["end_date"]:
                            date_filtered.append(meta)
                    except Exception:
                        try:
                            record_date_obj = datetime.strptime(meta["record_datetime"], "%Y-%m-%d %H:%M:%S")
                            record_date = record_date_obj.strftime("%Y-%m-%d")
                            if date_range["start_date"] <= record_date <= date_range["end_date"]:
                                date_filtered.append(meta)
                        except Exception:
                            continue
            filtered_metadatas = date_filtered

        data_type = "hourly_stats" if hour is not None else "daily_stats"
        type_filtered = [
            meta for meta in filtered_metadatas
            if meta.get("data_type") == data_type
        ]

        if type_filtered:
            filtered_metadatas = type_filtered
        else:
            # 없으면 daily_stats라도 사용
            type_filtered = [
                meta for meta in filtered_metadatas
                if meta.get("data_type") == "daily_stats"
            ]
            if type_filtered:
                filtered_metadatas = type_filtered

        if not filtered_metadatas:
            logger.info(f" 필터링 후 stats_collection에 데이터가 없습니다.")
            return []

        logger.info(f" 통계 데이터 조회 성공: {len(filtered_metadatas)}건")
        return filtered_metadatas

    except Exception as e:
        logger.info(f" 통계 데이터 ChromaDB 조회 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []

# ---------------------------------------------------------------
# ** 최적 환경 조건 가져오기
#    ChromaDB optimal_collection에서 최적 환경 조건 데이터를 조회
# ---------------------------------------------------------------
def get_optimal_conditions(farm_id=None, hour=None, date_range=None):
    try:
        logger.info(f" ##### optimal data_range: {date_range}")
            
        if not date_range:
            one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
            today = datetime.now().strftime("%Y-%m-%d")
            date_range = {
                "start_date": one_year_ago,
                "end_date": today
            }
            logger.info(f" Optimal 날짜 범위가 지정되지 않아 기본 범위 사용: {date_range['start_date']} ~ {date_range['end_date']}")
      
        logger.info(f" ##### optimal data_range: {date_range}")
        
        # 변수 초기화
        filtered_metadatas = []
        fallback_applied = False
        
        try:
            result = cra.get_documents(collection_name=cfg.optimal_collection(), limit=100)
            logger.info(f" where 없이 전체 데이터 조회: {len(result.get('metadatas', []))}건")
            
            if farm_id is None:
                farm_id = result.get("farm_id")
                
            # 수동 필터링
            if result and "metadatas" in result and result["metadatas"]:
                for metadata in result["metadatas"]:
                    if metadata.get("data_type") != "optimal_conditions":
                        continue
                    if farm_id is not None and str(metadata.get("farm_id")) != str(farm_id):
                        continue
                    meta_hour = metadata.get("hour_of_day")
                    try:
                        meta_hour = int(meta_hour)
                    except:
                        continue
                    if hour is not None and meta_hour != int(hour):
                        continue
                    if date_range and "record_datetime" in metadata:
                        record_date_obj = cfg.parse_datetime(metadata["record_datetime"])
                        if not record_date_obj:
                            continue
                        record_date = record_date_obj.strftime("%Y-%m-%d")
                        if not (date_range["start_date"] <= record_date <= date_range["end_date"]):
                            continue
                    filtered_metadatas.append(metadata)
                
                logger.info(f" 수동 필터링 후 데이터: {len(filtered_metadatas)}건")

            # 기존 필터된 데이터가 없을 경우 fallback 처리
            if hour is not None and not filtered_metadatas:
                logger.info(f" [Fallback] hour={hour} 조건의 데이터가 없어 대체 시간대 검색 시도")

                # hour 조건 제거하고 필터링 (farm_id만 맞추고 가장 최근 시간 사용)
                fallback_candidates = []
                if result and "metadatas" in result and result["metadatas"]:
                    for meta in result["metadatas"]:
                        if (meta.get("data_type") == "optimal_conditions" and 
                            (farm_id is None or str(meta.get("farm_id")) == str(farm_id))):
                            fallback_candidates.append(meta)

                if fallback_candidates:
                    sorted_by_time = sorted(
                        fallback_candidates,
                        key=lambda m: m.get("record_datetime", ""),
                        reverse=True
                    )
                    fallback_hour = sorted_by_time[0].get("hour_of_day", "알수없음")
                    logger.info(f" [Fallback] 대체로 선택된 시간대: {fallback_hour}")

                    filtered_metadatas = [
                        meta for meta in fallback_candidates
                        if meta.get("hour_of_day") == fallback_hour
                    ]
                    fallback_applied = True
                    
        except Exception as e:
            logger.warning(f" ChromaDB where 쿼리 실패, 전체 데이터 조회 후 필터링: {e}")
            # 예외 발생 시에도 빈 리스트로 초기화
            filtered_metadatas = []
            try:
                result = cra.get_documents(
                    collection_name=cfg.optimal_collection(),
                    limit=100
                )
                if result and "metadatas" in result and result["metadatas"]:
                    filtered_metadatas = [
                        meta for meta in result["metadatas"] 
                        if meta.get("data_type") == "optimal_conditions"
                    ]
            except Exception as inner_e:
                logger.error(f" 전체 데이터 조회도 실패: {inner_e}")
                filtered_metadatas = []

        if not filtered_metadatas:
            logger.info(f" optimal_collection에 데이터가 없습니다.")
            return []

        # 추가 필터링 (이미 위에서 처리되었지만 안전성을 위해 재확인)
        if not fallback_applied:
            # data_type 필터링
            filtered_metadatas = [
                meta for meta in filtered_metadatas 
                if meta.get("data_type") == "optimal_conditions"
            ]

            # farm_id 필터링
            if farm_id is not None:
                filtered_metadatas = [
                    meta for meta in filtered_metadatas 
                    if str(meta.get("farm_id")) == str(farm_id)
                ]

            # hour 필터링
            if hour is not None:
                hour_filtered = [
                    meta for meta in filtered_metadatas 
                    if (meta.get("hour_of_day") == hour or 
                        str(meta.get("hour_of_day")) == str(hour))
                ]
                if hour_filtered:
                    filtered_metadatas = hour_filtered

        if not filtered_metadatas:
            logger.info(f" 필터링 후 optimal_collection에 데이터가 없습니다.")
            return []
        
        logger.info(f" 최적 환경 조건 조회 성공: {len(filtered_metadatas)}건")
        return filtered_metadatas
        
    except Exception as e:
        logger.error(f" 최적 환경 조건 ChromaDB 조회 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []

# -----------------------------------------------------------
# ** 학습 데이터 검색
# -----------------------------------------------------------
def search_learned_data(query, farm_id=None, hour=None, date_range=None):
    try:
        # 유사도 검색
        enhanced_query = query
        if farm_id:
            enhanced_query += f" 농장코드: {farm_id}"
        if hour is not None:
            enhanced_query += f" 시간대: {hour}시"

        date_range_condition = None
        if date_range:
            logger.info(f" 날짜 범위가 지정되었습니다: {date_range['start_date']} ~ {date_range['end_date']}")
            date_range_condition = date_range
            enhanced_query += f" 기간: {date_range['start_date']}부터 {date_range['end_date']}까지"
            
        similar_docs = search_similar_data(enhanced_query, farm_id, hour, 5, date_range_condition)
        if similar_docs:
            return similar_docs
        else:
            try:
                learned_results = cra.get_documents(collection_name=cfg.learned_collection(), limit=10)
                
                if learned_results and "metadatas" in learned_results and learned_results["metadatas"]:
                    filtered_docs = []
                    for metadata in learned_results["metadatas"]:
                        # 학습 플래그나 관련 필드 검사
                        if (metadata.get("is_learned_flag", False) or 
                            "learning_date" in metadata or 
                            "document_title" in metadata):
                            filtered_docs.append(metadata)
                    
                    if filtered_docs:
                        logger.info(f" 일반 검색으로 학습 데이터 {len(filtered_docs)}건 조회됨")
                        return filtered_docs
            except Exception as e:
                logger.warning(f" 학습 데이터 일반 검색 중 오류: {e}")
        
        return []
        
    except Exception as e:
        logger.error(f" 학습 데이터 검색 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []

# -----------------------------------------------------------
# ** 문서 데이터 검색
# -----------------------------------------------------------
def search_document_data(farm_id=None):
    try:
        document_result = cra.get_documents(cfg.document_collection(), where={"farm_id": str(farm_id)} if farm_id else None, limit=20)
        if document_result and "documents" in document_result:
            logger.info(f" document_collection에서 {len(document_result.get('documents', []))}건 문서 조회됨")
            return document_result.get("documents", [])
        return []
    except Exception as e:
        logger.warning(f" document_collection 조회 중 오류: {e}")
        return []

# -----------------------------------------------------------
# ** 학습 요약 데이터 조회
# -----------------------------------------------------------
def get_learning_summary_data():
    try:
        learned_data = []
        learning_results = cra.get_documents(collection_name=cfg.learned_collection(), limit=100)
        if learning_results and "metadatas" in learning_results and learning_results["metadatas"]:
            learning_docs = {}
            for metadata in learning_results["metadatas"]:
                if metadata.get("is_learned_flag", True):
                    doc_title = metadata.get("document_title", "")
                    learning_date = metadata.get("learning_date", "")
                    record_datetime = metadata.get("record_datetime", "")
                    if not doc_title:
                        doc_title = metadata.get("crop_name", "") or "학습 문서"
                    
                    if not learning_date and record_datetime:
                        learning_date = record_datetime
                    
                    if doc_title: 
                        key = f"{doc_title}_{learning_date}" if learning_date else f"{doc_title}"
                        if key not in learning_docs:
                            learning_docs[key] = {
                                "document_title": doc_title,
                                "learning_date": learning_date or "날짜 정보 없음",
                                "data_type": "learning_summary",
                                "crop_name": metadata.get("crop_name", ""),
                                "category": metadata.get("category", "")
                            }
            
            for doc_info in learning_docs.values():
                learned_data.append(doc_info)
                
            logger.info(f" 학습 데이터 요약 {len(learning_docs)}건 조회됨")
        return learned_data
    except Exception as e:
        logger.warning(f" 학습 데이터 요약 조회 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []

# -----------------------------------------------------------
# ** 작물 정보 검색
# -----------------------------------------------------------
def search_crop_information(query):
    try:
        logger.debug(f" query_documents 호출 - query_text: {query}")       
        query_embedding = embed_text(query)
        if not query_embedding:
            logger.warning("쿼리 임베딩 생성 실패")
            return []
         
        crop_qa_results = cra.query_documents(
            collection_name=cfg.learned_collection(),
            query_texts=[query],
            query_embeddings=[query_embedding],            
            where={"data_type": "qa_pair"},
            n_results=5
        )            
        logger.debug(f" query_documents 결과: {len(crop_qa_results.get('documents', [[]])[0])}건")                
        if crop_qa_results and "metadatas" in crop_qa_results and crop_qa_results["metadatas"] and len(crop_qa_results["metadatas"][0]) > 0:
            logger.info(f" 작물 문서 학습 정보 {len(crop_qa_results['metadatas'][0])}건 검색됨")
            return crop_qa_results["metadatas"][0]
        return []
    except Exception as e:
        logger.warning(f" 작물 정보 검색 중 오류: {e}")
        return []

# -----------------------------------------------------------
# ** 작물 관련 문서 검색
# -----------------------------------------------------------
def search_crop_related_documents(query):
    """
    작물 관련 문서를 검색하는 함수
    """
    try:
        crop_patterns = [r'상황\s*버섯', r'작약', r'쇠\s*무릎']
        
        mentioned_crop = None
        for pattern in crop_patterns:
            crop_match = re.search(pattern, query)
            if crop_match:
                mentioned_crop = crop_match.group(0).replace(' ', '')
                break

        if mentioned_crop:
            logger.info(f" 질의에서 작물명 '{mentioned_crop}' 감지됨")
            
            enhanced_query = f"{query} {mentioned_crop} 작물 정보"
            query_embedding = embed_text(enhanced_query)
            if not query_embedding:
                logger.warning("쿼리 임베딩 생성 실패")
                return []

            crop_results = cra.query_documents(
                collection_name=cfg.optimal_collection(),
                query_texts=[enhanced_query],
                query_embeddings=[query_embedding],
                n_results=3,
                where={"crop_name": mentioned_crop}
            )                
            if crop_results and "metadatas" in crop_results and crop_results["metadatas"] and len(crop_results["metadatas"][0]) > 0:
                logger.info(f" 작물명 '{mentioned_crop}'으로 {len(crop_results['metadatas'][0])}개 문서 추가 검색됨")
                return crop_results["metadatas"][0]
        
        return []
        
    except Exception as e:
        logger.warning(f" 작물 관련 문서 검색 중 오류: {e}")
        return []

# -----------------------------------------------------------
# ** 농장별 특화 데이터 검색
# -----------------------------------------------------------
def search_farm_specific_data(query, farm_name, house_name=None):
    """
    농장별 특화 데이터를 검색하는 함수
    """
    try:
        enhanced_query = f"{query} 농장: {farm_name}"
        if house_name:
            enhanced_query += f" 재배사: {house_name}"
        
        logger.info(f" 농장명 기준 강화된 검색 쿼리: {enhanced_query}")
        
        embedding = embed_text(enhanced_query)
        logger.info(f" query_embedding dim = {len(embedding)}")  # 확인용 로그

        if embedding and len(embedding) == cfg.CHROMA_EMBEDDING_DIM:
            farm_specific_results = cra.query_documents(
                collection_name=cfg.source_collection(),
                query_embeddings=[embedding],
                n_results=20
            )
        else:
            logger.warning(f" 올바르지 않은 임베딩 차원: {len(embedding)} (expected {cfg.CHROMA_EMBEDDING_DIM})")
            return []
            
        if farm_specific_results and "metadatas" in farm_specific_results and farm_specific_results["metadatas"]:
            if farm_specific_results["metadatas"][0]:
                filtered_results = [
                    meta for meta in farm_specific_results["metadatas"][0]
                    if meta.get("farm_name") == farm_name
                ]
                
                if filtered_results:
                    logger.info(f" 농장명 '{farm_name}' 기준 검색 결과: {len(filtered_results)}건")
                    return filtered_results
        return []
        
    except Exception as e:
        logger.warning(f" 농장별 특화 데이터 검색 중 오류: {e}")
        return []

# -----------------------------------------------------------
# ** 날씨 데이터 검색
# -----------------------------------------------------------
def search_weather_data(query):
    try:
        weather_context = search_supplementary_weather_data(query)
        weather_data = get_weather_info()
        
        return {
            "weather_context": weather_context,
            "weather_data": weather_data
        }
    except Exception as e:
        logger.warning(f" 날씨 데이터 검색 중 오류: {e}")
        return {"weather_context": {}, "weather_data": None}

# -----------------------------------------------------------
# ** 여러 컬렉션에서 통합된 가상 릴레이 데이터 생성
# -----------------------------------------------------------
def create_virtual_relay_data(stats_data, optimal_data, learned_data):
    virtual_data = {
        "record_datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    relay_data = {}
    if stats_data:
        latest_stats = stats_data[0]
        virtual_data["farm_id"] = latest_stats.get("farm_id")
        virtual_data["house_id"] = latest_stats.get("house_id")
        
        if "relay_stats" in latest_stats:
            try:
                relay_stats = json.loads(latest_stats["relay_stats"])
                for stats_key, value in relay_stats.items():
                    source_key = cfg.RELAY_FIELD_MAPPING.get(stats_key)
                    if source_key:
                        relay_data[source_key] = value
            except:
                pass

    if optimal_data and not relay_data:
        latest_optimal = optimal_data[0]
        virtual_data["farm_id"] = latest_optimal.get("farm_id", virtual_data.get("farm_id"))
        virtual_data["house_id"] = latest_optimal.get("house_id", virtual_data.get("house_id"))
        
        if "relay_means" in latest_optimal:
            try:
                relay_means = json.loads(latest_optimal["relay_means"]) if isinstance(latest_optimal["relay_means"], str) else latest_optimal["relay_means"]
                for stats_key, value in relay_means.items():
                    source_key = cfg.RELAY_FIELD_MAPPING.get(stats_key)
                    if source_key and source_key not in relay_data:
                        # 평균값을 불리언으로 변환
                        relay_data[source_key] = value > 0.5 if isinstance(value, (int, float)) else bool(value)
            except:
                pass

    if learned_data and not relay_data:
        for learned_item in learned_data:
            if "standardized_relay_data" in learned_item:
                for key, value in learned_item["standardized_relay_data"].items():
                    if key not in relay_data:
                        relay_data[key] = value

    if relay_data:
        for key, value in relay_data.items():
            virtual_data[key] = value

        relay_stats = {}
        for source_key, value in relay_data.items():
            stats_key = next((k for k, v in cfg.RELAY_FIELD_MAPPING.items() if v == source_key), None)
            if stats_key:
                relay_stats[stats_key] = value
        
        virtual_data["relay_stats"] = json.dumps(relay_stats, ensure_ascii=False)
        virtual_data["standardized_relay_data"] = relay_data
        
        return virtual_data
    
    return None

# -----------------------------------------------------------
# ** 농장/재배사 ID 조회
# -----------------------------------------------------------
"""미사용 함수 제거: get_farm_house_ids"""

# -----------------------------------------------------------------------
# 질의 유형에 따라 필요한 컬렉션에서 관련 데이터를 검색하는 함수
# -----------------------------------------------------------------------
def retrieve_context_data(query, query_type, hour=None, farm_id=None, farm_name=None, house_id=None, house_name=None):
    context_data = {
        "learned_data": [],
        "stats_data": [],
        "optimal_data": [],
        "current_data": [],
        "document_data": [],
        "farm_info": {
            "farm_id": farm_id,
            "farm_name": farm_name,
            "house_id": house_id,
            "house_name": house_name
        }
    }

    try:
        document_data = search_document_data(farm_id)
        context_data["document_data"] = document_data
        
        one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")

        date_range = {
            "start_date": one_year_ago,
            "end_date": today
        }
        logger.info(f" 기본 날짜 범위 설정: {date_range['start_date']} ~ {date_range['end_date']}")
    
        for pattern, value in otp.CROPS_PERIOD.items():
            if pattern in query:
                period = value
                logger.info(f" 기간 패턴 추출: {period}")
                break

        # 작물 관련 문서 검색
        crop_documents = search_crop_related_documents(query)
        if crop_documents:
            context_data["optimal_data"].extend(crop_documents)

        # 학습 요약 데이터 조회
        learning_summary = get_learning_summary_data()
        context_data["learned_data"] = learning_summary

        # 현재 농장 데이터 조회
        current_data_result = get_latest_farm_data(farm_id, hour)
        context_data["current_data"] = current_data_result.get("current_data", [])

        latest_stats_time = current_data_result.get("latest_stats_time")
        latest_learned_time = current_data_result.get("latest_learned_time")
        reference_time = current_data_result.get("reference_time")

        logger.info(f"get_latest_farm_data 반환 - stats: {latest_stats_time}, learned: {latest_learned_time}, 참조: {reference_time}")
        
        # 릴레이 데이터 표준화
        if context_data["current_data"]:
            for data_item in context_data["current_data"]:
                relay_data = cfg.extract_relay_data(data_item)
                if relay_data:
                    data_item["standardized_relay_data"] = relay_data
                    relay_stats = {}
                    for source_key, value in relay_data.items():
                        stats_key = next((k for k, v in cfg.RELAY_FIELD_MAPPING.items() if v == source_key), None)
                        if stats_key:
                            relay_stats[stats_key] = value

                    if "relay_stats" not in data_item:
                        data_item["relay_stats"] = json.dumps(relay_stats, ensure_ascii=False)
            
            # 학습 데이터와 현재 데이터 시간 비교 필터링
            if context_data["learned_data"]:
                latest_learned_datetime = None
                for learned_item in context_data["learned_data"]:
                    if "record_datetime" in learned_item:
                        try:
                            item_datetime = datetime.strptime(learned_item["record_datetime"], "%Y-%m-%d %H:%M:%S")
                            if latest_learned_datetime is None or item_datetime > latest_learned_datetime:
                                latest_learned_datetime = item_datetime
                        except Exception as e:
                            logger.warning(f" 날짜 형식 변환 오류: {e}")
                            
                if latest_learned_datetime:
                    logger.info(f" 학습 데이터 최신 날짜: {latest_learned_datetime}")
                    filtered_current_data = []
                    for item in context_data["current_data"]:
                        if "record_datetime" in item:
                            try:
                                item_datetime = datetime.strptime(item["record_datetime"], "%Y-%m-%d %H:%M:%S")
                                if item_datetime > latest_learned_datetime:
                                    filtered_current_data.append(item)
                            except Exception:
                                filtered_current_data.append(item)  # 날짜 파싱 오류 시 기본 포함
                        else:
                            filtered_current_data.append(item)  # 날짜 필드 없으면 기본 포함
                            
                    if filtered_current_data:
                        logger.info(f" 학습 데이터보다 최신인 현재 데이터 {len(filtered_current_data)}건 필터링됨")
                        context_data["current_data"] = filtered_current_data
                    else:
                        logger.info(f" 학습 데이터보다 최신인 현재 데이터가 없음")            
        else:
            logger.warning(f" 현재 농장 데이터를 찾을 수 없습니다.")

        # 유사도 기반 학습 데이터 검색
        similar_docs = search_learned_data(query, farm_id, hour, date_range)
        if similar_docs:
            context_data["learned_data"] = similar_docs

        # 작물 정보 검색 (crop_information 타입일 때)
        if query_type == "crop_information":
            crop_info = search_crop_information(query)
            if crop_info:
                learning_info_found = False
                for metadata in crop_info:
                    if ("learning_date" in metadata or "document_title" in metadata) and metadata not in context_data["learned_data"]:
                        context_data["learned_data"].append(metadata)
                        learning_info_found = True
                
                if learning_info_found:
                    logger.info(f" 작물 문서 학습 정보 {len(crop_info)}건 추가됨")

        # 농장별 특화 데이터 검색
        if farm_name:
            farm_specific_data = search_farm_specific_data(query, farm_name, house_name)
            if farm_specific_data:
                context_data["farm_specific_data"] = farm_specific_data

        # 질의 유형별 특화 데이터 검색
        if query_type == "relay_status":
            stats_data = get_statistical_data(farm_id, hour, date_range)
            if stats_data:
                context_data["stats_data"] = stats_data
                logger.info(f" 통계 데이터 {len(stats_data)}건 조회 성공")

            optimal_data = get_optimal_conditions(farm_id, hour, date_range)
            if optimal_data:
                context_data["optimal_data"] = optimal_data
                logger.info(f" 최적 환경 데이터 {len(optimal_data)}건 조회 성공")

        elif query_type in ["environment_control", "environment_status", "control_suggestion", "farm_status"]:
            optimal_data = get_optimal_conditions(farm_id, hour, date_range)
            if optimal_data:
                context_data["optimal_data"] = optimal_data
                for item in context_data["optimal_data"]:
                    if "is_manual" not in item:
                        item["is_manual"] = False                
        
        elif query_type in ["yield_information", "data_analysis", "environment_status", "farm_status"]:
            stats_data = get_statistical_data(farm_id, hour, date_range)
            if stats_data:
                context_data["stats_data"] = stats_data
                logger.info(f" 통계 데이터 {len(stats_data)}건 조회 성공")

        # 시간대 제약 없이 재검색
        if (not context_data["current_data"]) and hour is not None:
            logger.info(f" 시간대 {hour}에 데이터가 없어 시간대 제약 없이 재검색합니다.")
            additional_data_result = get_latest_farm_data(farm_id, None)
            additional_data = additional_data_result.get("current_data", [])
            if additional_data:
                for data_item in additional_data:
                    relay_data = cfg.extract_relay_data(data_item)
                    if relay_data:
                        data_item["standardized_relay_data"] = relay_data
                
                context_data["current_data"] = additional_data
                logger.info(f" 추가 검색으로 현재 데이터 {len(additional_data)}건 조회됨")

        # 릴레이 상태 질의에 대한 가상 데이터 생성
        if query_type == "relay_status" and not context_data["current_data"]:
            if context_data["stats_data"] or context_data["optimal_data"] or context_data["learned_data"]:
                virtual_current_data = create_virtual_relay_data(
                    context_data["stats_data"], 
                    context_data["optimal_data"], 
                    context_data["learned_data"]
                )
                
                if virtual_current_data:
                    context_data["current_data"] = [virtual_current_data]
                    logger.info(f" 다른 컬렉션에서 보완된 릴레이 데이터 생성")
                
    except Exception as e:
        logger.error(f" 컨텍스트 데이터 검색 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())

    data_counts = {
        "current": len(context_data["current_data"]),
        "learned": len(context_data["learned_data"]),
        "optimal": len(context_data["optimal_data"]),
        "stats": len(context_data["stats_data"]),
        "document": len(context_data["document_data"])
    }
    logger.info(f" 대화를 위한 각 데이터 조회 결과: {data_counts}")
    
    return context_data

# -----------------------------------------------------------
# ** 파일 정보 추출
#    첨부 파일 분석 및 컨텍스트에 필요한 정보 추출
# -----------------------------------------------------------
def extract_file_info(file_paths):
    if not file_paths:
        return None
    
    file_context = {
        "csv_data": [],
        "excel_data": [],
        "image_data": [],
        "text_data": []
    }

    for file_info in file_paths:
        filename = file_info["filename"]
        path = file_info["path"]
        
        try:
            file_ext = os.path.splitext(filename)[1].lower()
            if file_ext == '.csv':
                file_context["csv_data"].append(process_csv_file(path, filename))
            elif file_ext in ['.xlsx', '.xls']:
                file_context["excel_data"].append(process_excel_file(path, filename))
            elif file_ext in ['.txt', '.log', '.md']:
                file_context["text_data"].append(process_text_file(path, filename))
            elif file_ext in ['.jpg', '.jpeg', '.png', '.gif']:
                file_context["image_data"].append({
                    "filename": filename,
                    "note": "이미지 파일 첨부됨 (내용 분석 불가)"
                })
            else:
                logger.info(f" 지원되지 않는 파일 형식: {filename}")
                
        except Exception as e:
            logger.error(f" 파일 정보 추출 중 오류 ({filename}): {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    return file_context

# -----------------------------------------------------------
# ** CSV 파일 처리
# -----------------------------------------------------------
def process_csv_file(file_path, filename):
    """
    CSV 파일을 처리하는 함수
    """
    try:
        df = pd.read_csv(file_path, encoding='utf-8')
        if df.empty or len(df.columns) <= 1:
            encodings = ['cp949', 'euc-kr', 'latin1']
            for encoding in encodings:
                try:
                    df = pd.read_csv(file_path, encoding=encoding)
                    if not df.empty and len(df.columns) > 1:
                        break
                except:
                    continue

        rows_count = len(df)
        columns_count = len(df.columns)
        columns_info = list(df.columns)

        sample_rows = df.head(5).to_dict(orient='records')

        numeric_stats = {}
        for col in df.select_dtypes(include=['number']).columns:
            numeric_stats[col] = {
                "mean": df[col].mean(),
                "min": df[col].min(),
                "max": df[col].max()
            }
        
        result = {
            "filename": filename,
            "rows_count": rows_count,
            "columns_count": columns_count,
            "columns": columns_info,
            "sample_data": sample_rows,
            "numeric_stats": numeric_stats
        }
        
        return result
        
    except Exception as e:
        logger.error(f" CSV 파일 처리 중 오류: {e}")
        return {
            "filename": filename,
            "error": f"파일 처리 중 오류 발생: {str(e)}"
        }

# -----------------------------------------------------------
# ** Excel 파일 처리
# -----------------------------------------------------------
def process_excel_file(file_path, filename):
    """
    Excel 파일을 처리하는 함수
    """
    try:
        xl = pd.ExcelFile(file_path)
        sheets = xl.sheet_names
        
        result = {
            "filename": filename,
            "sheets_count": len(sheets),
            "sheets": {}
        }

        for sheet in sheets:
            df = pd.read_excel(file_path, sheet_name=sheet)
            sheet_info = {
                "rows_count": len(df),
                "columns_count": len(df.columns),
                "columns": list(df.columns),
                "sample_data": df.head(3).to_dict(orient='records')
            }
            
            result["sheets"][sheet] = sheet_info
        
        return result
        
    except Exception as e:
        logger.error(f" Excel 파일 처리 중 오류: {e}")
        return {
            "filename": filename,
            "error": f"파일 처리 중 오류 발생: {str(e)}"
        }

# -----------------------------------------------------------
# ** 텍스트 파일 처리
# -----------------------------------------------------------
def process_text_file(file_path, filename):
    """
    텍스트 파일을 처리하는 함수
    """
    try:
        encodings = ['utf-8', 'cp949', 'euc-kr', 'latin1']
        content = None
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as file:
                    content = file.read()
                    break
            except:
                continue
        
        if content is None:
            with open(file_path, 'rb') as file:
                content = file.read().decode('utf-8', errors='replace')

        lines = content.split('\n')
        lines_count = len(lines)
        chars_count = len(content)

        if len(content) > 2000:
            preview = content[:1000] + "\n...[중략]...\n" + content[-1000:]
        else:
            preview = content
        
        return {
            "filename": filename,
            "lines_count": lines_count,
            "chars_count": chars_count,
            "preview": preview
        }
        
    except Exception as e:
        logger.error(f" 텍스트 파일 처리 중 오류: {e}")
        return {
            "filename": filename,
            "error": f"파일 처리 중 오류 발생: {str(e)}"
        }


# -------------------------------------------------
# 사용자가 입력한 텍스트를 처리하고 저장하는 함수
# -------------------------------------------------
def process_and_save_text(text_content, farm_id):
    """
    사용자가 입력한 텍스트를 처리하고 저장하는 함수
    """
    try:
        logger.info(f" 텍스트 처리 시작 (길이: {len(text_content)}자)")

        temp_dir = tempfile.mkdtemp()
        temp_file_path = os.path.join(temp_dir, f"user_input_{datetime.now().strftime('%Y%m%d%H%M%S')}.txt")
        
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            f.write(text_content)
            
        logger.info(f" 임시 파일 생성 완료: {temp_file_path}")
        
        result = llm_document_process(temp_file_path, farm_id)
        
        # 임시 파일 삭제
        try:
            os.remove(temp_file_path)
            os.rmdir(temp_dir)
        except Exception as e:
            logger.warning(f" 임시 파일 삭제 중 오류: {e}")
        
        # 처리 결과 확인 및 응답 생성
        if result["success"]:
            chunks_count = result.get("chunks_stored", 0)
            qa_count = result.get("qa_pairs_generated", 0)
            
            response = f"텍스트 학습 및 저장이 완료되었습니다.\n\n"
            response += f"• 처리된 문서 청크: {chunks_count}개\n"
            response += f"• 생성된 질문-답변 쌍: {qa_count}개\n\n"
            
            # 문서 유형과 작물 감지
            doc_type = result.get("document_type", "일반")
            crop_name = result.get("crop_name", "")
            
            if crop_name:
                response += f"감지된 작물: {crop_name}\n"
            response += f"문서 유형: {doc_type}\n\n"
            
            response += "이제 이 내용에 관해 질문해보세요!"
            
            return response
        else:
            error = result.get("error", "알 수 없는 오류")
            return f"텍스트 처리 중 오류가 발생했습니다: {error}"
            
    except Exception as e:
        logger.error(f" 텍스트 처리 중 오류: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return f"텍스트 처리 중 예상치 못한 오류가 발생했습니다: {str(e)}"
