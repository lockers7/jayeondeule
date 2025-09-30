import re
import sys
sys.path.append("/workspace/llm")
import time
import json
from datetime import datetime
from typing   import Union, Dict 

import config                  as cfg
import modules.chroma_rest_api as cra

from modules.relay_status   import get_single_house_status, get_all_houses_status, change_operation_mode
from modules.data_retriever import search_weather_data
from modules.utils_text     import identify_document_specific_query

from modules.log_handler    import setup_logger
logger = setup_logger(__name__)

# -----------------------------------------------------------
# ** 프롬프트 구성 메인 함수
# -----------------------------------------------------------
def construct_prompt(query, query_type, context_data, farm_id=None, house_id=None, hour=None):
    prompt = ""
    
    farm_info = context_data.get("farm_info", {})
    if farm_info.get("farm_name"):
        farm_name = farm_info.get("farm_name")
    elif farm_id:
        farm_name = cfg.get_farm_name(farm_id, house_id)
    else:
        farm_name = "자연들에"
    farm_info_text = f"농장코드: {farm_id}, " if farm_id else ""
    time_info = f"시간대: {hour}시, " if hour is not None else f"현재 시간: {datetime.now().hour}시, "
    system_prompt = get_system_prompt(farm_name)
    
    document_query_type, relevant_doc = identify_document_specific_query(query, context_data)
        
    if document_query_type:
        if document_query_type == "crop_cultivation":
            prompt = get_crop_cultivation_prompt(farm_name, query)
            if relevant_doc:
                if "cultivation" in relevant_doc:
                    prompt += f"\n재배 방법 관련 정보:\n{relevant_doc['cultivation']}\n"
                elif "cultivation_method" in relevant_doc:
                    prompt += f"\n재배 방법 관련 정보:\n{relevant_doc['cultivation_method']}\n"
                elif "cultivation_environment" in relevant_doc:
                    prompt += f"\n재배 환경 관련 정보:\n{relevant_doc['cultivation_environment']}\n"

        elif document_query_type == "crop_disease":
            prompt = get_crop_disease_prompt(farm_name, query)
            if relevant_doc:
                if "disease_control" in relevant_doc:
                    prompt += f"\n병해충 관련 정보:\n{relevant_doc['disease_control']}\n"
                elif "disease_info" in relevant_doc:
                    prompt += f"\n병해충 관련 정보:\n{relevant_doc['disease_info']}\n"

        elif document_query_type == "crop_harvest":
            prompt = get_crop_harvest_prompt(farm_name, query)
            if relevant_doc:
                if "harvest_info" in relevant_doc:
                    prompt += f"\n수확 관련 정보:\n{relevant_doc['harvest_info']}\n"
                elif "harvest_processing" in relevant_doc:
                    prompt += f"\n수확 관련 정보:\n{relevant_doc['harvest_processing']}\n"

        elif document_query_type == "crop_benefit":
            prompt = get_crop_benefit_prompt(farm_name, query)
            if relevant_doc:
                if "benefits" in relevant_doc:
                    prompt += f"\n효능 관련 정보:\n{relevant_doc['benefits']}\n"
                elif "components_benefits" in relevant_doc:
                    prompt += f"\n성분 및 효능 관련 정보:\n{relevant_doc['components_benefits']}\n"
    
    elif query_type == "general_chat":
        prompt = get_general_chat_prompt(farm_name, query)

    elif query_type == "relay_status":
        prompt = f"{system_prompt}\n\n{farm_info_text}{time_info}릴레이 상태에 관한 질문입니다. 현재 릴레이 설정값을 상세히 조회하여 보여주세요.\n\n사용자 질문: {query}\n\n"
        if context_data["current_data"]:
            latest_data = context_data["current_data"][0]

            relay_status_text = get_relay_status_text(latest_data)
            prompt += relay_status_text
            prompt += "\n현재 환경 상태:\n"

            source_sensor_keys = [k for k in cfg.SENSOR_FIELD_MAPPING.keys() if not k.endswith('_valu')]
            stats_sensor_keys = [k for k in cfg.SENSOR_FIELD_MAPPING.keys() if k.endswith('_valu')]

            sensor_added = set()
            for key in source_sensor_keys:
                if key in latest_data and key in cfg.SENSOR_FIELD_MAPPING:
                    info = cfg.SENSOR_FIELD_MAPPING[key]
                    display_name = info[0]
                    unit = info[1]
                    if display_name not in sensor_added:
                        prompt += f"- {display_name}: {latest_data[key]}{unit}\n"
                        sensor_added.add(display_name)

            if "sensor_stats" in latest_data and not sensor_added:
                try:
                    sensor_stats = json.loads(latest_data["sensor_stats"])
                    for key in stats_sensor_keys:
                        if key in sensor_stats and key in cfg.SENSOR_FIELD_MAPPING:
                            info = cfg.SENSOR_FIELD_MAPPING[key]
                            display_name = info[0]
                            unit = info[1]
                            if display_name not in sensor_added:
                                stats = sensor_stats[key]
                                mean_value = stats.get("mean", 0) if isinstance(stats, dict) else stats
                                prompt += f"- {display_name}: {mean_value}{unit}\n"
                                sensor_added.add(display_name)
                except Exception as e:
                    prompt += f"센서 통계 데이터 파싱 오류: {str(e)}\n"

            prompt += "\n릴레이 장치 설명:\n"
            relay_keys = get_ordered_relay_keys()
            for key in relay_keys:
                if key in cfg.RELAY_FIELD_MAPPING:
                    info = cfg.RELAY_FIELD_MAPPING[key]
                    relay_name = info[0]
                    relay_function = info[2]
                    prompt += f"- {relay_name}: {relay_function}\n"
            prompt += "\n현재 환경 분석 및 제어 조합:\n"
        else:
            prompt += "현재 릴레이 상태 정보를 조회할 수 없습니다. 데이터가 없습니다.\n"
            
        prompt += "\n" + get_relay_status_prompt()

    elif query_type == "farm_status":
        prompt = get_farm_status_prompt(system_prompt, farm_info_text, time_info, query)

        if context_data["current_data"]:
            prompt += "\n현재 농장 상태 데이터:\n"
            for idx, data in enumerate(context_data["current_data"][:3]):
                prompt += f"\n--- 데이터 #{idx+1} ---\n"
                for key, value in data.items():
                    if value is not None and key not in ['id', 'document_id']:
                        prompt += f"{key}: {value}\n"
        if context_data["stats_data"]:
            prompt += "\n\n최근 통계 데이터:\n"
            for stat in context_data["stats_data"][:2]:
                if "sensor_stats" in stat:
                    try:
                        sensor_stats = json.loads(stat["sensor_stats"])
                        prompt += "\n센서 통계 데이터:\n"
                        for sensor, values in sensor_stats.items():
                            prompt += f"- {cfg.get_sensor_name(sensor)}: 평균={values.get('mean', 0)}, 최소={values.get('min', 0)}, 최대={values.get('max', 0)}\n"
                    except:
                        pass
        prompt += get_farm_status_append_prompt()
    elif query_type == "web_search":
        prompt = f"""
            당신은 자연들에 스마트팜의 AI 어시스턴트입니다.
            사용자가 웹 검색이 필요한 질문을 했습니다.
            
            사용자 질문: {query}
            
            죄송하지만 현재 실시간 웹 검색 기능을 제공하지 않습니다. 
            다음과 같은 방법을 이용해주세요:
            
            1. 날씨 정보: 기상청 홈페이지(weather.go.kr) 또는 날씨 앱 이용
            2. 실시간 정보: 포털 사이트나 관련 웹사이트 직접 확인
            3. 농장 관련 궁금한 점이 있으시면 언제든 말씀해주세요!
            
            농장 환경이나 작물 관리에 대한 질문이시라면 도움을 드릴 수 있습니다.
        """
    elif query_type == "weather_query":
        weather_result = search_weather_data(query)
        weather_context = weather_result.get("weather_context", {})
        weather_data = weather_result.get("weather_data")
        
        location = weather_context.get("location", "현재 위치")
        time_info_weather = weather_context.get("time_info", "오늘")
        weather_focus = weather_context.get("weather_focus", "일반 날씨")
        
        prompt = get_weather_query_prompt(
            query,
            location,
            time_info_weather,
            weather_focus,
            weather_data,
        )

    elif query_type == "file_analysis":
        prompt = get_file_analysis_prompt(query)

        if "file_context" in context_data:
            file_prompt = create_file_context_prompt(context_data["file_context"])
            prompt += file_prompt

    elif query_type == "environment_status":
        prompt = f"{system_prompt}\n\n{farm_info_text}{time_info}현재 환경 상태에 대한 질문입니다. 센서 데이터를 기반으로 답변하라.\n\n사용자 질문: {query}\n\n"
        if context_data["current_data"]:
            latest_data = context_data["current_data"][0]
            prompt += "현재 환경 상태:\n"

            for key, value in latest_data.items():
                if key.endswith('_value') and value is not None:
                    sensor_name = cfg.get_sensor_name(key)
                    unit = cfg.get_sensor_unit(key) if hasattr(cfg, 'get_sensor_unit') else ''
                    prompt += f"- {sensor_name}: {value}{unit}\n"

            prompt += "\n현재 릴레이 상태:\n"
            relay_keys = [k for k in latest_data.keys() if k.endswith('_flag')]
            for key in relay_keys:
                if key in latest_data:
                    relay_name = cfg.search_relay_function('rfm', 'relay_name', key, 'function_detail')
                    status = "켜짐" if latest_data[key] else "꺼짐"
                    prompt += f"- {relay_name}: {status}\n"

            prompt += "\n추가 정보:\n"
            for key in ['farm_name', 'house_name', 'growth_status', 'crop_type', 'total_yield']:
                if key in latest_data and latest_data[key]:
                    prompt += f"- {key}: {latest_data[key]}\n"
        else:
            prompt += "주의: 현재 농장 데이터를 조회할 수 없습니다. 일반적인 정보만 제공됩니다.\n"

    elif query_type == "environment_control" or query_type == "relay_control":
        prompt = f"{system_prompt}\n\n{farm_info_text}{time_info}환경 제어 요청입니다. 요청에 따라 적절한 릴레이 설정을 제안하라.\n\n사용자 요청: {query}\n\n"
        if context_data["current_data"]:
            latest_data = context_data["current_data"][0]
            prompt += "현재 환경 상태 및 릴레이 설정:\n"

            if "indoor_temperature_value" in latest_data:
                prompt += f"- 내부온도: {latest_data['indoor_temperature_value']}℃\n"
            if "indoor_humidity_value" in latest_data:
                prompt += f"- 내부습도: {latest_data['indoor_humidity_value']}%\n"
            if "co2_concentration_value" in latest_data:
                prompt += f"- co2 농도: {latest_data['co2_concentration_value']}ppm\n"

            prompt += "\n현재 릴레이 상태:\n"
            relay_keys = [
                'water_heater_flag', 'fog_occurs_flag', 'drainage_motor_flag', 'drainage_motor_2_flag',
                'intake_fan_flag', 'exhaust_fan_flag', 'lighting_flag', 'irrigation_flag',
                'indoor_heater_flag', 'air_circulation_valve_flag', 'air_intake_valve_flag', 'air_exhaust_valve_flag'
            ]
            
            for key in relay_keys:
                if key in latest_data:
                    relay_name = cfg.search_relay_function('rfm', 'relay_name', key, 'function_detail')
                    status = "켜짐" if latest_data[key] else "꺼짐"
                    prompt += f"- {relay_name}: {status}\n"

        if context_data["optimal_data"]:
            optimal = context_data["optimal_data"][0]
            prompt += "\n최적 환경 조건:\n"
            is_manual = optimal.get("is_manual", False)
            prompt += f"(설정 타입: {'수동 설정' if is_manual else '자동 학습'})\n"            
            if "sensor_means" in optimal:
                try:
                    sensor_means = json.loads(optimal["sensor_means"])
                    if "indoor_temperature_value" in sensor_means:
                        prompt += f"- 최적 내부온도: {sensor_means['indoor_temperature_value']}℃\n"
                    if "indoor_humidity_value" in sensor_means:
                        prompt += f"- 최적 내부습도: {sensor_means['indoor_humidity_value']}%\n"
                    if "co2_concentration_value" in sensor_means:
                        prompt += f"- 최적 co2 농도: {sensor_means['co2_concentration_value']}ppm\n"
                except:
                    pass

    elif query_type == "yield_information":
        prompt = f"{system_prompt}\n\n{farm_info_text}{time_info}수확량 및 판매 정보에 대한 질문입니다. 생육 데이터를 기반으로 답변하라.\n\n사용자 질문: {query}\n\n"
        if context_data["stats_data"]:
            prompt += "생육 통계 데이터:\n"
            for stat in context_data["stats_data"][:3]:
                prompt += f"- 날짜: {stat.get('date', '')}\n"
                
                if "sensor_stats" in stat:
                    try:
                        sensor_stats = json.loads(stat["sensor_stats"])
                        prompt += "  센서 평균값:\n"
                        for sensor, values in sensor_stats.items():
                            sensor_name = cfg.get_sensor_name(sensor)
                            prompt += f"  - {sensor_name}: {values.get('mean', 0)}\n"
                    except:
                        pass

        if context_data["learned_data"]:
            for data in context_data["learned_data"]:
                if "crops_data" in data:
                    try:
                        crops = data["crops_data"]
                        if isinstance(crops, str):
                            crops = json.loads(crops)
                        
                        if crops:
                            prompt += "\n생육 데이터:\n"
                            for crop in crops[:3]:
                                prompt += f"- 총 수확량: {crop.get('crop_qtty', 0)}\n"
                                prompt += f"- 등급1 수확량: {crop.get('crop_grde_qtty_1', 0)}\n"
                                prompt += f"- 등급1 비율: {crop.get('grade_1_ratio', 0) * 100}%\n"
                                prompt += f"- 총 수익: {crop.get('crop_grde_amut_1', 0) * crop.get('crop_grde_qtty_1', 0) + crop.get('crop_grde_amut_2', 0) * crop.get('crop_grde_qtty_2', 0) + crop.get('crop_grde_amut_3', 0) * crop.get('crop_grde_qtty_3', 0)}\n"
                    except:
                        pass
    
    elif query_type == "control_suggestion":
        prompt = f"{system_prompt}\n\n{farm_info_text}{time_info}환경 제어 조언 요청입니다. 최적 환경 조건과 현재 상태를 비교하여 조언하라.\n\n사용자 요청: {query}\n\n"
        if context_data["current_data"]:
            latest_data = context_data["current_data"][0]
            prompt += "현재 환경 상태:\n"
            
            if "indoor_temperature_value" in latest_data:
                prompt += f"- 내부온도: {latest_data['indoor_temperature_value']}℃\n"
            if "indoor_humidity_value" in latest_data:
                prompt += f"- 내부습도: {latest_data['indoor_humidity_value']}%\n"
            if "co2_concentration_value" in latest_data:
                prompt += f"- co2 농도: {latest_data['co2_concentration_value']}ppm\n"

        if context_data["optimal_data"]:
            optimal = context_data["optimal_data"][0]
            prompt += "\n최적 환경 조건:\n"
 
            is_manual = optimal.get("is_manual", False)
            prompt += f"(운용 모드: {'수동 설정' if is_manual else '자동 학습'})\n" 
            
            if "sensor_means" in optimal:
                try:
                    sensor_means = json.loads(optimal["sensor_means"])
                    if "indoor_temperature_value" in sensor_means:
                        prompt += f"- 최적 내부온도: {sensor_means['indoor_temperature_value']}℃\n"
                    if "indoor_humidity_value" in sensor_means:
                        prompt += f"- 최적 내부습도: {sensor_means['indoor_humidity_value']}%\n"
                    if "co2_concentration_value" in sensor_means:
                        prompt += f"- 최적 co2 농도: {sensor_means['co2_concentration_value']}ppm\n"
                except:
                    pass
            
            if "relay_means" in optimal:
                try:
                    relay_means = json.loads(optimal["relay_means"])
                    prompt += "\n최적 릴레이 설정:\n"
                    for key, value in relay_means.items():
                        relay_name = cfg.search_relay_function('rfm', 'relay_name', key, 'function_detail')
                        status = "켜짐" if value > 0.5 else "꺼짐"
                        prompt += f"- {relay_name}: {status} (가동률: {value * 100:.1f}%)\n"
                except:
                    pass

    elif query_type in ["general_chat", "farm_general"]:
        source_result   = cra.get_documents(cfg.source_collection(), where={"farm_id": str(farm_id)}, limit=50)
        learned_result  = cra.get_documents(cfg.learned_collection(), where={"farm_id": str(farm_id)}, limit=30)
        stats_result    = cra.get_documents(cfg.stats_collection(), where={"farm_id": str(farm_id)}, limit=10)
        optimal_result  = cra.get_documents(cfg.optimal_collection(), where={"farm_id": str(farm_id)}, limit=10)
        document_result = cra.get_documents(cfg.document_collection())
        prompt = get_farm_general_prompt(query, source_result.get("documents",[]), learned_result.get("documents",[]), stats_result.get("documents",[]), optimal_result.get("documents",[]), document_result.get("documents",[]))

    elif query_type == "llm_identity":
        prompt = get_llm_identity_prompt(farm_name, query)

    elif query_type == "crop_information":
        learning_date = None
        document_title = None
        if context_data["learned_data"]:
            for data in context_data["learned_data"]:
                if "learning_date" in data:
                    learning_date = data["learning_date"]
                if "document_title" in data:
                    document_title = data["document_title"]
                if learning_date and document_title:
                    break
        learning_info = ""
        if learning_date and document_title:
            learning_info = f"\n\n이 정보는 {learning_date}에 학습한 '{document_title}' 문서를 바탕으로 제공됩니다."
        elif learning_date:
            learning_info = f"\n\n이 정보는 {learning_date}에 학습한 내용을 바탕으로 제공됩니다."

        prompt = get_crop_information_prompt(learning_info)
        if context_data["current_data"]:
            prompt += "\n현재 환경 데이터:\n"
            latest_data = context_data["current_data"][0]
            
            for key in latest_data:
                if key.endswith('_value') or key.endswith('_valu'):
                    sensor_name = cfg.get_sensor_name(key)
                    unit = cfg.get_sensor_unit(key) if hasattr(cfg, 'get_sensor_unit') else ''
                    prompt += f"- {sensor_name}: {latest_data[key]}{unit}\n"    

    elif query_type == "single_house_status":
        prompt = f"{system_prompt}\n\n{farm_info_text}{time_info}특정 재배사의 현재 시스템 상태에 대한 질문입니다.\n\n사용자 질문: {query}\n\n"
        
        house_name_match = re.search(r'(제\d+|제\d+동|제\d+호|\d+동|\d+호|재배사\d+)', query)
        house_name = house_name_match.group(0) if house_name_match else None
        
        house_status = get_single_house_status(farm_id, house_id, house_name)
        house_status = {}    
        if house_status:
            prompt += get_single_house_status_prompt(house_status)
        else:
            prompt += "특정 재배사의 상태 정보를 조회할 수 없습니다. 데이터가 없습니다.\n"

    elif query_type == "all_houses_status":
        prompt = f"{system_prompt}\n\n{farm_info_text}{time_info}모든 재배사의 현재 시스템 상태에 대한 질문입니다.\n\n사용자 질문: {query}\n\n"

        all_houses_status = get_all_houses_status(farm_id)
        all_houses_status = []  # 임시
        
        if all_houses_status:
            prompt += f"농장: {all_houses_status[0]['farm_name']} 전체 재배사 상태\n\n"
            
            for house in all_houses_status:
                prompt += get_all_houses_status_prompt(house)
                relay_keys = [k for k in house.keys() if k.endswith('_flag')]
                for key in relay_keys:
                    if key in house:
                        relay_name = cfg.search_relay_function('rfm', 'relay_name', key, 'function_detail')
                        status = "켜짐" if house[key] else "꺼짐"
                        prompt += f"- {relay_name}: {status}\n"
                prompt += "\n\n" 

            prompt += f"총 {len(all_houses_status)}개 재배사 정보를 조회했습니다.\n"
        else:
            prompt += "재배사 상태 정보를 조회할 수 없습니다. 데이터가 없습니다.\n"
    
    elif query_type == "auto_mode" or query_type == "manual_mode":
        operation_mode = "자동" if query_type == "auto_mode" else "수동"
        prompt = f"{system_prompt}\n\n{farm_info_text}{time_info}농장 혹은 재배사의 작동 모드를 {operation_mode}으로 변경하는 요청입니다.\n\n사용자 요청: {query}\n\n"
        
        house_specified = False
        house_name_match = re.search(r'(제\d+|제\d+동|제\d+호|\d+동|\d+호|재배사\d+)', query)
        house_name = house_name_match.group(0) if house_name_match else None
        
        result = change_operation_mode(farm_id, house_id, "auto" if query_type == "auto_mode" else "manual")
        result = {"success": False, "message": "모드 변경 기능이 구현되지 않았습니다."}  # 임시
        
        if result["success"]:
            prompt += f"작동 모드 변경 성공: {result['message']}\n\n"
            prompt += f"변경된 작동 모드: {result.get('mode', operation_mode + '모드')}\n"
        else:
            prompt += f"작동 모드 변경 실패: {result['message']}\n"

    else:
        prompt = f"{system_prompt}\n\n{farm_info_text}{time_info}일반적인 질문입니다. 제공된 데이터를 기반으로 최대한 답변하라.\n\n사용자 질문: {query}\n\n"
        if context_data["learned_data"]:
            prompt += "관련 데이터:\n"
            for data in context_data["learned_data"]:
                for key, value in data.items():
                    if isinstance(value, dict) or isinstance(value, list):
                        continue
                    prompt += f"- {key}: {value}\n"

    if farm_name and farm_name != "스마트팜" and farm_name != "알 수 없는 농장":
        farm_specific_info = f"\n\n[{farm_name} 농장 특정 정보]\n"
        farm_specific_data = context_data.get("farm_specific_data", [])
        
        if farm_specific_data:
            latest_data = farm_specific_data[0]
            
            sensor_keys = [k for k in latest_data.keys() if k.endswith('_value') or k.endswith('_valu')]
            if sensor_keys:
                farm_specific_info += "현재 환경 상태:\n"
                for key in sensor_keys:
                    if latest_data.get(key) is not None:
                        sensor_name = cfg.get_sensor_name(key)
                        unit = cfg.get_sensor_unit(key)
                        farm_specific_info += f"- {sensor_name}: {latest_data[key]}{unit}\n"
            
            relay_keys = [k for k in latest_data.keys() if k.startswith('relay_') and k.endswith('_flag')]
            if relay_keys:
                farm_specific_info += "\n현재 장치 상태:\n"
                for key in relay_keys:
                    if key in latest_data:
                        relay_name = cfg.search_relay_function('rfm', 'relay_name', key, 'function_detail')
                        status = "켜짐" if latest_data[key] else "꺼짐"
                        farm_specific_info += f"- {relay_name}: {status}\n"
            
            prompt += farm_specific_info                    

    if "file_context" in context_data:
        prompt += "\n\n"
        prompt += create_file_context_prompt(context_data["file_context"])

    summary_parts = []
    if context_data.get("current_data"):
        summary_parts.append(f"[현재 환경 요약] {len(context_data['current_data'])}건")
    if context_data.get("optimal_data"):
        summary_parts.append(f"[추천 환경] {len(context_data['optimal_data'])}건")
    if context_data.get("stats_data"):
        summary_parts.append(f"[통계 정보] {len(context_data['stats_data'])}건")
    if context_data.get("learned_data"):
        summary_parts.append(f"[학습 정보] {len(context_data['learned_data'])}건")
    if context_data.get("document_data"):
        summary_parts.append(f"[학습 정보] {len(context_data['document_data'])}건")
    if context_data.get("file_context"):
        summary_parts.append(f"[첨부파일] 포함")

    if farm_id is not None:
        summary_parts.append(f"[농장 ID] {farm_id}")
    if hour is not None:
        summary_parts.append(f"[요청 시간대] {hour}시")

    summary_text = "\n".join(summary_parts)
    prompt += f"\n\n[요약정보]\n{summary_text}\n\n[사용자 질문]\n{query}"

    logger.info("\n"*1)
    logger.info("="*20 + " " + ">"*3 + " PROMPT GENERATION " + "<"*3 + " " + "="*20)
    logger.info(f"[1] 사용자 질문: {query}")
    logger.info(f"[2] 질의 유형: {query_type}")
    logger.info(f"[3] 프롬프트 길이: {len(prompt)}자")
    logger.info("[3-1] 컨텍스트 요약:")
    logger.info(f" - 현재 데이터 수: {len(context_data.get('current_data', []))}")
    logger.info(f" - 최적 조건 수: {len(context_data.get('optimal_data', []))}")
    logger.info(f" - 통계 데이터 수: {len(context_data.get('stats_data', []))}")
    logger.info(f" - 학습 데이터 수: {len(context_data.get('learned_data', []))}")
    if context_data.get("file_context"):
        logger.info(" - 첨부파일 포함")

    return prompt

