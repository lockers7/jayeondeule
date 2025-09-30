import re
import sys
sys.path.append("/workspace/llm")
import json
import asyncio
import traceback
from datetime import datetime, timedelta

import config                  as cfg
import modules.chorma_handler  as chdr
import modules.chroma_rest_api as cra            
import modules.postgre_query   as dbQry

from modules.com_function        import safe_bool_convert
from modules.llm_processor       import process_llm_query
from modules.postgre_handler     import db_session

from modules.log_handler         import setup_logger
logger = setup_logger(__name__)

WATER_TEMP_OFFSET = 5  # 수온을 내부온도보다 5도 높게 설정
# Removed unused constants: DEBUG_MODE, HEATING_PREDICTION_TIME
   
# ---------------------------------------------------------
# 모든 농장/재배사의 릴레이 제어 수행
# ---------------------------------------------------------
def control_all_relays():
    current_time = datetime.now().strftime("%H:%M")
    logger.info("="  * 120)
    logger.info(f" 시간대 {current_time}시 사용자 릴레이 자동 제어 작업 시작")

    try:
        with db_session() as db:
            farm_lists = db.fetch_all(query=dbQry.GET_FARM_HOUSE_LIST, vals=(), as_dict=True)
        for farm in farm_lists:
            farm_id = farm["farm_id"]
            farm_name = farm["farm_name"]
            house_id = farm["hous_id"]
            house_name = farm["hous_name"]

            # 아래에서 관수, 조명은 자동, 수동 여부 상관없이 실행 되도록 한다.
            apply_time_based_settings_exception(farm_id, house_id)            

            if farm.get("mnul_ctrl_flag", False):
                logger.info(f"***{'-'*110}***")
                logger.info(f" {farm_name} 농장, {house_name} 재배사 시간대 {current_time}시 릴레이 수동 모드로 인해 자동 제어를 실행하지 않습니다.")
                logger.info(f"***{'-'*110}***")
                continue

            logger.info("-"  * 100)
            logger.info(f" {farm_name} 농장, {house_name} 재배사 시간대 {current_time}시 릴레이 제어 시작")
            logger.info("-"  * 100)

            current_env = get_current_environment_data(farm_id, house_id)
            if not current_env:
                logger.info(f" {farm_name} 농장, {house_name} 재배사의 환경 데이터가 없습니다. 다음 재배사로 넘어갑니다.")
                continue

            optimal_conditions = get_optimal_conditions(farm_id, house_id)
            if not optimal_conditions:
                logger.info(f" {farm_name} 농장, {house_name} 재배사의 최적 환경 조건 데이터가 없습니다. \nGET_OPTIMAL_CONDITION 쿼리로 대체합니다.")
                optimal_conditions = optimal_condition_from_postgresql(farm_id, house_id)
                if not optimal_conditions:
                    continue

            relay_settings = determine_relay_settings(farm_id, house_id, current_env, optimal_conditions)
            if relay_settings:
                relay_settings = save_relay_settings(farm_id, house_id, relay_settings)
                if not relay_settings:
                    logger.info(f" {farm_name} 농장, {house_name} 재배사 릴레이 설정 저장 실패")
            else:
                logger.info(f" {farm_name} 농장, {house_name} 재배사 릴레이 설정을 결정할 수 없습니다.")

            logger.info(f"센서 상태 ===> {farm_name} - {house_name} \n"
                         f" - 내부온도: {current_env.get('indoor_temperature')} ℃\n"
                         f" - 외부온도: {current_env.get('outdoor_temperature')} ℃\n"
                         f" - 내부습도: {current_env.get('indoor_humidity')} %\n"
                         f" - 외부습도: {current_env.get('outdoor_humidity')} %\n"
                         f" - co2: {current_env.get('co2')} ppm\n"
                         f" - 수온: {current_env.get('water_temperature')} ℃")

            logger.info(f"{relay_settings}")
        logger.info(f" 시간대 {current_time}시 사용자 릴레이 자동 제어 작업 종료")
        logger.info("="  * 120)
    except Exception as e:
        logger.error(f" 릴레이 제어 작업 중 오류: {e}")
        logger.error(traceback.format_exc())
        logger.error(f" 시간대 {current_time}시 릴레이 제어 작업 실패")

# ---------------------------------------------------------
# 릴레이 판단 결정 함수 - 기존 방식 유지 + LLM 연동
# ---------------------------------------------------------
def determine_relay_settings(farm_id, house_id, current_env, optimal_conditions):
    relay_settings = cfg.initialize_relay_settings()

    current_time = datetime.now()
    optimal = optimal_conditions.get("sensor_means", {})
    optimal_datas = (
                        f"- 적정최저온도: {optimal.get('적정최저온도')} \n"
                        f"- 적정최고온도: {optimal.get('적정최고온도')} \n"
                        f"- 적정최저습도: {optimal.get('적정최저습도')} \n"
                        f"- 적정최고습도: {optimal.get('적정최고습도')} \n"
                        f"- 적정최고co2: {optimal.get('적정최고co2')} \n"
                        f"- 적정최저co2: {optimal.get('적정최저co2')} \n"
                        f"- 적정최저수온: {optimal.get('적정최저수온')} \n"
                        f"- 적정최고수온: {optimal.get('적정최고수온')} \n"
                        f"- 현재시간: {current_time} (24시간 기준) \n"        
                    )
    
    # Removed unused growth_datas and learning_datas

    sensor = extract_current_sensor_values(current_env)
    sensor_datas = (
                        f"- 내부온도: {sensor.get('current_temp', 0)} ℃ \n"
                        f"- 외부온도: {sensor.get('outdoor_temp', 0)} ℃ \n"
                        f"- 내부습도: {sensor.get('current_humidity', 0)} % \n"
                        f"- 외부습도: {sensor.get('outdoor_humidity', 0)} % \n"
                        f"- co2 농도: {sensor.get('current_co2', 0)} ppm \n"
                        f"- 수온: {sensor.get('current_water_temp', 0)} ℃ \n"
                        f"- 현재시간: {current_time} (24시간 기준) \n"        
                    )
        
    # system_prompt, user_prompt = relay_build_control_prompt(optimal_datas, sensor_datas, learning_datas)
    
    # try:
    #     logger.info(f" LLM 기반 릴레이 제어위한 LLM 판단 중")
    #     async def get_llm_result():
    #         context_data = {
    #             "original_query": "relay_control",
    #             "current_data": [current_env] if current_env else [],
    #             "optimal_data": [optimal_conditions] if optimal_conditions else [],
    #             "stats_data": [],
    #             "learned_data": []
    #         }
    #         response_parts = []
    #         async for chunk in process_llm_query(system_prompt=system_prompt, user_prompt=user_prompt, query_type="relay_llm_control", context_data=context_data, hour=current_time.hour, stream=False):
    #             response_parts.append(chunk)
    #         return ''.join(response_parts)
        
    #     llm_response_text = asyncio.run(get_llm_result())
    # except Exception as e:
    #     logger.error(f"LLM 릴레이 제어 호출 중 오류: {e}")
    #     llm_response_text = None

    llm_response_text = None
    relay_settings_extracted = None
    # try:
    #     relay_settings_extracted = None
    #     if llm_response_text and "METADATA:" in llm_response_text:
    #         metadata_json = llm_response_text.split("METADATA:", 1)[1].strip()
    #         metadata_json = re.sub(r'#[^\n]*', '', metadata_json)
    #         try:
    #             metadata_dict = json.loads(metadata_json)
    #             relay_settings_extracted = metadata_dict.get("relay_settings")
    #             if isinstance(relay_settings_extracted, dict):
    #                 logger.info(f"METADATA에서 relay_settings 추출 성공: {len(relay_settings_extracted)}개")
    #             else:
    #                 logger.warning("METADATA에 relay_settings 키가 없거나 형식이 올바르지 않습니다.")
    #         except json.JSONDecodeError as e:
    #             logger.error(f"METADATA JSON 파싱 실패: {e}")
    #     else:
    #         logger.warning("LLM 응답에 METADATA 블록이 없습니다.")
    # except Exception as e:
    #     logger.error(f"LLM 릴레이 제어 파싱 중 오류: {e}")
    #     relay_settings_extracted = None

    if relay_settings_extracted:
        relay_settings.update({k: safe_bool_convert(v) for k, v in relay_settings_extracted.items()})
        doc_id = cra._doc_id_generator("self", farm_id, house_id, current_time)

        try:
            if "METADATA:" in llm_response_text:
                metadata_start = llm_response_text.find("METADATA:") + len("METADATA:")
                metadata_json = llm_response_text[metadata_start:].strip()
                metadata_json = re.sub(r'#[^\n]*', '', metadata_json)
                metadata_dict = json.loads(metadata_json)
                status = cra.upsert_collection_data(calledby="forcedetermine_relay_settings", collection=cfg.self_learning_collection(), doc_id=doc_id, document=llm_response_text, metadata=metadata_dict)
                logger.info(f" LLM 기반 릴레이 제어 결과 적용 완료")
            else:
                metadata_dict = {"status": "no_metadata_found", "raw_response": llm_response_text[:500]}
                
                status = cra.upsert_collection_data(calledby="forcedetermine_relay_settings", collection=cfg.self_learning_collection(), doc_id=doc_id, document=llm_response_text, metadata=metadata_dict)
                logger.info(f" LLM 응답 저장 완료 (METADATA 없음)")
        except Exception as e:
            logger.error(f"릴레이 제어 데이터 저장 중 오류: {e}")
            metadata_dict = {"error": f"저장 중 오류: {str(e)}", "raw_response": llm_response_text[:200],  "error_type": type(e).__name__}
            status = cra.upsert_collection_data(calledby="forcedetermine_relay_settings", collection=cfg.self_learning_collection(), doc_id=doc_id, document=llm_response_text, metadata=metadata_dict)
            logger.info(f" LLM 응답 저장 완료 (알수 없는 오류 발생)")
                
            if "error" in status:
                logger.error(f"############ ERROR ===============> 저장 실패: {status['error']}")
    else:
        logger.warning(f" LLM 응답 실패: 규칙 기반으로 대체")
        try:
            apply_rule_based_relay_control(relay_settings, sensor, optimal_conditions.get("sensor_means", {}), house_id)
           
            apply_learned_relay_means(relay_settings, optimal_conditions)
            logger.info(f" 규칙 기반 릴레이 제어 결과 적용 완료")
        except Exception as e:
            logger.error(f"규칙 기반 릴레이 설정 실패: {e}")

    validate_and_apply_safety_rules(relay_settings, farm_id, house_id)

    apply_time_based_settings(relay_settings, farm_id, house_id)            

    return relay_settings

