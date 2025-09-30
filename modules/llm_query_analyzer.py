import re
import sys
sys.path.append("/workspace/llm")
import json
import time        
import requests  
import ollama

from datetime     import datetime, timedelta

import config                   as cfg
import modules.chroma_rest_api  as cra
import modules.postgre_query    as dbQry
import modules.pattern_query    as qrp

from modules.utils_farm      import extract_farm_id
from modules.utils_date      import extract_hour, extract_date_range
from modules.log_handler     import setup_logger
from modules.postgre_handler import db_session
from modules.llm_rag_ref_web import get_weather_info

logger = setup_logger(__name__)

# -----------------------------------------------------------
# ** 통합된 질의 분석 메인 함수
# -----------------------------------------------------------
def analyze_query_unified(query, file_paths=None, enhanced_mode=True):
    analysis_result = {
        "query_type": "",
        "special_command": None,
        "farm_id": None,
        "house_id": None,
        "farm_name": None,
        "house_name": None,
        "hour": None,
        "date_range": None,
        "period": None,
        "found_farm_names": [],
        "found_house_names": []
    }
    
    try:
        special_command = identify_special_commands(query, file_paths)
        analysis_result["special_command"] = special_command

        if enhanced_mode:
            llm_analysis = analyze_query_with_llm(query)
            analysis_result["llm_query_type"] = llm_analysis["query_type"]
            analysis_result["llm_search_keywords"] = llm_analysis["search_keywords"]
            analysis_result["llm_confidence"] = llm_analysis["confidence"]

            if llm_analysis["query_type"] == "웹검색관련질문":
                analysis_result["needs_web_search"] = True
                analysis_result["web_search_keywords"] = llm_analysis["search_keywords"]
                analysis_result["query_type"] = "web_search"
                logger.info(f"웹 검색 질의 분석 완료: {analysis_result}")
                return analysis_result
                
            elif llm_analysis["query_type"] == "날짜관련질문":
                analysis_result["query_type"] = "current_date_time"
                analysis_result["needs_web_search"] = False
                analysis_result["web_search_keywords"] = None
                logger.info(f"날짜 관련 질의 분석 완료: {analysis_result}")
                return analysis_result
                
            elif llm_analysis["query_type"] == "농장관련질문":
                analysis_result["query_type"] = "farm_general"
                analysis_result["needs_web_search"] = False
                analysis_result["web_search_keywords"] = None
            else:
                analysis_result["query_type"] = "general_chat"
                analysis_result["needs_web_search"] = False
                analysis_result["web_search_keywords"] = None
                logger.info(f"일반 질의 분석 완료: {analysis_result}")
                return analysis_result
        else:
            llm_analysis = analyze_query_with_llm(query)
            query_type = llm_analysis["query_type"]
            
            if query_type == "날짜관련질문":
                analysis_result["query_type"] = "current_date_time"
                return analysis_result
            elif query_type == "웹검색관련질문":
                analysis_result["query_type"] = "web_search"
                return analysis_result
            elif query_type == "농장관련질문":
                analysis_result["query_type"] = "farm_general"
            else:
                analysis_result["query_type"] = "general_chat"

        farm_analysis = extract_farm_details(query)
        analysis_result.update(farm_analysis)
        
        logger.info(f"통합 질의 분석 완료: {analysis_result}")
        return analysis_result
        
    except Exception as e:
        logger.error(f"통합 질의 분석 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return analysis_result

# -----------------------------------------------------------
# ** LLM 기반 질문 유형 판단 함수
# -----------------------------------------------------------
def analyze_query_with_llm(query):
    try:
        system_prompt = """
                            당신은 사용자 질문을 분석하여 정확한 질문 유형을 판단하는 AI입니다.
                            다음 답변 유형 중 하나로만 답변하고, 추가 설명은 하지 마세요.

                            답변 유형:
                            1. 날짜관련질문 - 현재 날짜, 시간, 요일 등을 묻는 질문
                            2. 농장관련질문 - 스마트팜, 센서, 릴레이, 환경, 작물, 재배 등 농장 운영과 관련된 질문
                            3. 웹검색관련질문(키워드) - 날씨, 뉴스, 실시간 정보 등 웹에서 검색해야 하는 질문 (괄호 안에 검색 키워드 포함)
                            4. 일반질문 - 위 항목에 해당하지 않는 일반적인 대화나 질문

                            답변 규칙:
                            - 웹검색관련질문인 경우 반드시 괄호 안에 검색할 키워드를 포함하세요
                            - 예: "웹검색관련질문(서울 날씨)", "웹검색관련질문(비트코인 가격)"
                            - 다른 유형은 그대로 답변: "날짜관련질문", "농장관련질문", "일반질문"
                        """

        user_prompt = f"다음 질문은 어떤 유형인가요? '{query}'"

        from modules.llm_processor import get_llm_response
        
        llm_response = get_llm_response(
            system_prompt=system_prompt, 
            user_prompt=user_prompt,
            temperature=0.1, 
            top_p=0.8, 
            top_k=20, 
            num_predict=50,
            query_type="query_classification"
        )

        query_type_info = parse_llm_query_type_response(llm_response)
        logger.info(f"LLM 질문 유형 판단: '{query}' -> {query_type_info}")
        
        return query_type_info

    except Exception as e:
        logger.error(f"LLM 질문 유형 판단 중 오류: {e}")
        return {
            "query_type": "일반질문",
            "search_keywords": None,
            "confidence": "low"
        }

# -----------------------------------------------------------
# ** LLM 응답 파싱 함수
# -----------------------------------------------------------
def parse_llm_query_type_response(llm_response):
    llm_response = llm_response.strip()
    
    web_search_pattern = r'웹검색관련질문\(([^)]+)\)'
    match = re.search(web_search_pattern, llm_response)
    
    if match:
        keywords = match.group(1).strip()
        return {
            "query_type": "웹검색관련질문",
            "search_keywords": keywords,
            "confidence": "high"
        }
    
    if "날짜관련질문" in llm_response:
        return {
            "query_type": "날짜관련질문",
            "search_keywords": None,
            "confidence": "high"
        }
    elif "농장관련질문" in llm_response:
        return {
            "query_type": "농장관련질문", 
            "search_keywords": None,
            "confidence": "high"
        }
    elif "일반질문" in llm_response:
        return {
            "query_type": "일반질문",
            "search_keywords": None,
            "confidence": "high"
        }
    else:
        logger.warning(f"예상하지 못한 LLM 응답: {llm_response}")
        return {
            "query_type": "일반질문",
            "search_keywords": None,
            "confidence": "low"
        }

# -----------------------------------------------------------
# ** 웹 검색 키워드를 위한 날씨 정보 조회 함수 
# -----------------------------------------------------------
def get_weather_info_for_query(search_keywords):
    try:
        location = extract_location_from_keywords(search_keywords)

        weather_result = get_weather_info(location)
        return weather_result
        
    except Exception as e:
        logger.error(f"날씨 정보 조회 중 오류: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"날씨 정보 조회 실패: {str(e)}"
        }

# -----------------------------------------------------------
# ** 검색 키워드에서 지역명 추출 함수
# -----------------------------------------------------------
def extract_location_from_keywords(keywords):
    default_location = "Seoul"

    city_mapping = {
        "서울": "Seoul",
        "부산": "Busan", 
        "대구": "Daegu",
        "인천": "Incheon",
        "광주": "Gwangju",
        "대전": "Daejeon",
        "울산": "Ulsan",
        "세종": "Sejong",
        "경기": "Gyeonggi",
        "강원": "Gangwon",
        "충북": "Chungbuk",
        "충남": "Chungnam",
        "전북": "Jeonbuk",
        "전남": "Jeonnam", 
        "경북": "Gyeongbuk",
        "경남": "Gyeongnam",
        "제주": "Jeju",
        "수원": "Suwon",
        "성남": "Seongnam",
        "고양": "Goyang",
        "용인": "Yongin",
        "청주": "Cheongju",
        "천안": "Cheonan",
        "전주": "Jeonju",
        "포항": "Pohang",
        "창원": "Changwon"
    }

    for korean_city, english_city in city_mapping.items():
        if korean_city in keywords:
            return english_city
    
    return default_location

# -----------------------------------------------------------
# ** 특수 명령어 식별 
# -----------------------------------------------------------
def identify_special_commands(query, file_paths=None):
    if file_paths and any(pattern.search(query) for pattern in qrp.DOCUMENT_FOR_TRAIN_PATTERNS):
        return "document_train"
    
    if re.compile(r'^아래\s*내용을\s*학습하고\s*저장해줘', re.IGNORECASE).search(query.strip()):
        return "text_learn"
    
    if any(pattern.search(query) for pattern in qrp.LEARNING_PATTERNS):
        return "learning_info"
    
    if any(pattern.search(query) for pattern in qrp.LLM_IDENTITY_PATTERNS):
        return "llm_identity"
    
    return None

# -----------------------------------------------------------
# ** 농장명과 재배사명 추출 함수
# -----------------------------------------------------------
def extract_farm_house_names(query):
    logger.info(f" 농장명 검색 쿼리:{query}")
    try:
        farm_names = set()
        house_names = set()
        
        try:
            farm_data = cra.get_documents(collection_name=cfg.farm_collection())
            
            if farm_data and "metadatas" in farm_data:
                for metadata in farm_data["metadatas"]:
                    if "farm_name" in metadata and metadata["farm_name"]:
                        farm_names.add(metadata["farm_name"])
                    if "house_name" in metadata and metadata["house_name"]:
                        house_names.add(metadata["house_name"])
        except Exception as e:
            logger.warning(f" Farm 컬렉션 조회 중 오류: {e}")
            
        for collection_name in [cfg.source_collection(), cfg.stats_collection(), cfg.optimal_collection()]:
            try:
                collection_data = cra.get_documents(collection_name=collection_name, limit=1000)
                
                if collection_data and "metadatas" in collection_data:
                    for metadata in collection_data["metadatas"]:
                        if "farm_name" in metadata and metadata["farm_name"]:
                            farm_names.add(metadata["farm_name"])
                        if "house_name" in metadata and metadata["house_name"]:
                            house_names.add(metadata["house_name"])
            except Exception as e:
                logger.warning(f" {collection_name} 컬렉션 조회 중 오류: {e}")
        
        farm_names = list(set(farm_names))
        house_names = list(set(house_names))
                
        found_farm_names = []
        found_house_names = []
        
        for farm_name in farm_names:
            if farm_name and farm_name in query:
                found_farm_names.append(farm_name)
        
        for house_name in house_names:
            if house_name and house_name in query:
                found_house_names.append(house_name)
        
        logger.info(f" 쿼리에서 발견된 농장명: {found_farm_names}, 재배사명: {found_house_names}")
        return found_farm_names, found_house_names
    
    except Exception as e:
        logger.error(f" 농장명/재배사명 추출 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return [], []

# -------------------------------------------------------------------------------
# 질의에서 농장명을 추출하고 해당 농장 ID를 반환하는 함수
# -------------------------------------------------------------------------------
def extract_farm_name_from_query(query):
    try:
        farm_names = []
        with db_session() as database:
            results = database.fetch_all(dbQry.GET_LIST_FARM, (), as_dict=True)
            if results:
                farm_names = [(row["farm_id"], row["farm_name"]) for row in results]
        
        for farm_id, farm_name in farm_names:
            if farm_name in query:
                logger.info(f" 쿼리에서 농장명 '{farm_name}(ID:{farm_id})' 발견")
                return farm_id, farm_name
        
        return None, None
    except Exception as e:
        logger.error(f" 농장명 추출 중 오류: {e}")
        return None, None
    
# get_weather_info는 modules.llm_rag_ref_web의 구현을 사용합니다.

# -----------------------------------------------------------
# ** 농장 관련 상세 정보 추출 함수 (공통 로직)
# -----------------------------------------------------------
def extract_farm_details(query):
    """
    농장 관련 상세 정보를 추출하는 공통 함수
    farm_id, hour, date_range, period 등을 추출
    """
    farm_details = {
        "farm_id": None,
        "house_id": None,
        "farm_name": None,
        "house_name": None,
        "hour": None,
        "date_range": None,
        "period": None,
        "found_farm_names": [],
        "found_house_names": []
    }
    
    try:
        farm_id = extract_farm_id(query)
        farm_details["farm_id"] = farm_id

        hour = extract_hour(query)
        farm_details["hour"] = hour

        start_date, end_date = extract_date_range(query)
        if start_date and end_date:
            farm_details["date_range"] = {
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d")
            }

        for pattern, value in qrp.CROPS_PERIOD_PATTERNS:
            if pattern.search(query):
                farm_details["period"] = value
                break
  
        found_farm_names, found_house_names = extract_farm_house_names(query)
        farm_details["found_farm_names"] = found_farm_names
        farm_details["found_house_names"] = found_house_names

        if found_farm_names and not farm_id:
            farm_id, farm_name = extract_farm_name_from_query(query)
            farm_details["farm_id"] = farm_id
            farm_details["farm_name"] = farm_name
        
        return farm_details
        
    except Exception as e:
        logger.error(f"농장 상세 정보 추출 중 오류: {e}")
        return farm_details