# -----------------------------------------------------------
# ** 프롬프트 템플릿 정의
# -----------------------------------------------------------
def get_system_prompt(farm_name=None):
    return ""

    # if not farm_name:
    #     farm_name = "스마트팜"
    
    # return f"""
    #         당신은 {farm_name} 스마트팜 시스템을 관리하는 AI 어시스턴트입니다. 농장주의 질문에 답변하고 재배 환경을 최적화하는 역할을 합니다.
    #         사용자는 농장주로, 장치 데이터 및 생육 데이터에 기반한 질문을 할 것입니다.
    #         데이터는 센서 데이터(온도, 습도, co2 등), 릴레이 데이터(각종 장치 작동 상태), 생육 데이터(수확량, 등급별 판매 정보 등)를 포함합니다.

    #         답변 시 다음 사항을 준수하라:
    #         1. 질문에 직접적으로 답변하고, 질문에 관련된 데이터를 명확하게 제시하라.
    #         2. 환경 제어 관련 요청에는 릴레이 설정값을 명시적으로 제안하라.
    #         3. 최적 환경 조건과 현재 환경을 비교하여 개선점을 제안하라.
    #         4. 간결하고 명확하게 답변하며, 기술적 용어는 농장주가 이해할 수 있는 방식으로 설명하라.
    #         5. 자신감 있게 조언하되, 불확실한 부분은 솔직하게 인정하라.
    #         6. 기간별 통계 질문에는 평균값, 최대값, 최소값 등 정확한 통계 정보를 제공하라.
    #         7. 농장 정보 관련 질문에는 관련된 모든 정보를 리스트 형태로 제공하라.
    #         8. 생산량과 수익에 관한 질문에는 구체적인 수치와 비교 정보를 제공하라.
    #         """