# ----------------------------------------------------------------------
# LLM 응답을 파싱하여 벡터DB 저장 형식으로 변환
# ----------------------------------------------------------------------
def parse_llm_response_to_vectordb_format(llm_response_text):
    try:
        document = ""
        text     = ""
        metadata = {}

        if "DOCUMENT:" in llm_response_text:
            doc_start = llm_response_text.find("DOCUMENT:") + len("DOCUMENT:")
            doc_end = llm_response_text.find("TEXT:")
            if doc_end == -1:
                doc_end = llm_response_text.find("METADATA:")
            if doc_end == -1:
                doc_end = len(llm_response_text)
            document = llm_response_text[doc_start:doc_end].strip()

        if "TEXT:" in llm_response_text:
            text_start = llm_response_text.find("TEXT:") + len("TEXT:")
            text_end = llm_response_text.find("METADATA:")
            if text_end == -1:
                text_end = len(llm_response_text)
            text = llm_response_text[text_start:text_end].strip()

        if not text and document:
            text = document

        if "METADATA:" in llm_response_text:
            metadata_start = llm_response_text.find("METADATA:") + len("METADATA:")
            metadata_block = llm_response_text[metadata_start:].strip()

            match = re.search(r'\{[\s\S]*\}', metadata_block)
            if match:
                metadata_json_str = match.group(0)
                
                metadata_json_str = re.sub(r'//.*?\n|#.*?\n', '', metadata_json_str)

                try:
                    metadata = json.loads(metadata_json_str)
                except json.JSONDecodeError as e:
                    logger.warning(f"METADATA JSON 파싱 실패: {e}")
                    metadata = {
                        "error": "JSON 파싱 실패",
                        "raw_metadata": metadata_json_str[:500], 
                        "parsing_error": str(e)
                    }
            else:
                logger.warning("METADATA 블록에서 JSON 중괄호가 감지되지 않음")
                metadata = {
                    "error": "METADATA 블록 구조 이상",
                    "raw_metadata": metadata_block[:500]
                }

        if not document:
            document = "릴레이 제어 결정 완료"
        if not text:
            text = document
        if not metadata:
            metadata = {"status": "응답 파싱 완료"}

        if "relay_settings" not in metadata:
            metadata["relay_settings"] = {}
        
        return {
            "document": document,
            "text": text,
            "metadata": metadata
        }

    except Exception as e:
        logger.error(f"LLM 응답 파싱 중 예외 발생: {e}")
        return {
            "document": "릴레이 제어 처리 중 오류",
            "text": "릴레이 제어 처리 중 오류",
            "metadata": {
                "error": str(e),
                "raw_response": llm_response_text[:500]
            }
        }
    
# ---------------------------------------------------------
# ChromaDB 컬렉션에서 조건에 맞는 데이터를 필터링하여 반환
# ---------------------------------------------------------
def filter_chromadb_results(collection, conditions):
    try:
        all_results = cra.get_documents(collection_name=collection)
        
        if "error" not in all_results and "metadatas" in all_results:
            filtered_metadatas = []
            for metadata in all_results["metadatas"]:
                match = True
                for key, value in conditions.items():
                    if metadata.get(key) != value:
                        match = False
                        break
                if match:
                    filtered_metadatas.append(metadata)
            
            return {"metadatas": filtered_metadatas, "ids": []}
        else:
            return {"metadatas": [], "ids": []}
    except Exception as e:
        logger.warning(f" ChromaDB 필터링 중 오류: {e}")
        return {"metadatas": [], "ids": []}

# ---------------------------------------------------------
# 현재 환경 데이터 가져오기
# ---------------------------------------------------------
def get_current_environment_data(farm_id, house_id):
    try:
        logger.info(f" 농장 {farm_id}, 재배사 {house_id}의 현재 환경 데이터 조회 시작")
        current_hour = datetime.now().hour
        
        with db_session() as db:
            result  = dict(db.fetch_one(query=dbQry.GET_NOW_UNIT_INFO, vals=(farm_id, house_id)) or {})
            if not result:
                logger.info(f" 농장 {farm_id}, 재배사 {house_id}의 환경 데이터가 없습니다. 처리 건수: 0건")
                return None
                
            env_data = {
                "record_datetime": result["record_datetime"],
                "hour_of_day": datetime.strptime(str(result["record_datetime"]), "%Y-%m-%d %H:%M:%S").hour if result["record_datetime"] else current_hour,
                "indoor_temperature": result["indoor_temperature"],
                "indoor_humidity": result["indoor_humidity"],
                "outdoor_temperature": result["outdoor_temperature"],
                "outdoor_humidity": result["outdoor_humidity"],
                "co2": result.get("co2", result.get("co2")),
                "water_temperature": result["water_temperature"],
                "light_level": result["light_level"],
                "water_level": result["water_level"]
            }
            
            relay_result = db.fetch_one(query=dbQry.GET_LATEST_RELAY_INFO, vals=(farm_id, house_id))
            if relay_result:
                relay_data = {
                    "relay_1st_flag": relay_result["relay_1st_flag"],  
                    "relay_2st_flag": relay_result["relay_2st_flag"],  
                    "relay_3st_flag": relay_result["relay_3st_flag"],  
                    "relay_4st_flag": relay_result["relay_4st_flag"],  
                    "relay_5st_flag": relay_result["relay_5st_flag"],  
                    "relay_6st_flag": relay_result["relay_6st_flag"],  
                    "relay_7st_flag": relay_result["relay_7st_flag"],  
                    "relay_8st_flag": relay_result["relay_8st_flag"],  
                    "relay_9st_flag": relay_result["relay_9st_flag"],  
                    "relay_10st_flag": relay_result["relay_10st_flag"],
                    "relay_11st_flag": relay_result["relay_11st_flag"],
                    "relay_12st_flag": relay_result["relay_12st_flag"],
                    "relay_13st_flag": relay_result["relay_13st_flag"],
                    "relay_14st_flag": relay_result["relay_14st_flag"],
                    "relay_15st_flag": relay_result["relay_15st_flag"],
                    "relay_16st_flag": relay_result["relay_16st_flag"] 
                }
                env_data["current_relay"] = relay_data
        
        return env_data
        
    except Exception as e:
        logger.error(f" 환경 데이터 조회 중 오류: {e}")
        logger.error(traceback.format_exc())
        return None
    
# ---------------------------------------------------------
# ChromaDB에서 최적 환경 조건 가져오기
# ---------------------------------------------------------
def get_optimal_conditions(farm_id, house_id):
    try:
        logger.info(f" 농장 {farm_id}, 재배사 {house_id}의 최적 환경 조건 조회 시작")
        start_time = datetime.now()        
        current_hour = datetime.now().hour

        one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d 00:00:00")
        one_year_ago_dt = datetime.strptime(one_year_ago, "%Y-%m-%d %H:%M:%S")
        
        try:
            all_optimal = cra.get_documents(collection_name=cfg.optimal_collection())
            optimal_count = len(all_optimal.get("ids", [])) if "error" not in all_optimal else 0
            logger.info(f" optimal_collection 데이터 건수: {optimal_count}")
        except Exception as e:
            logger.warning(f" optimal_collection 데이터 건수 확인 중 오류: {e}")
            optimal_count = 0
            
        try:
            all_learned = cra.get_documents(collection_name=cfg.learned_collection())
            learned_count = len(all_learned.get("ids", [])) if "error" not in all_learned else 0
            logger.info(f" learned_collection 데이터 건수: {learned_count}")
        except Exception as e:
            logger.warning(f" learned_collection 데이터 건수 확인 중 오류: {e}")
            learned_count = 0
            
        use_manual = False
        try:
            settings_id = f"settings_{farm_id}_{house_id}"
            settings = cra.get_documents(collection_name=cfg.setting_collection(), ids=[settings_id])
            if settings and "metadatas" in settings:
                metadatas = settings["metadatas"]
                if isinstance(metadatas, list) and len(metadatas) > 0 and isinstance(metadatas[0], list):
                    if len(metadatas[0]) > 0:
                        use_manual = metadatas[0][0].get("use_manual_settings", False)
            
            logger.info(f" 농장 {farm_id}, 재배사 {house_id}의 운용 모드: {'수동' if use_manual else '자동'}")
        except Exception as e:
            logger.warning(f" 운용 모드 설정 조회 중 오류: {e}")
            use_manual = False
        
        optimal_results = filter_chromadb_results(
            cfg.optimal_collection(), 
            {"farm_id": farm_id, 
             "house_id": house_id, 
             "is_manual": use_manual, 
             "data_type": "optimal_conditions"}
        )

        if use_manual and (not optimal_results or "metadatas" not in optimal_results or not optimal_results["metadatas"]):
            logger.info(f" 수동 설정이 없어 자동 설정 검색")
            
            optimal_results = filter_chromadb_results(
                cfg.optimal_collection(), 
                {"farm_id": farm_id, 
                 "house_id": house_id, 
                 "is_manual": False, 
                 "data_type": "optimal_conditions"}
            )
        
        filtered_results = []
        if optimal_results and "metadatas" in optimal_results and optimal_results["metadatas"]:
            for item in optimal_results["metadatas"]:
                if "record_datetime" in item:
                    try:
                        item_date = datetime.strptime(item["record_datetime"], "%Y-%m-%d %H:%M:%S")
                        if item_date >= one_year_ago_dt:
                            filtered_results.append(item)
                    except Exception as e:
                        logger.warning(f"날짜 형식 오류: {item.get('record_datetime')} - {e}")
        
        if not filtered_results:
            logger.warning(f" optimal_collection에 데이터가 없습니다. \n learned_collection에서 대체 데이터를 찾습니다.")
            try:
                learned_data_list = chdr.get_learned_data(None, current_hour)
                if isinstance(learned_data_list, list) and learned_data_list:
                    learned_data = learned_data_list[0]
                else:
                    learned_data = {}
                if learned_data:
                    logger.info(f" learned_collection에서 {len(learned_data)}건의 데이터를 찾았습니다.")

                    docs = learned_data.get("documents", [])
                    if docs:
                        optimal_conditions = extract_optimal_from_learned(docs[0], current_hour)
                    else:
                        logger.warning("learned_data에 문서가 없습니다. 기본값을 사용합니다.")
                        optimal_conditions = {}

                    logger.info(f" learned_collection에서 최적 환경 조건 추출 완료")
                    return optimal_conditions
            except Exception as e:
                logger.error(f" learned_collection 대체 데이터 검색 중 오류: {e}")
                logger.error(traceback.format_exc())

            default_conditions = optimal_condition_from_postgresql(farm_id, house_id)
                
            is_daytime = 6 <= current_hour < 18
            
            default_relay_settings = {
                "relay_1st_flag": 0.8 if not is_daytime else 0.2,  # 수온히터 (야간에 주로 가동)
                "relay_2st_flag": 0.6,                             # 분무모터 (보통 가동)
                "relay_5st_flag": 0.7 if is_daytime else 0.3,      # 흡입모터 (주간에 주로 가동)
                "relay_6st_flag": 0.7 if is_daytime else 0.3,      # 배출모터 (주간에 주로 가동)
                "relay_7st_flag": 0.9 if is_daytime else 0.1,      # 조명토글 (주간에 거의 항상 가동)
                "relay_9st_flag": 0.8 if not is_daytime else 0.2,  # 내부히터 (야간에 주로 가동)
                "relay_10st_flag": 0.7,                            # 순환밸브 (보통 가동)
            }
            
            default_conditions["relay_means"] = default_relay_settings
            logger.info(f" 기본 최적 환경 조건 사용")
            return default_conditions
        
        optimal_data = filtered_results[0]
        
        optimal_conditions = {
            "sensor_means": json.loads(optimal_data.get("sensor_means", "{}")),
            "relay_means": json.loads(optimal_data.get("relay_means", "{}"))
        }
        
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        logger.info(f" 농장 {farm_id}, 재배사 {house_id}의 최적 환경 조건 조회 완료: 센서 데이터 {len(optimal_conditions['sensor_means'])}개, 릴레이 데이터 {len(optimal_conditions['relay_means'])}개 (처리시간: {processing_time:.3f}초)")
        return optimal_conditions
        
    except Exception as e:
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        logger.error(f" 최적 환경 조건 조회 중 오류: {e}")
        logger.error(traceback.format_exc())
        logger.info(f" 농장 {farm_id}, 재배사 {house_id}의 최적 환경 조건 조회 실패 (처리시간: {processing_time:.3f}초)")
        return None

# --------------------------------------------------------------------------
# Optimal 조건을 읽어 온다.
# --------------------------------------------------------------------------
def optimal_condition_from_postgresql(farm_id, house_id):
    with db_session() as db:
        rows = db.fetch_all(query=dbQry.GET_OPTIMAL_CONDITION, vals=(farm_id, house_id), as_dict=True)
    if rows:
        row = rows[0]
        return {
            "sensor_means": {
                "적정최저온도": row["온도최저"],
                "적정온도": row["온도적정"],
                "적정최고온도": row["온도최고"],
                "적정최저습도": row["습도최저"],
                "적정습도": row["습도적정"],
                "적정최고습도": row["습도최고"],
                "적정최저co2": row.get("co2최저", row.get("co2최저")),
                "적정co2": row.get("co2적정", row.get("co2적정")),
                "적정최고co2": row.get("co2최고", row.get("co2최고")),
                "적정최저수온": row["수온최저"],
                "적정수온": row["수온적정"],
                "적정최고수온": row["수온최고"],
                "적정광량": 500
            },
            "growth_means": {},
            "relay_means": {}
        }