# -----------------------------------------------------------
# ** 작물 재배 관련 프롬프트
# -----------------------------------------------------------
def get_crop_cultivation_prompt(farm_name, query):
    return f"""
            당신은 {farm_name} 스마트팜 시스템의 농업 전문가입니다. 사용자가 작물 재배 방법에 관해 질문했습니다.
            사용자 질문: {query}

            다음 정보를 기반으로 작물 재배 방법에 대해 상세히 답변해주세요:
            1. 재배 환경 조건 (온도, 습도, 토양 등)
            2. 재배 시기 및 기간
            3. 재배 방법의 단계별 설명
            4. 주의할 점 및 팁

            답변은 농업 전문가답게 정확하고 실용적이되, 일반 농장주도 이해할 수 있게 작성해주세요.
            """

# -----------------------------------------------------------
# ** 작물 병해충 관련 프롬프트
# -----------------------------------------------------------
def get_crop_disease_prompt(farm_name, query):
    return f"""
            당신은 {farm_name} 스마트팜 시스템의 농업 병해충 전문가입니다. 사용자가 작물 병해충에 관해 질문했습니다.
            사용자 질문: {query}

            다음 정보를 포함하여 작물 병해충에 대해 상세히 답변해주세요:
            1. 주요 병해충의 종류와 증상
            2. 발생 원인 및 조건
            3. 예방 및 방제 방법
            4. 친환경 방제 방법이 있다면 함께 설명

            답변은 농업 전문가답게 정확하되, 일반 농장주도 실제 적용할 수 있도록 실용적으로 작성해주세요.
            """