# ---------------------------------------------------------
# 학습 데이터에서 최적 조건 추출
# ---------------------------------------------------------
def extract_optimal_from_learned(learned_data, current_hour):
    try:
        start_time = datetime.now()        
        optimal_conditions = {
            "sensor_means": {},
            "relay_means": {}
        }
        
        if isinstance(learned_data, list) and len(learned_data) > 0:
            docs = learned_data.get("documents", [])
            if docs:
                optimal_conditions = extract_optimal_from_learned(docs[0], current_hour)
            else:
                logger.warning("learned_data에 문서가 없습니다. 기본값을 사용합니다.")
                optimal_conditions = {}
            if optimal_conditions:
                logger.info(f" learned_collection에서 최적 환경 조건 추출 완료")
                return optimal_conditions
        else:
            logger.warning(" learned_data가 비어 있거나 형식이 올바르지 않음")
                    
        if "optimal_conditions" in learned_data:
            try:
                optimal_data = learned_data["optimal_conditions"]
                if isinstance(optimal_data, str):
                    optimal_data = json.loads(optimal_data)

                is_daytime = 6 <= current_hour < 18

                if "temperature" in optimal_data:
                    temp_data = optimal_data["temperature"]["day" if is_daytime else "night"]
                    optimal_conditions["sensor_means"]["indoor_temperature_value"] = temp_data.get("optimal", 22)

                if "humidity" in optimal_data:
                    humid_data = optimal_data["humidity"]["day" if is_daytime else "night"]
                    optimal_conditions["sensor_means"]["indoor_humidity_value"] = humid_data.get("optimal", 70)
                
                if "co2" in optimal_data:
                    optimal_conditions["sensor_means"]["co2_concentration_value"] = optimal_data["co2"].get("optimal", 800)
                
                if "water_temperature" in optimal_data:
                    optimal_conditions["sensor_means"]["water_temperature_value"] = optimal_data["water_temperature"].get("optimal", 20)
                
                if "light_level" in optimal_data:
                    optimal_conditions["sensor_means"]["light_level_value"] = optimal_data["light_level"].get("optimal", 500)
                
                if "relay_settings" in optimal_data:
                    for relay_key, settings in optimal_data["relay_settings"].items():
                        normalized_key = f"relay_{relay_key}st_flag"
                        ratio = settings.get("day_ratio" if is_daytime else "night_ratio", 0.5)
                        optimal_conditions["relay_means"][normalized_key] = ratio
                
                has_data = False
                for key, value in optimal_conditions["sensor_means"].items():
                    if value > 0:
                        has_data = True
                        break
                
                if has_data:
                    logger.info(f" learned_data의 optimal_conditions에서 유효한 데이터 추출됨")
                    return optimal_conditions
            except Exception as e:
                logger.warning(f" learned_data의 optimal_conditions 처리 중 오류: {e}")
        
        if "document" in learned_data:
            try:
                document_json = json.loads(learned_data["document"])
                
                if "time_patterns" in document_json:
                    time_patterns = document_json.get("time_patterns", {})
                    
                    if isinstance(time_patterns, str):
                        time_patterns = json.loads(time_patterns)
                        
                    daily_patterns = time_patterns.get("daily", {})
                    
                    hour_str = str(current_hour)
                    if "temperature" in daily_patterns and hour_str in daily_patterns["temperature"]:
                        optimal_conditions["sensor_means"]["indoor_temperature_value"] = daily_patterns["temperature"][hour_str]
                    if "humidity" in daily_patterns and hour_str in daily_patterns["humidity"]:
                        optimal_conditions["sensor_means"]["indoor_humidity_value"] = daily_patterns["humidity"][hour_str]
                    if "co2" in daily_patterns and hour_str in daily_patterns["co2"]:
                        optimal_conditions["sensor_means"]["co2_concentration_value"] = daily_patterns["co2"][hour_str]
                    if "relay_usage" in daily_patterns:
                        relay_usage = daily_patterns["relay_usage"]
                        
                        for relay_key, hours in relay_usage.items():
                            if hour_str in hours:
                                optimal_conditions["relay_means"][relay_key] = hours[hour_str]

                if "optimal_conditions" in document_json:
                    optimal_data = document_json.get("optimal_conditions", {})
                    
                    if isinstance(optimal_data, str):
                        optimal_data = json.loads(optimal_data)
                        
                    if "temperature" in optimal_data:
                        is_daytime = 6 <= current_hour < 18
                        temp_data = optimal_data["temperature"]["day" if is_daytime else "night"]
                        optimal_conditions["sensor_means"]["indoor_temperature_value"] = temp_data.get("optimal", 22)
                        
                    if "humidity" in optimal_data:
                        is_daytime = 6 <= current_hour < 18
                        humid_data = optimal_data["humidity"]["day" if is_daytime else "night"]
                        optimal_conditions["sensor_means"]["indoor_humidity_value"] = humid_data.get("optimal", 70)
                        
                    if "co2" in optimal_data:
                        optimal_conditions["sensor_means"]["co2_concentration_value"] = optimal_data["co2"].get("optimal", 800)
                        
                    if "water_temperature" in optimal_data:
                        optimal_conditions["sensor_means"]["water_temperature_value"] = optimal_data["water_temperature"].get("optimal", 20)
                        
                    if "light_level" in optimal_data:
                        optimal_conditions["sensor_means"]["light_level_value"] = optimal_data["light_level"].get("optimal", 500)
                        
                    if "relay_settings" in optimal_data:
                        is_daytime = 6 <= current_hour < 18
                        for relay_key, settings in optimal_data["relay_settings"].items():
                            optimal_conditions["relay_means"][relay_key] = settings.get("day_ratio" if is_daytime else "night_ratio", 0.5)
            except:
                pass

        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
                        
        return optimal_conditions
    except Exception as e:
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        logger.error(f" 학습 데이터에서 최적 조건 추출 중 오류: {e}")
        logger.error(traceback.format_exc())
        logger.error(f" 시간대 {current_hour}시 학습 데이터에서 최적 조건 추출 실패 (처리시간: {processing_time:.3f}초)")
        return {"sensor_means": {}, "relay_means": {}}
    
# ---------------------------------------------------------
# 미리 정의된 릴레이 조합을 설정에 적용
# ---------------------------------------------------------
def apply_relay_combination(relay_settings, combination_name):
    if combination_name in cfg.RELAY_COMBINATIONS:
        combination = cfg.RELAY_COMBINATIONS[combination_name]
        
        key_mapping = {
            "air_circulation_valve_flag": "relay_10st_flag",  
            "air_intake_valve_flag": "relay_11st_flag",       
            "air_exhaust_valve_flag": "relay_14st_flag"     
        }
        
        for src_key, value in combination.items():
            if src_key in key_mapping:
                relay_settings[key_mapping[src_key]] = value
                
        logger.info(f" 릴레이 조합 적용: {combination_name}")

# ---------------------------------------------------------
# 현재 환경 데이터에서 센서 값 추출
# ---------------------------------------------------------
def extract_current_sensor_values(current_env):
    return {
        "current_temp": cfg.clean_sensor_value(current_env.get("indoor_temperature")),
        "current_humidity": cfg.clean_sensor_value(current_env.get("indoor_humidity")),
        "current_co2": cfg.clean_sensor_value(current_env.get("co2")),
        "current_water_temp": cfg.clean_sensor_value(current_env.get("water_temperature")),
        "current_light": cfg.clean_sensor_value(current_env.get("light_level")),
        "current_water_level": cfg.clean_sensor_value(current_env.get("water_level")),
        "outdoor_temp": cfg.clean_sensor_value(current_env.get("outdoor_temperature")),
        "outdoor_humidity": cfg.clean_sensor_value(current_env.get("outdoor_humidity"))
    }

# ---------------------------------------------------------
# 시간 기반 릴레이 설정
# ---------------------------------------------------------
def apply_time_based_settings(relay_settings, farm_id, house_id):
    now = datetime.now().time()
    
    with db_session() as db:
        light_set = db.fetch_all(query=dbQry.GET_LIGHT_IRRIGATION, vals=(farm_id, house_id, "light"), as_dict=True)
        relay_settings["조명토글"] = any(
            cfg.to_time(row["strt_time"]) <= now <= cfg.to_time(row["fnsh_time"])
            for row in light_set
        )

        water_set = db.fetch_all(query=dbQry.GET_LIGHT_IRRIGATION, vals=(farm_id, house_id, "water"), as_dict=True)
        relay_settings["관수토글"] = any(
            cfg.to_time(row["strt_time"]) <= now <= cfg.to_time(row["fnsh_time"])
            for row in water_set
        )

# ---------------------------------------------------------
# 시간 기반 예외처리 릴레이 설정 
# ---------------------------------------------------------
def apply_time_based_settings_exception(farm_id, house_id):
    now = datetime.now().time()
    
    with db_session() as db:
        light_get = db.fetch_all(query=dbQry.GET_LIGHT_IRRIGATION, vals=(farm_id, house_id, "light"), as_dict=True)
        light_set = any(cfg.to_time(row["strt_time"]) <= now <= cfg.to_time(row["fnsh_time"]) for row in light_get)
        if house_id == 2:
            rst = cfg.search_relay_function('rfm_e','function_name','조명토글','relay_name')
        else:
            rst = cfg.search_relay_function('rfm','function_name','조명토글','relay_name')
        db.execute_query(f"UPDATE RELAY_L_RECORDING SET {rst} = {light_set} WHERE farm_id = {farm_id} AND hous_id = {house_id} AND recd_dttm = (SELECT max(recd_dttm) FROM RELAY_L_RECORDING WHERE farm_id = {farm_id} AND hous_id = {house_id})")

        water_get = db.fetch_all(query=dbQry.GET_LIGHT_IRRIGATION, vals=(farm_id, house_id, "water"), as_dict=True)
        water_set = any(cfg.to_time(row["strt_time"]) <= now <= cfg.to_time(row["fnsh_time"]) for row in water_get)
        if house_id == 2:
            rst = cfg.search_relay_function('rfm_e','function_name','관수토글','relay_name')
        else:
            rst = cfg.search_relay_function('rfm','function_name','관수토글','relay_name')
        db.execute_query(f"UPDATE RELAY_L_RECORDING SET {rst} = {water_set} WHERE farm_id = {farm_id} AND hous_id = {house_id} AND recd_dttm = (SELECT max(recd_dttm) FROM RELAY_L_RECORDING WHERE farm_id = {farm_id} AND hous_id = {house_id})")

# ---------------------------------------------------------
# 학습된 평균 릴레이 상태 적용
# ---------------------------------------------------------
def apply_learned_relay_means(relay_settings, optimal_conditions):
    if "relay_means" in optimal_conditions:
        try:
            relay_means = optimal_conditions["relay_means"]
            if isinstance(relay_means, str):
                relay_means = json.loads(relay_means)
                
            for relay_key, mean_value in relay_means.items():
                if relay_key in relay_settings:
                    if mean_value > 0.7 and relay_key not in [
                        "relay_3st_flag", "relay_4st_flag",
                        "relay_8st_flag"                    
                    ]:
                        if relay_settings[relay_key] is False:
                            relay_settings[relay_key] = True
        except Exception as e:
            logger.warning(f"릴레이 평균값 적용 중 오류: {e}")
            