# -----------------------------------------------------------
# ** 작물 수확 관련 프롬프트
# -----------------------------------------------------------
def get_crop_harvest_prompt(farm_name, query):
    return f"""
            당신은 {farm_name} 스마트팜 시스템의 농작물 수확 전문가입니다. 사용자가 작물 수확에 관해 질문했습니다.
            사용자 질문: {query}

            다음 정보를 포함하여 작물 수확에 대해 상세히 답변해주세요:
            1. 적정 수확 시기 및 판단 방법
            2. 수확 방법 및 주의사항
            3. 수확 후 관리 (건조, 저장, 보관 등)
            4. 수확물의 품질 판단 기준

            답변은 농업 전문가답게 정확하되, 일반 농장주도 실제 적용할 수 있도록 실용적으로 작성해주세요.
            """

# -----------------------------------------------------------
# ** 작물 효능 관련 프롬프트
# -----------------------------------------------------------
def get_crop_benefit_prompt(farm_name, query):
    return f"""
            당신은 {farm_name} 스마트팜 시스템의 약용식물 전문가입니다. 사용자가 작물의 효능이나 성분에 관해 질문했습니다.
            사용자 질문: {query}

            다음 정보를 포함하여 작물의 효능과 성분에 대해 상세히 답변해주세요:
            1. 주요 약리 성분 및 특성
            2. 건강상 효능 및 의학적 가치
            3. 전통적 사용법 및 현대적 활용
            4. 주의사항 (있다면)

            답변은 전문가답게 정확하되, 일반인도 이해할 수 있는 수준으로 작성해주세요.
            다만, 의학적 주장은 신중하게 하고 필요시 참고용임을 명시해주세요.
            """