# ---------------------------------------------------------
# 한글 기능명 기반 릴레이 설정을 relay_*st_flag 형태로 변환
# ---------------------------------------------------------
def convert_functional_names_to_relay_flags(relay_settings, farm_id, house_id):
    converted_settings = {}
    
    # 농장별 릴레이 매핑 가져오기
    # relay_mapping = cfg.get_relay_mapping_for_farm(farm_id) if farm_id else cfg.RELAY_FIELD_MAPPING
    if house_id == 2:
        relay_mapping = cfg.RELAY_FIELD_MAPPING_E
    else:
        relay_mapping = cfg.RELAY_FIELD_MAPPING
        
    korean_to_relay_mapping = {}
    for key, value in relay_mapping.items():
        if key.startswith('relay_') and key.endswith('_flag'):
            korean_name = value[1] 
            korean_to_relay_mapping[korean_name] = key

    for korean_name, relay_flag in korean_to_relay_mapping.items():
        if korean_name in relay_settings:
            converted_settings[relay_flag] = relay_settings[korean_name]

    for key, value in relay_settings.items():
        if key.startswith('relay_') and key.endswith('_flag'):
            if key not in converted_settings: 
                converted_settings[key] = value

    all_relay_flags = [key for key in relay_mapping.keys() 
                      if key.startswith('relay_') and key.endswith('_flag')]
    
    for flag in all_relay_flags:
        if flag not in converted_settings:
            converted_settings[flag] = False
    
    return converted_settings

# ---------------------------------------------------------
# 릴레이 설정을 DB 저장용 params로 변환
# ---------------------------------------------------------
def build_relay_params(farm_id, house_id, current_time, converted_settings):
    if house_id != 2:
        params = [farm_id, house_id, current_time]
        params.extend([converted_settings.get(f"relay_{i}st_flag", 'N/A') for i in range(1, 17)])
    else:
        params = [current_time]
        params.extend([converted_settings.get(f"relay_{i}st_flag", 'N/A') for i in range(1, 16)])
        
    return params

# ---------------------------------------------------------
# 릴레이 설정값을 DB에 저장
# ---------------------------------------------------------
def save_relay_settings(farm_id, house_id, relay_settings):
    try:
        logger.info(f" 농장 {farm_id}, 재배사 {house_id}의 릴레이 설정 저장 시작")
        start_time = datetime.now()
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        converted_settings = convert_functional_names_to_relay_flags(relay_settings, farm_id, house_id)
        params = build_relay_params(farm_id, house_id, current_time, converted_settings)

        with db_session() as db:
            latest_relay = db.fetch_one(query=dbQry.GET_LATEST_RELAY_INFO, vals=(farm_id, house_id))
            
        farm_name, house_name = cfg.get_farm_name(farm_id=farm_id, house_id=house_id)
        
        relay_log = log_relay_settings_change_with_farm_mapping(farm_name, house_name, current_time, 
                                                             latest_relay, converted_settings, farm_id, house_id)
        
        with db_session() as db:
            if house_id != 2:
                db.execute_query(dbQry.SET_RELAY_VALUE, params)
            else:
                db.execute_query(dbQry.SET_RELAY_VALUE_E, params)

        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        return relay_log
        
    except Exception as e:
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        logger.error(f" 릴레이 설정 저장 중 오류: {e}")
        logger.error(traceback.format_exc())
        logger.info(f" 농장 {farm_id}, 재배사 {house_id}의 릴레이 설정 저장 실패 (처리시간: {processing_time:.3f}초)")
        return False

# ---------------------------------------------------------
# 농장별 매핑을 지원하는 로그 함수
# ---------------------------------------------------------
def log_relay_settings_change_with_farm_mapping(farm_name, house_name, current_time, 
                                               latest_relay, converted_settings, farm_id=None, house_id=None):
    # relay_mapping = cfg.get_relay_mapping_for_farm(farm_id)
    if house_id == 2:
        relay_mapping = cfg.RELAY_FIELD_MAPPING_E
    else:
        relay_mapping = cfg.RELAY_FIELD_MAPPING
        
    # 주요 릴레이만 필터링 
    main_relays = [key for key in relay_mapping.keys() 
                  if key.startswith('relay_') and key.endswith('_flag')]

    relay_changes = []
    for relay_key in main_relays:
        if relay_key in relay_mapping:
            relay_name = relay_mapping[relay_key][1] 
            old_value = latest_relay.get(relay_key, 'N/A')
            new_value = converted_settings.get(relay_key, 'N/A')
            relay_changes.append(f" - {relay_name}: {old_value} -> {new_value}")
    
    relay_log = f"릴레이셋팅 ===> {farm_name} 농장, {house_name} 재배사, {current_time}에\n" + "\n".join(relay_changes)
    
    return relay_log

# ---------------------------------------------------------
# 환경 상태 판단 함수
# 현재 센서값과 최적값을 비교하여 환경 상태를 판단
# ---------------------------------------------------------
def get_environmental_status(sensors, optimal_values):
    temp_status = "적정"
    if sensors["current_temp"] > optimal_values.get("적정최고온도", 30):
        temp_status = "높음"
    elif sensors["current_temp"] < optimal_values.get("적정최저온도", 15):
        temp_status = "낮음"
    
    humidity_status = "적정" 
    if sensors["current_humidity"] > optimal_values.get("적정최고습도", 80):
        humidity_status = "높음"
    elif sensors["current_humidity"] < optimal_values.get("적정최저습도", 50):
        humidity_status = "낮음"
    
    co2_status = "정상"
    if sensors["current_co2"] > optimal_values.get("적정최고co2", 1000):
        co2_status = "높음"
    
    outdoor_temp_status = "적정"
    if sensors["outdoor_temp"] > optimal_values.get("적정최고온도", 30):
        outdoor_temp_status = "높음"
    elif sensors["outdoor_temp"] < optimal_values.get("적정최저온도", 15):
        outdoor_temp_status = "낮음"
    
    outdoor_humidity_status = "적정"
    if sensors["outdoor_humidity"] > optimal_values.get("적정최고습도", 80):
        outdoor_humidity_status = "높음"
    elif sensors["outdoor_humidity"] < optimal_values.get("적정최저습도", 50):
        outdoor_humidity_status = "낮음"
    
    return {
        "내부온도": temp_status,
        "내부습도": humidity_status,
        "co2": co2_status,
        "외부온도": outdoor_temp_status,
        "외부습도": outdoor_humidity_status
    }

# ---------------------------------------------------------
# 안전 규칙 적용 함수 (신규)
# 필수 안전 규칙 적용
#  1. 수온히터와 내부히터 동시 On 금지
#  2. 내부히터와 히터밸브 동일 상태 유지
# ---------------------------------------------------------
def apply_safety_rules(relay_settings):
    if relay_settings["수온히터"] and relay_settings["내부히터"]:
        relay_settings["수온히터"] = False
        logger.warning("안전규칙 적용: 수온히터와 내부히터 동시 On 방지 - 수온히터 Off")
    
    relay_settings["히터밸브"] = relay_settings["내부히터"]

# ---------------------------------------------------------
# 공기순환 모드 적용 함수
#     5가지 공기순환 모드 중 하나를 적용
# ---------------------------------------------------------
def apply_air_circulation_mode(relay_settings, mode, status_info="", unique_id="", house_id=None):
    # 모든 순환 관련 릴레이 초기화
    circulation_relays = {
        "흡입모터": False, "배출모터": False, "순환밸브": False,
        "흡입밸브": False, "배출밸브": False
    }
    
    # 모드별 설정
    mode_settings = {
        "혼합순환": {"흡입모터": True, "배출모터": True, "순환밸브": True, "흡입밸브": True, "배출밸브": True},
        "내부순환": {"흡입모터": True, "배출모터": True, "순환밸브": True},
        "외부순환": {"흡입모터": True, "배출모터": True, "흡입밸브": True, "배출밸브": True},
        "흡입순환": {"흡입모터": True, "흡입밸브": True},
        "배출순환": {"배출모터": True, "배출밸브": True}
    }
    
    # 모드 설정 적용
    if mode in mode_settings:
        circulation_relays.update(mode_settings[mode])
    else:
        # 기본순환
        circulation_relays.update({"흡입모터": True, "배출모터": True, "순환밸브": True})
        mode = "기본순환"
    
    # 릴레이 설정에 적용
    cfg.set_relay_basic_settings(relay_settings, **circulation_relays)
    
    # 로그 출력
    log_relay_decision(status_info, mode, unique_id, relay_settings, house_id)

# ---------------------------------------------------------
# 릴레이 결정에 대한 통합 로깅
# ---------------------------------------------------------
def log_relay_decision(status_info, mode, unique_id, relay_settings, house_id=None):
    if house_id == 2:
        relay_mapping = cfg.RELAY_FIELD_MAPPING_E
    else:
        relay_mapping = cfg.RELAY_FIELD_MAPPING
    
    main_relays = [key for key in relay_mapping.keys() 
                  if key.startswith('relay_') and key.endswith('_flag')]
   
    active_relays = []
    inactive_relays = []
    
    for relay_key in main_relays:
        if relay_key in relay_mapping:
            relay_name = relay_mapping[relay_key][1]  # 간단한 이름
            relay_display = f"{relay_name}({relay_key})"
            
            # 한글명으로 relay_settings에서 찾기 (기존 로직과 호환성)
            korean_name = relay_name
            if korean_name in relay_settings:
                if relay_settings[korean_name] is True:
                    active_relays.append(relay_display)
                elif relay_settings[korean_name] is False:
                    inactive_relays.append(relay_display)
            # relay_key로 직접 찾기
            elif relay_key in relay_settings:
                if relay_settings[relay_key] is True:
                    active_relays.append(relay_display)
                elif relay_settings[relay_key] is False:
                    inactive_relays.append(relay_display)
    
    logger.info(f"--->>>릴레이 제어 결정 [{unique_id}]:")
    logger.info(f"      환경상태: {status_info}")
    logger.info(f"      순환모드: {mode}")
    logger.info(f"      활성릴레이: {', '.join(active_relays) if active_relays else '없음'}")