# -----------------------------------------------------------
# ** 일반 대화 프롬프트
# -----------------------------------------------------------
def get_general_chat_prompt(farm_name, query):
    return ""

    # return f"""
    #         당신은 {farm_name} 스마트팜의 AI 어시스턴트입니다. 농장주와 자연스럽고 친근한 대화를 나눌 수 있습니다.
    #         사용자 질문: {query}

    #         다음 사항을 준수하라:
    #         1. 농업과 스마트팜에 관련된 일반적인 질문에는 정확한 정보를 제공하라.
    #         2. 농장 운영 및 버섯 재배와 관련된 일반적인 지식을 친절하게 설명하라.
    #         3. 간단한 인사와 일상적인 질문에는 자연스럽고 친근하게 응답하라.
    #         4. 원예, 농업 기술, 스마트팜 기술에 대한 기본적인 질문에도 답변하라.
    #         5. 너무 전문적인 내용보다는 농장주가 이해하기 쉬운 용어를 사용하라.
    #         6. 농장 데이터에 관한 질문이 아닌 경우에도 친절하고 도움이 되는 대화를 유지하라.
    #         """

# -----------------------------------------------------------
# ** 릴레이 상태 프롬프트
# -----------------------------------------------------------
def get_relay_status_prompt():
    return """
            다음 사항을 포함하여 답변해주세요:
            1. 질문에서 요청한 재배사의 현재 릴레이 상태를 위에 제시된 형식대로 정확히 나열해주세요.
            2. 각 릴레이의 작동 여부를 '작동중(True)' 또는 '미작동(False)'으로 명확히 표시해주세요.
            3. 릴레이의 작동 목적과 현재 환경 조건에 따른 적절성도 간단히 언급해주세요.
            4. 현재 환경 조건에 따라 조정이 필요한 릴레이가 있다면 추천해주세요.
            """

# -----------------------------------------------------------
# ** 농장 상태 프롬프트
# -----------------------------------------------------------
def get_farm_status_prompt(system_prompt, farm_info, time_info, query):
    return f"""
            {system_prompt}

            {farm_info}{time_info}사용자가 농장의 현재 상태, 정보 또는 농장 목록에 대해 문의하셨습니다.
            질문 유형에 따라 다음과 같이 답변해주세요:

            1. 농장 수 질문: 특정 지역 또는 전체 농장 수를 정확히 알려주세요.
            2. 농장 목록 질문: 모든 농장의 이름과 위치를 목록 형태로 제공하라.
            3. 농장주 정보 질문: 농장주 이름, 연락처, 주소 등을 명확히 알려주세요.
            4. 농장별 수확량/매출 비교 질문: 농장별 성과를 비교하고 순위를 알려주세요.
            5. 기본 농장 정보 질문: 현재 농장의 기본 정보와 최신 상태를 요약해서 제공하라.

            사용자 질문: {query}
            """

# -----------------------------------------------------------
# ** 농장 상태 추가 정보 프롬프트
# -----------------------------------------------------------
def get_farm_status_append_prompt():
    return """
            주의사항:
            1. 조회된 데이터를 바탕으로 현재 농장 상태를 구체적으로 요약해 주세요.
            2. 온도, 습도, co2 등 주요 환경 수치를 정확히 언급해 주세요.
            3. 릴레이 상태(켜짐/꺼짐)도 구체적으로 설명해 주세요.
            4. 데이터가 부족하면 '데이터가 제공되지 않았습니다'라고 말하지 말고, 조회된 데이터를 바탕으로 최대한 답변해 주세요.
            5. 작물 생육 상태나 수확량 정보가 있다면 이 정보도 포함해 주세요.
            """

# -----------------------------------------------------------
# ** 날씨 질의 프롬프트
# -----------------------------------------------------------
def get_weather_query_prompt(
    query,
    location,
    time_info=None,
    weather_focus=None,
    weather_data=None,
):
    """날씨 관련 질문에 대응하는 프롬프트를 생성한다."""

    instructions = [
        "당신은 날씨 정보를 제공하는 AI 어시스턴트입니다.",
        "날씨 정보는 기상청(https://www.weather.go.kr)을 참고했다고 언급하세요.",
        "날씨 예보의 불확실성을 고려해 조언하세요.",
        "필요하면 더 정확한 정보를 위해 기상청 홈페이지 확인을 제안하세요.",
    ]

    details = [f"사용자 질문: {query}", f"지역: {location}"]
    if time_info:
        details.append(f"시간: {time_info}")
    if weather_focus:
        details.append(f"관심 날씨 요소: {weather_focus}")

    if weather_data:
        weather_lines = [
            "현재 확보된 날씨 데이터:",
            f"- 지역: {weather_data.get('city', location)}",
            f"- 현재 기온: {weather_data.get('temperature')}°C",
            f"- 체감 온도: {weather_data.get('feels_like')}°C",
            f"- 날씨 상태: {weather_data.get('description')}",
            f"- 습도: {weather_data.get('humidity')}%",
            f"- 기압: {weather_data.get('pressure')} hPa",
            f"- 풍속: {weather_data.get('wind_speed')} m/s",
            f"- 구름량: {weather_data.get('clouds')}%",
            f"- 가시거리: {weather_data.get('visibility')} km",
            f"- 일출: {weather_data.get('sunrise')}",
            f"- 일몰: {weather_data.get('sunset')}",
        ]
    else:
        weather_lines = [
            "날씨 데이터를 확보하지 못했습니다.",
            "적절한 안내와 대안을 제시하세요 (예: 기상청 홈페이지 또는 날씨 앱 이용 권장).",
        ]

    body = "\n".join(details + [""] + instructions + [""] + weather_lines)
    return f"""
            {body}
            """

# -----------------------------------------------------------
# ** 파일 분석 프롬프트
# -----------------------------------------------------------
def get_file_analysis_prompt(query):
    return f"""
            당신은 데이터 분석 전문가이자 농업 전문가입니다. 사용자가 제공한 파일 데이터를 분석하고 통찰력 있는 정보를 제공해주세요.

            사용자 질문: {query}
            """

# -----------------------------------------------------------
# ** LLM 정체성 프롬프트
# -----------------------------------------------------------
def get_llm_identity_prompt(farm_name, query):
    return f"""
            당신은 {farm_name}의 지킴이 AI 어시스턴트입니다. 자기 소개나 역할에 대한 질문에 응답합니다.
            사용자 질문: {query}

            다음 내용을 포함하여 답변하라:
            1. "{farm_name}의 지킴이"라는 정체성을 항상 언급하라.
            2. 스마트팜 데이터를 관리하고 분석하는 역할을 수행한다고 설명하라.
            3. 농장주가 농장 관리와 작물 생육에 관한 질문을 할 수 있다고 안내하라.
            4. 친절하고 도움이 되는 태도로 응답하라.
            """

# -----------------------------------------------------------
# ** 작물 정보 프롬프트
# -----------------------------------------------------------
def get_crop_information_prompt(learning_info=""):
    return f"""
            당신은 스마트팜 AI 어시스턴트로, 특히 상황버섯 재배에 전문성을 가지고 있습니다.

            다음 내용을 포함하여 답변하라:
            1. 농장에서는 상황버섯을 재배하고 있음을 언급하라.
            2. 상황버섯의 생육 조건이나 재배 방법에 관한 정보를 제공하라.
            3. 질문에 해당하는 센서 데이터나 환경 조건을 참조하여 맞춤형 정보를 제공하라.
            4. 상황버섯 재배에 도움이 될 수 있는 추가 조언을 제공하라.
            5. 답변 마지막에 다음 정보 출처를 포함하라: {learning_info}
            """

# -----------------------------------------------------------
# ** 단일 재배사 상태 프롬프트
# -----------------------------------------------------------
def get_single_house_status_prompt(house_status):
    return f"""
            재배사명: {house_status.get('house_name', '재배사명 없음')} - {house_status.get('operation_mode', '운영모드 모름')}

            현재 환경 상태:
            내부온도: {house_status.get('indoor_temperature', 'N/A')} | 
            내부습도: {house_status.get('indoor_humidity', 'N/A')} | 
            co2: {house_status.get('co2', 'N/A')} | 
            수온: {house_status.get('water_temperature', 'N/A')} | 
            광량: {house_status.get('light_level', 'N/A')} | 
            외부온도: {house_status.get('outdoor_temperature', 'N/A')} | 
            외부습도: {house_status.get('outdoor_humidity', 'N/A')}

            조회 시간: {house_status.get('record_datetime', 'N/A')}
            """

# -----------------------------------------------------------
# ** 전체 재배사 상태 프롬프트
# -----------------------------------------------------------
def get_all_houses_status_prompt(house_status):
    return f"""
            재배사명: {house_status.get('house_name', '재배사명 없음')} - {house_status.get('operation_mode', '운영모드 모름')}

            현재 환경 상태:
            내부온도: {house_status.get('indoor_temperature', 'N/A')} | 
            내부습도: {house_status.get('indoor_humidity', 'N/A')} | 
            co2: {house_status.get('co2', 'N/A')} | 
            수온: {house_status.get('water_temperature', 'N/A')} | 
            광량: {house_status.get('light_level', 'N/A')} | 
            외부온도: {house_status.get('outdoor_temperature', 'N/A')} | 
            외부습도: {house_status.get('outdoor_humidity', 'N/A')}
            조회 시간: {house_status.get('record_datetime', 'N/A')}

            릴레이 상태:
            """

# -----------------------------------------------------------
# ** 농장 일반 프롬프트
# -----------------------------------------------------------
def get_farm_general_prompt(query, source, learned, stats, optimal, document):
    return f"""
            [사용자 질의]
            {query}

            [최근 센서 데이터 50건 - source_collection]
            {source} 

            [최근 학습된 환경 데이터 30건 - learned_collection]
            {learned}

            [최근 통계 데이터 20건 - stats_collection]
            {stats}

            [최근 최적 환경 조건 20건 - optimal_collection]
            {optimal}

            [문서 학습 데이터 조건 20건 - document_collection]
            {document}

            위의 데이터를 참고하여 사용자 질의에 대해 정확하고 친절하게 답변하라.
            """

# -----------------------------------------------------------
# ** 릴레이 상태 정보를 요구사항에 맞는 텍스트로 변환
# -----------------------------------------------------------
def get_relay_status_text(latest_data, farm_name=None, house_name=None):
    if not latest_data:
        return "릴레이 상태 정보를 찾을 수 없습니다."
    
    settings_time = "알 수 없음"
    if "record_datetime" in latest_data:
        settings_time = cfg.format_datetime(latest_data["record_datetime"])
    
    farm_info = ""
    if farm_name and house_name:
        farm_info = f"{farm_name}, {house_name} "
    
    text = f"{farm_info}셋팅시간: {settings_time} 상태\n"

    source_relay_keys = [k for k in cfg.RELAY_FIELD_MAPPING.keys() if not k.startswith('relay_')]
    stats_relay_keys  = [k for k in cfg.RELAY_FIELD_MAPPING.keys() if k.startswith('relay_')]
    ordered_source_keys = sorted(source_relay_keys, 
                                 key=lambda k: int(cfg.RELAY_FIELD_MAPPING[k][0].split('(릴레이')[1].split(')')[0]))

    relay_statuses = {}
    for key in ordered_source_keys:
        if key in latest_data:
            display_name = cfg.RELAY_FIELD_MAPPING[key][0]
            status = get_relay_status_display(latest_data[key])
            relay_statuses[display_name] = status

    if not relay_statuses and "relay_stats" in latest_data:
        try:
            relay_stats = json.loads(latest_data["relay_stats"])
            ordered_stats_keys = sorted(stats_relay_keys, 
                                      key=lambda k: int(cfg.RELAY_FIELD_MAPPING[k][0].split('(릴레이')[1].split(')')[0]))
                                      
            for key in ordered_stats_keys:
                if key in relay_stats:
                    display_name = cfg.RELAY_FIELD_MAPPING[key][0]
                    relay_value = relay_stats[key]
                    status = get_relay_status_display(relay_value)
                    relay_statuses[display_name] = status
        except Exception as e:
            text += f"릴레이 통계 데이터 파싱 오류: {str(e)}\n"

    if not relay_statuses and "relay_means" in latest_data:
        try:
            relay_means = json.loads(latest_data["relay_means"])
            for stats_key, mean_value in relay_means.items():
                source_key = cfg.RELAY_FIELD_MAPPING.get(stats_key)
                if source_key and source_key in cfg.RELAY_FIELD_MAPPING:
                    display_name = cfg.RELAY_FIELD_MAPPING[source_key][0]
                    status = get_relay_status_display(mean_value)
                    relay_statuses[display_name] = status
        except Exception as e:
            text += f"최적 릴레이 데이터 파싱 오류: {str(e)}\n"

    if relay_statuses:
        for display_name in sorted(relay_statuses.keys(), 
                                  key=lambda k: int(k.split('(릴레이')[1].split(')')[0])):
            status = relay_statuses[display_name]
            text += f"{display_name}: {status}\n"
    else:
        text += "릴레이 상태 정보를 찾을 수 없습니다.\n"
    
    return text