# ==============================================================================================================
# 판단 제어 로직 - 리팩토링 버전
# ==============================================================================================================
# ---------------------------------------------------------
# 규칙 기반 릴레이 제어 함수
# 센서값 162가지 조합에 대한 처리
# ---------------------------------------------------------
def apply_rule_based_relay_control(relay_settings, sensors, optimal_values, house_id=None):
    status = get_environmental_status(sensors, optimal_values)
    
    status_str = f"내부온도:{status['내부온도']}, 내부습도:{status['내부습도']}, co2:{status['co2']}, 외부온도:{status['외부온도']}, 외부습도:{status['외부습도']}"
    combination_key = f"{status['내부온도']}_{status['내부습도']}_{status['co2']}_{status['외부온도']}_{status['외부습도']}"
    
    # 위험 상황 처리 (개선된 버전 사용)
    if handle_danger_situations(relay_settings, sensors, optimal_values, status_str, house_id):
        logger.info(f"위험상황 제어 완료 - 조합: {combination_key}")
        # 위험 상황에서도 수온히터 특별 제어 적용
        apply_water_heater_special_control(relay_settings, sensors, optimal_values)
        return
    
    # 1순위: 적정 상황 판단 (빠른 처리)
    if (status["내부온도"] == "적정" and status["내부습도"] == "적정" and 
        status["외부온도"] == "적정" and status["외부습도"] == "적정"):
        apply_air_circulation_mode(relay_settings, "혼합순환", status_str, "OPTIMAL_001", house_id)
        apply_safety_rules(relay_settings)
        apply_water_heater_special_control(relay_settings, sensors, optimal_values)
        logger.info(f"적정상황 제어 완료 - 전체적정 - 조합: {combination_key}")
        return
    
    if (status["내부온도"] == "적정" and status["내부습도"] == "적정" and 
        (status["외부온도"] != "적정" or status["외부습도"] != "적정")):
        apply_air_circulation_mode(relay_settings, "내부순환", status_str, "OPTIMAL_002", house_id)
        apply_safety_rules(relay_settings)
        apply_water_heater_special_control(relay_settings, sensors, optimal_values)
        logger.info(f"적정상황 제어 완료 - 내부적정 - 조합: {combination_key}")
        return
    
    if ((status["내부온도"] != "적정" or status["내부습도"] != "적정") and 
        status["외부온도"] == "적정" and status["외부습도"] == "적정"):
        apply_air_circulation_mode(relay_settings, "외부순환", status_str, "OPTIMAL_003", house_id)
        apply_safety_rules(relay_settings)
        apply_water_heater_special_control(relay_settings, sensors, optimal_values)
        logger.info(f"적정상황 제어 완료 - 외부적정 - 조합: {combination_key}")
        return

    # 2순위: 세부 조합별 처리 (9가지 온도-습도 조합 × 2가지 CO2 = 18가지)
    if status["내부온도"] == "높음" and status["내부습도"] == "높음":
        _handle_hot_humid_case(relay_settings, status, status_str, house_id)
    elif status["내부온도"] == "높음" and status["내부습도"] == "적정":
        _handle_hot_normal_humid_case(relay_settings, status, status_str, house_id)
    elif status["내부온도"] == "높음" and status["내부습도"] == "낮음":
        _handle_hot_dry_case(relay_settings, status, status_str, house_id)
    elif status["내부온도"] == "적정" and status["내부습도"] == "높음":
        _handle_normal_temp_humid_case(relay_settings, status, status_str, house_id)
    elif status["내부온도"] == "적정" and status["내부습도"] == "낮음":
        _handle_normal_temp_dry_case(relay_settings, status, status_str, house_id)
    elif status["내부온도"] == "낮음" and status["내부습도"] == "높음":
        _handle_cold_humid_case(relay_settings, status, status_str, house_id)
    elif status["내부온도"] == "낮음" and status["내부습도"] == "적정":
        _handle_cold_normal_humid_case(relay_settings, status, status_str, house_id)
    elif status["내부온도"] == "낮음" and status["내부습도"] == "낮음":
        _handle_cold_dry_case(relay_settings, status, status_str, house_id)
    else:
        logger.warning(f"예상치 못한 조합 발생: {combination_key}")
        apply_air_circulation_mode(relay_settings, "혼합순환", status_str, "RULE_UNEXPECTED", house_id)
    
    apply_safety_rules(relay_settings)
    # 모든 케이스에서 수온히터 특별 제어 적용
    apply_water_heater_special_control(relay_settings, sensors, optimal_values)
    logger.info(f"규칙기반 제어 완료 - 조합: {combination_key}")

    
# ---------------------------------------------------------
# 위험 상황 판단 및 처리 함수 (우선순위 기반)
# ---------------------------------------------------------
def handle_danger_situations(relay_settings, sensors, optimal_values, status_str, house_id=None):
    current_temp = sensors["current_temp"]
    current_humidity = sensors["current_humidity"]
    
    max_temp_threshold = optimal_values.get("적정최고온도", 30)
    min_temp_threshold = optimal_values.get("적정최저온도", 15)
    max_humidity_threshold = optimal_values.get("적정최고습도", 80)
    min_humidity_threshold = optimal_values.get("적정최저습도", 50)
    
    temp_danger = current_temp > max_temp_threshold
    temp_cold = current_temp < min_temp_threshold
    humidity_danger = current_humidity > max_humidity_threshold
    humidity_low = current_humidity < min_humidity_threshold
    
    danger_cases = [
        {
            "condition": temp_danger and humidity_danger,
            "settings": {"배수밸브": True, "수온히터": False, "내부히터": False, "분무모터": False},
            "mode": "배출순환",
            "message": f"온도위험:{current_temp}>{max_temp_threshold}, 습도위험:{current_humidity}>{max_humidity_threshold}",
            "id": "DANGER_TEMP_HUMIDITY",
            "priority": "순위1: 온도위험+습도위험"
        },
        {
            "condition": humidity_danger and temp_cold,
            "settings": {"수온히터": True, "히터밸브": False, "내부히터": False, "분무모터": False, "배수밸브": False},
            "mode": "내부순환",
            "message": f"습도위험:{current_humidity}>{max_humidity_threshold}, 저온:{current_temp}<{min_temp_threshold}",
            "id": "DANGER_HUMIDITY_COLD",
            "priority": "순위2: 습도위험+내부저온"
        },
        {
            "condition": humidity_danger and temp_danger,
            "settings": {"배수밸브": True, "수온히터": False, "내부히터": False, "분무모터": False},
            "mode": "배출순환",
            "message": f"습도위험:{current_humidity}>{max_humidity_threshold}, 고온:{current_temp}>{max_temp_threshold}",
            "id": "DANGER_HUMIDITY_HOT",
            "priority": "순위3: 습도위험+내부고온"
        },
        {
            "condition": temp_danger and humidity_low,
            "settings": {"분무모터": True, "배수밸브": True, "수온히터": False, "내부히터": False},
            "mode": "배출순환",
            "message": f"온도위험:{current_temp}>{max_temp_threshold}, 저습:{current_humidity}<{min_humidity_threshold}",
            "id": "DANGER_TEMP_DRY",
            "priority": "순위4: 온도위험+내부저습"
        },
        {
            "condition": temp_danger and humidity_danger,
            "settings": {"배수밸브": True, "수온히터": False, "내부히터": False, "분무모터": False},
            "mode": "배출순환",
            "message": f"온도위험:{current_temp}>{max_temp_threshold}, 다습:{current_humidity}>{max_humidity_threshold}",
            "id": "DANGER_TEMP_HUMID",
            "priority": "순위5: 온도위험+내부다습"
        }
    ]
    
    # 위험 상황 처리
    for case in danger_cases:
        if case["condition"]:
            cfg.set_relay_basic_settings(relay_settings, **case["settings"])
            apply_air_circulation_mode(relay_settings, case["mode"], 
                                             status_str + f" ({case['message']})", case["id"], house_id)
            apply_safety_rules(relay_settings)
            logger.info(f"위험상황 제어 완료 - {case['priority']}")
            return True
    
    # 개별 위험 상황 처리
    if temp_danger:
        settings = {"배수밸브": True, "수온히터": False, "내부히터": False}
        if humidity_low:
            settings["분무모터"] = True
        else:
            settings["분무모터"] = False
        
        cfg.set_relay_basic_settings(relay_settings, **settings)
        apply_air_circulation_mode(relay_settings, "배출순환", 
                                         status_str + f" (온도위험:{current_temp}>{max_temp_threshold})", 
                                         "DANGER_TEMP_ONLY", house_id)
        apply_safety_rules(relay_settings)
        logger.info(f"위험상황 제어 완료 - 개별: 온도위험")
        return True
    
    elif humidity_danger:
        cfg.set_relay_basic_settings(relay_settings, 
                               배수밸브=True, 분무모터=False, 수온히터=False, 내부히터=False)
        apply_air_circulation_mode(relay_settings, "배출순환", 
                                         status_str + f" (습도위험:{current_humidity}>{max_humidity_threshold})", 
                                         "DANGER_HUMIDITY_ONLY", house_id)
        apply_safety_rules(relay_settings)
        logger.info(f"위험상황 제어 완료 - 개별: 습도위험")
        return True
    
    return False