# -----------------------------------------------------------
# ** 릴레이 상태 표시 형식 통일
# -----------------------------------------------------------
def get_relay_status_display(value):
    if value is None:
        return "미작동(False)"
    
    if isinstance(value, (int, float)):
        if value > 0.5:  
            return "작동중(True)"
        else:
            return "미작동(False)"
    
    if isinstance(value, bool) or isinstance(value, str):
        if value in (True, "True", "true", "1", 1):
            return "작동중(True)"
        else:
            return "미작동(False)"
    
    return "상태 알 수 없음"

# =============================================================================
# LLM 통제에 의한 릴레이 셋팅 프롬프트
# =============================================================================
# -----------------------------------------------------------
# 1. 모든 센서값을 추출
# -----------------------------------------------------------
def extract_all_sensor_values(sensor_datas):
    return {
        'current_temp': safe_extract_value(sensor_datas, '내부온도', '℃'),
        'outdoor_temp': safe_extract_value(sensor_datas, '외부온도', '℃'),
        'current_humidity': safe_extract_value(sensor_datas, '내부습도', '%'),
        'outdoor_humidity': safe_extract_value(sensor_datas, '외부습도', '%'),
        'current_co2': safe_extract_value(sensor_datas, 'co2 농도', 'ppm'),
        'current_water': safe_extract_value(sensor_datas, '수온', '℃')
    }

# -----------------------------------------------------------
# 2. 모든 최적 센서값을 추출
# -----------------------------------------------------------
def extract_all_optimal_values(optimal_datas):
    return {
        'temp_min': safe_extract_value(optimal_datas, '적정최저온도', ''),
        'temp_max': safe_extract_value(optimal_datas, '적정최고온도', ''),
        'humidity_min': safe_extract_value(optimal_datas, '적정최저습도', ''),
        'humidity_max': safe_extract_value(optimal_datas, '적정최고습도', ''),
        'co2_min': safe_extract_value(optimal_datas, '적정최저co2', ''),
        'co2_max': safe_extract_value(optimal_datas, '적정최고co2', ''),
        'water_min': safe_extract_value(optimal_datas, '적정최저수온', ''),
        'water_max': safe_extract_value(optimal_datas, '적정최고수온', '')
    }

# -----------------------------------------------------------
# 3. 안전하게 값을 추출
# -----------------------------------------------------------
def safe_extract_value(data, param_name, unit):
    try:
        if unit:
            pattern = f'{param_name}: '
            if pattern in data:
                return data.split(pattern)[1].split(f' {unit}')[0].strip()
        else:
            pattern = f'{param_name}: '
            if pattern in data:
                return data.split(pattern)[1].split('\n')[0].strip()
        return 'N/A'
    except (IndexError, AttributeError):
        return 'N/A'

# -----------------------------------------------------------------
# 4. LLM이 직접 판단할 수 있는 명확하지만 유연한 시스템 프롬프트를 생
#    최대 자유도 + 안전장치 프롬프트 생성
# -----------------------------------------------------------------
def relay_control_system_prompt(session_id, sensor_values, optimal_values):
    return f"""
당신은 스마트팜 환경 제어 전문가입니다. 센서 데이터와 최적 조건을 분석하여 독자적으로 최적의 릴레이 제어를 결정하는 역할을 담당합니다.

## 핵심 역할
- 현재 환경과 최적 조건 간의 차이를 분석하여 제어 목표 설정
- 농업 환경 제어의 물리적 원리에 따른 논리적 판단
- 안전하고 효율적인 릴레이 조합 결정
- 위험 상황 우선 감지 및 즉시 대응

## 기본 제어 원리
### 온도 제어
**가열 (수온히터)**:  
- 내부온도가 목표 범위 하한 이하이거나, 내부온도가 곧 낮아질 경우에만 미리 수온을 목표선까지 예열(pre-heat)할 때 사용  
- 배수밸브 작동 시 유입되는 지하수는 이미 원하는 온도이므로 수온히터 사용 금지  
**가열 (내부히터)**:  
- 외부온도가 낮거나, 내부습도가 높아 온도를 상승시켜야 할 때만 사용  
 ### 냉각: 배수밸브(제습), 외부 공기 유입, 환기
 
### 습도 제어  
- **가습**: 분무모터, 수온히터
- **제습**: 배수밸브, 내부히터, 환기

### CO2 제어
- **환기**: 외부 공기 유입으로 CO2 농도 조절

### 공기 순환
- **내부순환**: 순환밸브 + 흡입모터 + 배출모터
- **외부순환**: 흡입밸브 + 배출밸브 + 흡입모터 + 배출모터  
- **혼합순환**: 모든 순환 장치 가동
- **배출순환**: 배출밸브 + 배출모터 (고온/고습 해결)
- **흡입순환**: 흡입밸브 + 흡입모터 (co2과잉 해결)

## 안전 규칙 (필수 준수)
1. **수온히터와 내부히터 동시 작동 절대 금지**
2. **내부히터 = 히터밸브 (항상 동일값)**  
3. **최소 1개 순환 장치는 반드시 가동**

## 판단 프로세스
1. **위험 상황 우선 확인** (온도/습도 임계값 초과)
2. **주요 제어 목표 설정** (온도↑↓, 습도↑↓, CO2↓)
3. **효과적인 릴레이 조합 선택**
4. **순환 모드 결정**
5. **안전 규칙 검증**

## 응답 형식
반드시 다음 형식으로 응답하세요:

DOCUMENT:
현재 센서값: [값들 나열]
판단 결과: [주요 제어 목표와 선택한 방법]
판단 근거: [왜 이런 제어를 선택했는지 논리적 설명]

TEXT:
[DOCUMENT 내용을 자연어로 요약]

METADATA:
[아래 JSON 형식 정확히 준수]
"""

    
# -----------------------------------------------------------------
# 5. LLM이 직접 판단할 수 있는 명확하지만 유연한 사용자 프롬프트를 생
#    최대 자유도 + 안전장치 프롬프트 생성
# -----------------------------------------------------------------
def relay_control_user_prompt(session_id, sensor_values, optimal_values):
    return f"""
다음 농장 환경을 분석하여 최적의 릴레이 제어를 독자적으로 판단해주세요.

## 현재 센서 데이터
- 내부온도: {sensor_values.get('current_temp', 'N/A')}℃
- 외부온도: {sensor_values.get('outdoor_temp', 'N/A')}℃  
- 내부습도: {sensor_values.get('current_humidity', 'N/A')}%
- 외부습도: {sensor_values.get('outdoor_humidity', 'N/A')}%
- CO2농도: {sensor_values.get('current_co2', 'N/A')}ppm
- 수온: {sensor_values.get('current_water', 'N/A')}℃

## 최적 환경 조건
- 온도범위: {optimal_values.get('temp_min', 'N/A')}~{optimal_values.get('temp_max', 'N/A')}℃
- 습도범위: {optimal_values.get('humidity_min', 'N/A')}~{optimal_values.get('humidity_max', 'N/A')}%
- CO2범위: {optimal_values.get('co2_min', 'N/A')}~{optimal_values.get('co2_max', 'N/A')}ppm  
- 수온범위: {optimal_values.get('water_min', 'N/A')}~{optimal_values.get('water_max', 'N/A')}℃

## 온도 제어 기준
- **수온히터**: 내부온도가 목표 범위 하한 이하이거나 낮아질 경우에만 미리 수온을 목표선까지 예열할 때 사용 (배수밸브 작동 시 사용 금지)  
- **내부히터**: 외부온도가 낮거나 내부습도가 높아 온도를 상승시켜야 할 때만 사용  

---

**요청사항**: 
위 센서값과 최적 조건을 비교 분석하여, 물리적/논리적 원리에 따라 가장 효과적인 릴레이 제어 방안을 독자적으로 결정해주세요.

session_id: {session_id}

## 응답 JSON 형식 (METADATA 부분에 정확히 작성)
{{
  "session_id": "{session_id}",
  "센서분석": {{
    "온도상태": "높음|적정|낮음",
    "습도상태": "높음|적정|낮음", 
    "co2상태": "높음|정상",
    "수온상태": "높음|적정|낮음"
  }},
  "우선제어대상": "온도상승|온도하강|습도상승|습도하강|co2감소|수온조절|없음",
  "외부환경비교": {{
    "주요제어방법": "내부순환|외부순환|혼합순환|배출순환|흡입순환"
  }},
  "수온제어": {{
    "현재수온": 실제값,
    "목표수온": 실제값,
    "온도차이": "높음|적정|낮음",
    "예열시간분": "예상시간",
    "예열필요여부": "필요|불필요"
  }},
  "순환모드": "혼합순환|내부순환|외부순환|배출순환|흡입순환",
  "relay_settings": {{
    "수온히터": true/false,
    "분무모터": true/false,
    "배수밸브": true/false,
    "흡입모터": true/false,
    "배출모터": true/false,
    "내부히터": true/false,
    "순환밸브": true/false,
    "흡입밸브": true/false,
    "배출밸브": true/false,
    "히터밸브": true/false
  }},
  "error_prevention_verified": true/false
}}
"""