# ---------------------------------------------------------
# 고온 고습 처리 (CO2 정상/높음 × 외부조건 9가지 = 18가지)
# ---------------------------------------------------------
def _handle_hot_humid_case(relay_settings, status, status_str, house_id=None):
    cfg.set_relay_basic_settings(relay_settings, 배수밸브=True, 수온히터=False, 분무모터=False, 내부히터=True)
    
    if status["co2"] == "정상":
        if status["외부온도"] == "높음" and status["외부습도"] == "높음":
            apply_air_circulation_mode(relay_settings, "배출순환", status_str, "RULE_101A", house_id)
        elif status["외부온도"] == "높음" and status["외부습도"] == "적정":
            apply_air_circulation_mode(relay_settings, "배출순환", status_str, "RULE_101B", house_id)
        elif status["외부온도"] == "높음" and status["외부습도"] == "낮음":
            apply_air_circulation_mode(relay_settings, "외부순환", status_str, "RULE_101C", house_id)
        elif status["외부온도"] == "적정" and status["외부습도"] == "높음":
            apply_air_circulation_mode(relay_settings, "배출순환", status_str, "RULE_101D", house_id)
        elif status["외부온도"] == "적정" and status["외부습도"] == "낮음":
            apply_air_circulation_mode(relay_settings, "외부순환", status_str, "RULE_101E", house_id)
        elif status["외부온도"] == "낮음" and status["외부습도"] == "높음":
            apply_air_circulation_mode(relay_settings, "배출순환", status_str, "RULE_101F", house_id)
        elif status["외부온도"] == "낮음" and status["외부습도"] == "적정":
            apply_air_circulation_mode(relay_settings, "외부순환", status_str, "RULE_101G", house_id)
        elif status["외부온도"] == "낮음" and status["외부습도"] == "낮음":
            apply_air_circulation_mode(relay_settings, "외부순환", status_str, "RULE_101H", house_id)
    
    elif status["co2"] == "높음":
        # CO2 높으면 무조건 외부순환 (환기 우선)
        apply_air_circulation_mode(relay_settings, "외부순환", status_str, f"RULE_102_{status['외부온도']}_{status['외부습도']}", house_id)

# ---------------------------------------------------------
# 고온 적정습도 처리 (18가지)
# ---------------------------------------------------------
def _handle_hot_normal_humid_case(relay_settings, status, status_str, house_id=None):
    cfg.set_relay_basic_settings(relay_settings, 배수밸브=True, 수온히터=False, 내부히터=False, 분무모터=False)
    
    if status["co2"] == "정상":
        if status["외부온도"] == "높음":
            apply_air_circulation_mode(relay_settings, "배출순환", status_str, f"RULE_201A_{status['외부습도']}", house_id)
        elif status["외부온도"] == "적정":
            apply_air_circulation_mode(relay_settings, "외부순환", status_str, f"RULE_201B_{status['외부습도']}", house_id)
        elif status["외부온도"] == "낮음":
            apply_air_circulation_mode(relay_settings, "외부순환", status_str, f"RULE_201C_{status['외부습도']}", house_id)
    
    elif status["co2"] == "높음":
        apply_air_circulation_mode(relay_settings, "외부순환", status_str, f"RULE_202_{status['외부온도']}_{status['외부습도']}", house_id)

# ---------------------------------------------------------
# 고온 저습 처리 (18가지)
# ---------------------------------------------------------
def _handle_hot_dry_case(relay_settings, status, status_str, house_id=None):
    # 공통 설정: 냉각 + 가습
    cfg.set_relay_basic_settings(relay_settings, 배수밸브=True, 수온히터=False, 분무모터=True, 내부히터=False)
    
    if status["co2"] == "정상":
        if status["외부온도"] == "높음" and status["외부습도"] == "낮음":
            # 외부도 덥고 건조하면 배출순환 (분무모터로 가습)
            apply_air_circulation_mode(relay_settings, "배출순환", status_str, "RULE_301A", house_id)
        else:
            # 외부 조건이 나으면 외부순환
            apply_air_circulation_mode(relay_settings, "외부순환", status_str, f"RULE_301B_{status['외부온도']}_{status['외부습도']}", house_id)
    
    elif status["co2"] == "높음":
        # CO2 높으면 무조건 외부순환
        apply_air_circulation_mode(relay_settings, "외부순환", status_str, f"RULE_302_{status['외부온도']}_{status['외부습도']}", house_id)

# ---------------------------------------------------------
# 적정온도 고습 처리 (18가지)
# ---------------------------------------------------------
def _handle_normal_temp_humid_case(relay_settings, status, status_str, house_id=None):
    cfg.set_relay_basic_settings(relay_settings, 분무모터=False, 수온히터=False, 배수밸브=True, 내부히터=True)     
    
    if status["co2"] == "정상":
        if status["외부습도"] == "낮음":
            # 외부가 건조하면 외부순환으로 제습
            apply_air_circulation_mode(relay_settings, "외부순환", status_str, f"RULE_401A_{status['외부온도']}", house_id)
        else:
            # 외부도 습하면 배출순환으로 습기 배출
            apply_air_circulation_mode(relay_settings, "배출순환", status_str, f"RULE_401B_{status['외부온도']}", house_id)
    
    elif status["co2"] == "높음":
        # CO2 높으면 무조건 외부순환
        apply_air_circulation_mode(relay_settings, "외부순환", status_str, f"RULE_402_{status['외부온도']}_{status['외부습도']}", house_id)

# ---------------------------------------------------------
# 적정온도 저습 처리 (18가지)
# ---------------------------------------------------------
def _handle_normal_temp_dry_case(relay_settings, status, status_str, house_id=None):
    cfg.set_relay_basic_settings(relay_settings, 분무모터=True, 배수밸브=False)   
    
    # 수온히터를 가습에 활용
    if status["외부온도"] == "높음":
        relay_settings["수온히터"] = True  
        relay_settings["내부히터"] = False
    else:
        relay_settings["수온히터"] = True
        relay_settings["내부히터"] = False 
    
    if status["co2"] == "정상":
        if status["외부습도"] == "높음":
            apply_air_circulation_mode(relay_settings, "외부순환", status_str, f"RULE_501A_{status['외부온도']}", house_id)
        else:
            apply_air_circulation_mode(relay_settings, "내부순환", status_str, f"RULE_501B_{status['외부온도']}", house_id)
    elif status["co2"] == "높음":
        apply_air_circulation_mode(relay_settings, "외부순환", status_str, f"RULE_502_{status['외부온도']}_{status['외부습도']}", house_id)

# ---------------------------------------------------------
# 저온 고습 처리 (18가지)
# ---------------------------------------------------------
def _handle_cold_humid_case(relay_settings, status, status_str, house_id=None):
    cfg.set_relay_basic_settings(relay_settings, 배수밸브=False, 분무모터=False)
    
    # 수온히터 우선 사용 (습도 제어는 배수밸브로)
    if status["외부온도"] == "높음":
        # 외부가 덥다면 수온히터로 가온
        relay_settings["수온히터"] = True
        relay_settings["내부히터"] = False
        heating_method = "수온"
    else:
        # 외부가 춥다면 수온히터 사용
        relay_settings["수온히터"] = True
        relay_settings["내부히터"] = False
        heating_method = "수온"
    
    if status["co2"] == "정상":
        if status["외부습도"] == "높음":
            apply_air_circulation_mode(relay_settings, "배출순환", status_str, f"RULE_601A_{heating_method}_{status['외부온도']}", house_id)
        else:
            apply_air_circulation_mode(relay_settings, "외부순환", status_str, f"RULE_601B_{heating_method}_{status['외부온도']}", house_id)
    elif status["co2"] == "높음":
        apply_air_circulation_mode(relay_settings, "외부순환", status_str, f"RULE_602_{heating_method}_{status['외부온도']}", house_id)

# ---------------------------------------------------------
# 저온 적정습도 처리 (18가지)
# ---------------------------------------------------------
def _handle_cold_normal_humid_case(relay_settings, status, status_str, house_id=None):
    cfg.set_relay_basic_settings(relay_settings, 배수밸브=False, 분무모터=False)
    
    # 수온히터 우선 사용
    if status["외부온도"] == "높음":
        relay_settings["수온히터"] = True
        relay_settings["내부히터"] = False
        heating_method = "수온"
    else:
        relay_settings["수온히터"] = True
        relay_settings["내부히터"] = False
        heating_method = "수온"
    
    if status["co2"] == "정상":
        if status["외부온도"] == "높음":
            apply_air_circulation_mode(relay_settings, "외부순환", status_str, f"RULE_701A_{heating_method}", house_id)
        else:
            apply_air_circulation_mode(relay_settings, "내부순환", status_str, f"RULE_701B_{heating_method}", house_id)
    elif status["co2"] == "높음":
        apply_air_circulation_mode(relay_settings, "외부순환", status_str, f"RULE_702_{heating_method}_{status['외부온도']}", house_id)

# ---------------------------------------------------------
# 저온 저습 처리 (18가지)
# ---------------------------------------------------------
def _handle_cold_dry_case(relay_settings, status, status_str, house_id=None):
    cfg.set_relay_basic_settings(relay_settings, 배수밸브=False, 분무모터=True)
    
    # 수온히터 우선 사용 (가습과 가온 동시 효과)
    if status["외부온도"] == "높음":
        relay_settings["수온히터"] = True
        relay_settings["내부히터"] = False
        heating_method = "수온"
    else:
        relay_settings["수온히터"] = True
        relay_settings["내부히터"] = False
        heating_method = "수온"
    
    if status["co2"] == "정상":
        if status["외부온도"] == "높음":
            apply_air_circulation_mode(relay_settings, "외부순환", status_str, f"RULE_801A_{heating_method}", house_id)
        else:
            if status["외부습도"] == "낮음":
                apply_air_circulation_mode(relay_settings, "내부순환", status_str, f"RULE_801B_{heating_method}", house_id)
            else:
                apply_air_circulation_mode(relay_settings, "외부순환", status_str, f"RULE_801C_{heating_method}", house_id)
    elif status["co2"] == "높음":
        apply_air_circulation_mode(relay_settings, "외부순환", status_str, f"RULE_802_{heating_method}_{status['외부온도']}", house_id)

# ---------------------------------------------------------
# 릴레이 설정 검증 및 안전 규칙 적용 함수
# LLM 생성 또는 룰 기반 생성 이후 공통으로 호출
# 검증 항목:
# 1. 공기순환 모드 설정 여부 (최소 1개 순환 장치 동작)
# 2. 내부히터와 히터밸브 동일값 여부
# 3. 내부히터와 수온히터 동시 동작 금지
# ---------------------------------------------------------
def validate_and_apply_safety_rules(relay_settings, farm_id=None, house_id=None):
    logger.info("=" * 80)
    logger.info("릴레이 설정 안전 규칙 검증 및 적용 시작")
    
    violations = []
    corrections = []
    
    # ================================================
    # 0.$$$$$$$$$$ 아래는 강제로 히터 막음.
    # ================================================
    relay_settings["수온히터"] = False
    relay_settings["내부히터"] = False
    relay_settings["히터밸브"] = False
    
    # ================================================
    # 1. 내부히터와 수온히터 동시 동작 금지 (최우선 안전 규칙)
    # ================================================
    if relay_settings.get("내부히터", False) and relay_settings.get("수온히터", False):
        violations.append("위험: 내부히터와 수온히터 동시 동작")
        relay_settings["수온히터"] = False 
        corrections.append("수정: 수온히터 비활성화 (안전 우선)")
        logger.warning("⚠️  안전규칙 위반: 내부히터와 수온히터 동시 동작 -> 수온히터 비활성화")
    
    # ================================================
    # 2. 내부히터와 히터밸브 동일값 강제 적용
    # ================================================
    heater_status = relay_settings.get("내부히터", False)
    valve_status = relay_settings.get("히터밸브", False)
    
    if heater_status != valve_status:
        violations.append(f"불일치: 내부히터({heater_status}) != 히터밸브({valve_status})")
        relay_settings["히터밸브"] = heater_status  # 내부히터 상태에 맞춤
        corrections.append(f"수정: 히터밸브를 내부히터 상태({heater_status})로 동기화")
        logger.info(f"🔧 히터 동기화: 히터밸브를 {heater_status}로 설정")
    
    # ================================================
    # 3. 공기순환 모드 검증 및 강제 적용
    # ================================================
    circulation_devices = {
        "흡입모터": relay_settings.get("흡입모터", False),
        "배출모터": relay_settings.get("배출모터", False), 
        "순환밸브": relay_settings.get("순환밸브", False),
        "흡입밸브": relay_settings.get("흡입밸브", False),
        "배출밸브": relay_settings.get("배출밸브", False)
    }
    
    active_circulation = [name for name, status in circulation_devices.items() if status]
    
    if not active_circulation:
        violations.append("위험: 공기순환 장치가 모두 비활성화됨")
        # 기본 안전 순환 모드 적용 (내부순환)
        relay_settings["흡입모터"] = True
        relay_settings["배출모터"] = True  
        relay_settings["순환밸브"] = True
        corrections.append("수정: 기본 내부순환 모드 강제 적용 (흡입모터, 배출모터, 순환밸브 활성화)")
        logger.warning("⚠️  공기순환 없음 -> 기본 내부순환 모드 강제 적용")
        active_circulation = ["흡입모터", "배출모터", "순환밸브"]
    
    # ================================================
    # 4. 순환 모드 분석 및 로깅
    # ================================================
    circulation_mode = "사용자정의"
    if circulation_devices["순환밸브"] and not circulation_devices["흡입밸브"] and not circulation_devices["배출밸브"]:
        circulation_mode = "내부순환"
    elif not circulation_devices["순환밸브"] and circulation_devices["흡입밸브"] and circulation_devices["배출밸브"]:
        circulation_mode = "외부순환"
    elif circulation_devices["순환밸브"] and circulation_devices["흡입밸브"] and circulation_devices["배출밸브"]:
        circulation_mode = "혼합순환"
    elif circulation_devices["흡입모터"] and not circulation_devices["배출모터"]:
        circulation_mode = "흡입순환"
    elif not circulation_devices["흡입모터"] and circulation_devices["배출모터"]:
        circulation_mode = "배출순환"
    
    # ================================================
    # 5. house_id별 릴레이 매핑 검증
    # ================================================
    if house_id == 2:
        relay_mapping = cfg.RELAY_FIELD_MAPPING_E
        expected_mapping = "E버전"
    else:
        relay_mapping = cfg.RELAY_FIELD_MAPPING
        expected_mapping = "표준버전"
    
    # ================================================
    # 6. 검증 결과 종합 로깅
    # ================================================
    logger.info(f"🏠 농장 매핑: {expected_mapping} (house_id: {house_id})")
    logger.info(f"🌪️  공기순환 모드: {circulation_mode}")
    logger.info(f"🔥 가열 장치: 내부히터({relay_settings.get('내부히터', False)}), 수온히터({relay_settings.get('수온히터', False)}), 히터밸브({relay_settings.get('히터밸브', False)})")
    logger.info(f"💨 활성 순환장치: {', '.join(active_circulation) if active_circulation else '없음'}")
    
    if violations:
        logger.warning(f"⚠️  안전 규칙 위반 {len(violations)}건 발견 및 수정:")
        for i, violation in enumerate(violations, 1):
            logger.warning(f"   {i}. {violation}")
        for i, correction in enumerate(corrections, 1):
            logger.info(f"   ✅ {i}. {correction}")
    else:
        logger.info("✅ 모든 안전 규칙 통과")
    
    logger.info("릴레이 설정 안전 규칙 검증 완료")
    logger.info("=" * 80)
    
    return {
        "violations_count": len(violations),
        "violations": violations,
        "corrections": corrections,
        "circulation_mode": circulation_mode,
        "active_circulation": active_circulation,
        "mapping_version": expected_mapping
    }
    
    # ---------------------------------------------------------
# 수온히터 특별 제어 로직 적용 함수
# ---------------------------------------------------------
def apply_water_heater_special_control(relay_settings, sensors, optimal_values):
    current_temp = sensors["current_temp"]
    current_water_temp = sensors["current_water_temp"]
    min_temp = optimal_values.get("적정최저온도", 15)
    
    # 수온히터 사용 결정이 이미 되어 있는 경우에만 특별 제어 적용
    if relay_settings.get("수온히터", False):
        # 내부온도가 최저온도보다 낮으면 특별 제어 적용
        if current_temp < min_temp:
            target_water_temp = current_temp + WATER_TEMP_OFFSET
            
            # 수온이 목표온도에 도달하지 않았으면 수온히터 계속 가동, 분무 중지
            if current_water_temp < target_water_temp:
                relay_settings["수온히터"] = True
                relay_settings["분무모터"] = False
                logger.info(f"수온히터 특별제어: 현재수온 {current_water_temp}℃ → 목표수온 {target_water_temp}℃")
            else:
                # 수온이 목표에 도달했으면 순환모터로 안개 유입
                relay_settings["수온히터"] = False
                relay_settings["분무모터"] = True
                logger.info(f"수온히터 특별제어: 수온 {current_water_temp}℃ 도달, 분무모터로 안개 유입")
        
        # 온도 하강 예측 제어 (최저온도 근처에서 미리 가동)
        elif current_temp <= min_temp + 2:
            relay_settings["수온히터"] = True
            relay_settings["분무모터"] = False
            logger.info(f"수온히터 예측제어: 내부온도 {current_temp}℃ 하강 예상으로 미리 가동")