# -----------------------------------------------------------------------------
# ** 릴레이 셋팅
# 센서 데이터와 명확한 규칙을 제공하여 LLM이 직접 판단하도록 하는 프롬프트를 생성
# 추측이나 예측이 아닌 명확한 센서값 기반 판단을 유도
# LLM에게 최대 자유도를 제공하되 안전장치를 유지하는 프롬프트를 생성
# 일관성과 안정성을 보장하는 범위에서만 자유도를 허용
# -----------------------------------------------------------------------------
def relay_build_control_prompt(optimal_datas, sensor_datas):    
    # -----------------------------------------------------------
    # 1. 순수 센서값만 추출 (상태 판단은 LLM이 수행)
    # -----------------------------------------------------------
    sensor_values = extract_all_sensor_values(sensor_datas)
    optimal_values = extract_all_optimal_values(optimal_datas)
    
    # -------------------------------------------------------------
    # 2. 세션 관리 매번 새로운 세션
    # -------------------------------------------------------------
    session_id = int(time.time() * 1000) % 100000
         
    # -----------------------------------------------------------
    # 3. 일관된 JSON 응답을 위한 개선된 프롬프트 생성
    # -----------------------------------------------------------
    system_prompt = relay_control_system_prompt(
        session_id=session_id,
        sensor_values=sensor_values,
        optimal_values=optimal_values
    )

    user_prompt = relay_control_user_prompt(
        session_id=session_id,
        sensor_values=sensor_values,
        optimal_values=optimal_values
    )
    
    return system_prompt, user_prompt
            
# -----------------------------------------------------------
# ** 관리자 숫자 순서로 정렬된 릴레이 키 목록 반환
# -----------------------------------------------------------
def get_ordered_relay_keys():
    source_relay_keys = [k for k in cfg.RELAY_FIELD_MAPPING.keys() if not k.startswith('relay_')]
    return sorted(source_relay_keys, key=lambda k: int(cfg.RELAY_FIELD_MAPPING[k][0].split('(릴레이')[1].split(')')[0]))

# -----------------------------------------------------------
# ** 파일 컨텍스트 프롬프트 생성
# -----------------------------------------------------------
def create_file_context_prompt(file_context):
    if not file_context:
        return ""
    
    prompt_text = "\n[첨부 파일 정보]\n"
    if file_context["csv_data"]:
        prompt_text += "\n## CSV 파일 데이터\n"
        for csv_info in file_context["csv_data"]:
            prompt_text += f"\n### 파일명: {csv_info['filename']}\n"
            if "error" in csv_info:
                prompt_text += f"오류: {csv_info['error']}\n"
                continue
                
            prompt_text += f"- 행 수: {csv_info['rows_count']}\n"
            prompt_text += f"- 열 수: {csv_info['columns_count']}\n"
            prompt_text += f"- 컬럼: {', '.join(csv_info['columns'])}\n"

            if csv_info.get('numeric_stats'):
                prompt_text += "\n수치형 컬럼 통계:\n"
                for col, stats in csv_info['numeric_stats'].items():
                    prompt_text += f"- {col}: 평균={stats['mean']:.2f}, 최소={stats['min']:.2f}, 최대={stats['max']:.2f}\n"

            if csv_info.get('sample_data'):
                prompt_text += "\n샘플 데이터 (최대 5행):\n"
                for i, row in enumerate(csv_info['sample_data']):
                    prompt_text += f"행 {i+1}: {row}\n"

    if file_context["excel_data"]:
        prompt_text += "\n## Excel 파일 데이터\n"
        for excel_info in file_context["excel_data"]:
            prompt_text += f"\n### 파일명: {excel_info['filename']}\n"
            
            if "error" in excel_info:
                prompt_text += f"오류: {excel_info['error']}\n"
                continue
                
            prompt_text += f"- 시트 수: {excel_info['sheets_count']}\n"
            for sheet_name, sheet_info in excel_info.get('sheets', {}).items():
                prompt_text += f"\n시트: {sheet_name}\n"
                prompt_text += f"- 행 수: {sheet_info['rows_count']}\n"
                prompt_text += f"- 열 수: {sheet_info['columns_count']}\n"
                prompt_text += f"- 컬럼: {', '.join(sheet_info['columns'])}\n"
                if sheet_info.get('sample_data'):
                    prompt_text += "\n샘플 데이터 (최대 3행):\n"
                    for i, row in enumerate(sheet_info['sample_data']):
                        prompt_text += f"행 {i+1}: {row}\n"

    if file_context["text_data"]:
        prompt_text += "\n## 텍스트 파일 데이터\n"
        for text_info in file_context["text_data"]:
            prompt_text += f"\n### 파일명: {text_info['filename']}\n"
            
            if "error" in text_info:
                prompt_text += f"오류: {text_info['error']}\n"
                continue
                
            prompt_text += f"- 줄 수: {text_info['lines_count']}\n"
            prompt_text += f"- 글자 수: {text_info['chars_count']}\n"

            if text_info.get('preview'):
                prompt_text += "\n내용 미리보기:\n"
                prompt_text += f"```\n{text_info['preview']}\n```\n"

    if file_context["image_data"]:
        prompt_text += "\n## 이미지 파일\n"
        for image_info in file_context["image_data"]:
            prompt_text += f"- {image_info['filename']}: {image_info.get('note', '이미지 파일')}\n"
    
    return prompt_text
