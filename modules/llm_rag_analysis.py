import os
import re
import sys
sys.path.append("/workspace/llm")
import json
import pandas as pd
import numpy  as np

from datetime    import datetime,timedelta

import config                  as cfg
import modules.chroma_rest_api as cra

from modules.log_handler      import setup_logger
from modules.dat_json_to_vcdb import fetch_data_from_json

logger = setup_logger(__name__)

# -----------------------------------------------------------
#   상수 정의
# -----------------------------------------------------------
RANK_KEYWORDS = {
    "최상": 5, "특상": 5, "특급": 5,
    "상": 4, "1등급": 4, "A급": 4, "우수": 4,
    "중상": 3, "양호": 3, "B급": 3, "2등급": 3, 
    "중": 2, "보통": 2, "C급": 2, "3등급": 2,
    "하": 1, "미흡": 1, "D급": 1, "4등급": 1
}
POSITIVE_KEYWORDS = ["좋음", "양호", "우수", "성공", "높음", "품질", "맛", "색상", "크기"]

NEGATIVE_KEYWORDS = ["벌레", "문제", "부족", "실패", "병해", "충해", "질병", "곰팡이", "나쁨", "이상", "낮음"]


# -----------------------------------------------------------
#   생육상태 문자열에 따라 순위 점수를 반환
#   높은 등급일수록 높은 점수를 반환
# -----------------------------------------------------------
def get_growth_status_rank(status):
    logger.debug(f"생육상태 순위 분석: {status}")
    
    if not status or not isinstance(status, str):
        return 0

    for keyword, score in RANK_KEYWORDS.items():
        if keyword in status:
            logger.debug(f"생육상태 '{status}'에서 키워드 '{keyword}' 발견, 점수: {score}")
            return score
            
    return 0
    
# -----------------------------------------------------------
# ** 생육시 기타사항이 긍정적인지 판단
# -----------------------------------------------------------
def is_positive_remark(remark):
    logger.debug(f"리마크 긍정/부정 분석: {remark}")
    
    if not remark:
        return 0
    
    positive_count = sum(1 for word in POSITIVE_KEYWORDS if word in remark)
    negative_count = sum(1 for word in NEGATIVE_KEYWORDS if word in remark)
    
    logger.debug(f"긍정 키워드: {positive_count}개, 부정 키워드: {negative_count}개")
    
    if positive_count > negative_count:
        return 1
    elif negative_count > positive_count:
        return -1
    else:
        return 0
    
# -----------------------------------------------------------
# ** 농장별 최적 조건 분석
# 데이터를 분석하여 최적 환경 조건을 도출한다.
# -----------------------------------------------------------
def analyze_farm_optimal_conditions(data):
    start_time = datetime.now()
    current_hour = datetime.now().hour

    units_count = len(data.get("units_data", [])) 
    crops_count = len(data.get("crops_data", []))
    logger.debug(f" 최적 조건 분석 입력 데이터: 장치 데이터 {units_count}건, 작물 데이터 {crops_count}건")

    optimal_conditions = initialize_optimal_conditions(current_hour)

    if not data.get("units_data"):
        logger.warning(" 최적 조건 분석: units_data 없음")
        return optimal_conditions

    if not data.get("crops_data"):
        logger.warning(" 최적 조건 분석: crops_data 없음 (빈 목록 처리)")

    try:
        top_crops = select_top_crops(data.get("crops_data", []))
        if not top_crops:
            top_crops = [{"crop_strt_date": datetime.now().strftime("%Y-%m-%d"), 
                          "crop_end_date": datetime.now().strftime("%Y-%m-%d")}]
        
        optimal_data = collect_optimal_data(data["units_data"], top_crops, current_hour)
        
        optimal_conditions = analyze_optimal_conditions(optimal_data, current_hour)
        
    except Exception as e:
        logger.error(f" 최적 환경 조건 분석 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
    end_time = datetime.now()
    
    return optimal_conditions

# -----------------------------------------------------------   
# 최적 환경 조건 초기화
# -----------------------------------------------------------
def initialize_optimal_conditions(hour):
    return {
        "hour_of_day": hour,
        "is_manual": False,
        "temperature": {
            "day": {"min": 0, "max": 0, "optimal": 0},
            "night": {"min": 0, "max": 0, "optimal": 0}
        },
        "humidity": {
            "day": {"min": 0, "max": 0, "optimal": 0},
            "night": {"min": 0, "max": 0, "optimal": 0}
        },
        "co2": {"min": 0, "max": 0, "optimal": 0},
        "water_temperature": {"min": 0, "max": 0, "optimal": 0},
        "light_level": {"min": 0, "max": 0, "optimal": 0},
        "relay_settings": {}
    }

# -----------------------------------------------------------
# 최적 환경 데이터 수집
# -----------------------------------------------------------
def select_top_crops(crops_data):
    if not crops_data:
        return []
        
    grade1_ratio_crops = sorted(crops_data, key=lambda x: x.get("grade_1_ratio", 0), reverse=True)
    
    status_ranked_crops = sorted(crops_data, 
                               key=lambda x: get_growth_status_rank(x.get("code_name", "")), 
                               reverse=True)

    positive_rmks_crops = sorted(crops_data, 
                               key=lambda x: is_positive_remark(x.get("rmks", "")), 
                               reverse=True)

    best_crops = []
    for crop in crops_data:
        score = 0
        score += (grade1_ratio_crops.index(crop) if crop in grade1_ratio_crops else len(crops_data)) * 0.5
        score += (status_ranked_crops.index(crop) if crop in status_ranked_crops else len(crops_data)) * 0.3
        score += (positive_rmks_crops.index(crop) if crop in positive_rmks_crops else len(crops_data)) * 0.2
        crop["combined_score"] = score
        best_crops.append(crop)
        
    best_crops = sorted(best_crops, key=lambda x: x.get("combined_score", 999), reverse=False)
    
    if not best_crops:
        return []

    return best_crops[:min(3, len(best_crops))]

# -----------------------------------------------------------   
# 최적 환경 데이터 수집
# -----------------------------------------------------------
def collect_optimal_data(units_data, top_crops, current_hour):
    optimal_sensor_data = []
    optimal_relay_data = []
    
    for crop in top_crops:
        crop_start = crop.get("crop_strt_date")
        crop_end = crop.get("crop_end_date")
        
        if not crop_start:
            continue

        try:
            if isinstance(crop_start, str):
                crop_start = datetime.strptime(crop_start, "%Y-%m-%d")
            if isinstance(crop_end, str) and crop_end:
                crop_end = datetime.strptime(crop_end, "%Y-%m-%d")
            else:
                crop_end = datetime.now()
        except Exception as e:
            logger.info(f" 날짜 변환 오류: {e}")
            continue

        for unit in units_data:
            unit_datetime = unit.get("record_datetime")
            if not unit_datetime:
                continue

            try:
                if isinstance(unit_datetime, str):
                    unit_datetime = datetime.strptime(unit_datetime, "%Y-%m-%d %H:%M:%S")
            except Exception:
                try:
                    unit_datetime = datetime.strptime(unit_datetime, "%Y-%m-%d %H:%M:%S")
                except Exception as e2:
                    logger.info(f" 장치 데이터 날짜 변환 오류: {e2}")
                    continue

            unit_hour = unit_datetime.hour
            if unit_hour != current_hour:
                continue

            if crop_start <= unit_datetime <= crop_end:
                is_daytime = 6 <= unit_datetime.hour < 18
                sensor_entry = {
                    "datetime": unit_datetime,
                    "is_daytime": is_daytime,
                    "values": unit.get("sensor_value", {})
                }

                optimal_sensor_data.append(sensor_entry)
                relay_entry = {
                    "datetime": unit_datetime,
                    "is_daytime": is_daytime,
                    "settings": unit.get("relay_status", {})
                }
                optimal_relay_data.append(relay_entry)
    
    return {
        "sensor_data": optimal_sensor_data,
        "relay_data": optimal_relay_data
    }

# -----------------------------------------------------------
# 수집된 데이터를 분석하여 최적 조건 도출
# -----------------------------------------------------------
def analyze_optimal_conditions(optimal_data, current_hour):
    optimal_conditions = initialize_optimal_conditions(current_hour)
    
    sensor_data = optimal_data.get("sensor_data", [])
    
    if not sensor_data:
        return optimal_conditions
        
    # 온도 분석
    analyze_temperature_conditions(sensor_data, optimal_conditions)
    
    # 습도 분석
    analyze_humidity_conditions(sensor_data, optimal_conditions)
    
    # co2 분석
    analyze_co2_conditions(sensor_data, optimal_conditions)
    
    # 수온 분석
    analyze_water_temperature_conditions(sensor_data, optimal_conditions)
    
    # 광량 분석
    analyze_light_level_conditions(sensor_data, optimal_conditions)
    
    # 릴레이 설정 분석 (추가 구현 필요)
    # TODO: analyze_relay_settings(optimal_data.get("relay_data", []), optimal_conditions)
    
    return optimal_conditions

# -----------------------------------------------------------
# 온도 분석
# -----------------------------------------------------------
def analyze_temperature_conditions(sensor_data, optimal_conditions):
    day_temps = []
    night_temps = []
    
    for entry in sensor_data:
        temp_value = None
        if "values" in entry and "indoor_temperature_value" in entry["values"]:
            temp_value = cfg.clean_sensor_value(entry["values"]["indoor_temperature_value"])
        elif "indoor_temperature_value" in entry:
            temp_value = cfg.clean_sensor_value(entry["indoor_temperature_value"])
        
        if temp_value is not None and temp_value != 0:
            if entry["is_daytime"]:
                day_temps.append(temp_value)
            else:
                night_temps.append(temp_value)
    
    if day_temps:
        optimal_conditions["temperature"]["day"]["min"] = round(np.percentile(day_temps, 25), 1)
        optimal_conditions["temperature"]["day"]["max"] = round(np.percentile(day_temps, 75), 1)
        optimal_conditions["temperature"]["day"]["optimal"] = round(np.mean(day_temps), 1)

    if night_temps:
        optimal_conditions["temperature"]["night"]["min"] = round(np.percentile(night_temps, 25), 1)
        optimal_conditions["temperature"]["night"]["max"] = round(np.percentile(night_temps, 75), 1)
        optimal_conditions["temperature"]["night"]["optimal"] = round(np.mean(night_temps), 1)

# -----------------------------------------------------------
# 습도 분석
# -----------------------------------------------------------
def analyze_humidity_conditions(sensor_data, optimal_conditions):
    day_humidity = [entry["values"].get("indoor_humidity_value", 0) 
                   for entry in sensor_data if entry["is_daytime"] 
                   and entry["values"].get("indoor_humidity_value")]
    night_humidity = [entry["values"].get("indoor_humidity_value", 0) 
                     for entry in sensor_data if not entry["is_daytime"] 
                     and entry["values"].get("indoor_humidity_value")]
    
    if day_humidity:
        optimal_conditions["humidity"]["day"]["min"] = round(np.percentile(day_humidity, 25), 1)
        optimal_conditions["humidity"]["day"]["max"] = round(np.percentile(day_humidity, 75), 1)
        optimal_conditions["humidity"]["day"]["optimal"] = round(np.mean(day_humidity), 1)

    if night_humidity:
        optimal_conditions["humidity"]["night"]["min"] = round(np.percentile(night_humidity, 25), 1)
        optimal_conditions["humidity"]["night"]["max"] = round(np.percentile(night_humidity, 75), 1)
        optimal_conditions["humidity"]["night"]["optimal"] = round(np.mean(night_humidity), 1)

# -----------------------------------------------------------
# co2 분석
# -----------------------------------------------------------
def analyze_co2_conditions(sensor_data, optimal_conditions):
    co2_concentration_values = [entry["values"].get("co2_concentration_value", 0) 
                 for entry in sensor_data 
                 if entry["values"].get("co2_concentration_value")]
    if co2_concentration_values:
        optimal_conditions["co2"]["min"] = round(np.percentile(co2_concentration_values, 25), 1)
        optimal_conditions["co2"]["max"] = round(np.percentile(co2_concentration_values, 75), 1)
        optimal_conditions["co2"]["optimal"] = round(np.mean(co2_concentration_values), 1)

# -----------------------------------------------------------
# 수온 분석
# -----------------------------------------------------------
def analyze_water_temperature_conditions(sensor_data, optimal_conditions):
    water_temps = [entry["values"].get("water_temperature_value", 0) 
                  for entry in sensor_data 
                  if entry["values"].get("water_temperature_value")]
    if water_temps:
        optimal_conditions["water_temperature"]["min"] = round(np.percentile(water_temps, 25), 1)
        optimal_conditions["water_temperature"]["max"] = round(np.percentile(water_temps, 75), 1)
        optimal_conditions["water_temperature"]["optimal"] = round(np.mean(water_temps), 1)

# -----------------------------------------------------------
# 광량 분석
# -----------------------------------------------------------
def analyze_light_level_conditions(sensor_data, optimal_conditions):
    light_levels = [entry["values"].get("light_level_value", 0) 
                   for entry in sensor_data 
                   if entry["values"].get("light_level_value")]
    if light_levels:
        optimal_conditions["light_level"]["min"] = round(np.percentile(light_levels, 25), 1)
        optimal_conditions["light_level"]["max"] = round(np.percentile(light_levels, 75), 1)
        optimal_conditions["light_level"]["optimal"] = round(np.mean(light_levels), 1)
        
# -----------------------------------------------------------
# ** 농장별 시간 패턴 분석
# -----------------------------------------------------------
def analyze_farm_time_patterns(data, hour):
    logger.debug("농장 시간 패턴 분석 시작")
    start_time = datetime.now()

    time_patterns = initialize_time_patterns(hour)

    units_data = data.get("units_data")
    if not units_data:
        logger.warning("시간 패턴 분석: units_data 없음")
        return time_patterns

    try:
        hour_units = [unit for unit in units_data if unit.get("hour_of_day") == hour]
        if not hour_units:
            logger.info(f"시간대 {hour}시 데이터가 없습니다. (조건 미일치)")
            return time_patterns

        sensor_data = collect_sensor_data(hour_units)

        update_time_patterns_with_sensor_data(time_patterns, sensor_data, hour)

        analyze_relay_data_for_time_patterns(time_patterns, hour_units, hour)
    except Exception as e:
        logger.error(f"시간 패턴 분석 중 오류 발생: {e}")

    return time_patterns

# -----------------------------------------------------------
# ** 릴레이-센서 상관관계 분석
# -----------------------------------------------------------
def analyze_relay_sensor_correlation(relay_key, units_data):
    """Removed unused function."""
    pass

# ----------------------------------------------------------------------------------------------------
# ** 통계 및 최적 환경 데이터 처리
#   stats_collections:  10분단위 집계 저장(집계단위: 00:00:00, 00:10:00, 00:20:00 ... 00:50:00 ...)
#   optimal_collection: 10분단위 집계 저장(집계단위: 00:00:00, 00:10:00, 00:20:00 ... 00:50:00 ...)
# ----------------------------------------------------------------------------------------------------
def process_stats_and_optimal_data():
    try:    
        logger.info("-"*100)
        logger.info(" 통계 및 최적 환경 데이터 처리 시작")
        start_time = datetime.now()

        now = datetime.now()
        interval_min = cfg.STATS_INTERVAL_MINUTES or 10  # 기본값 보장
        if interval_min == 0:
            logger.warning("STATS_INTERVAL_MINUTES가 0입니다. 10으로 보정합니다.")
            interval_min = 10

        now = datetime.now()
        current_minute = (now.minute // interval_min) * interval_min
        stats_timestamp = now.replace(minute=current_minute, second=0, microsecond=0)
        stats_time_str = stats_timestamp.strftime("%Y-%m-%d %H:%M:00")
        logger.debug(f" {interval_min}분 단위 집계 시간: {stats_time_str}")
        
        units_df_path = cfg.units_json_data()
        crops_df_path = cfg.crops_json_data()

        if os.path.exists(units_df_path):
            units_size = os.path.getsize(units_df_path) / 1024
            logger.debug(f" 임시 장치 데이터 파일 확인: {units_df_path} (크기: {units_size:.2f} KB)")

        if os.path.exists(crops_df_path):
            crops_size = os.path.getsize(crops_df_path) / 1024
            logger.debug(f" 임시 생육 데이터 파일 확인: {crops_df_path} (크기: {crops_size:.2f} KB)")

        source_data = cra.get_documents(collection_name=cfg.source_collection())
        if source_data and "metadatas" in source_data:
            data_kinds = {}
            data_kind_details = {}
            
            for item in source_data["metadatas"]:
                kind = str(item.get("data_kind", "unknown")).lower()
                data_kinds[kind] = data_kinds.get(kind, 0) + 1
                
                if kind not in data_kind_details:
                    data_kind_details[kind] = list(item.keys())
                
        if not os.path.exists(units_df_path):
            units_data = [
                item for item in source_data["metadatas"] 
                if item.get("data_kind", "").lower() == "units"
            ]
            
            os.makedirs(os.path.dirname(units_df_path), exist_ok=True)
                        
            with open(units_df_path, 'w', encoding='utf-8') as f:
                json.dump(units_data, f, ensure_ascii=False, indent=2)
            logger.info(f"units_data.json 파일 생성: {len(units_data)}건")
            
        if not os.path.exists(crops_df_path):
            crops_data = [
                item for item in source_data["metadatas"] 
                if "crops" in str(item.get("data_kind", "")).lower()
            ]
            
            logger.info(f"crops 데이터 추출 결과: {len(crops_data)}건")
            
            if crops_data:
                os.makedirs(os.path.dirname(crops_df_path), exist_ok=True)
                with open(crops_df_path, 'w', encoding='utf-8') as f:
                    json.dump(crops_data, f, ensure_ascii=False, indent=2)
                logger.info(f"crops_data.json 파일 생성: {len(crops_data)}건")
            
        logger.debug(f"전체 메타데이터의 data_kind: {[item.get('data_kind') for item in source_data['metadatas'][:10]]}")        
        
        crops_df_exists = os.path.exists(crops_df_path) and os.path.getsize(crops_df_path) > 10
        if not crops_df_exists:
            logger.warning("crops 데이터 파일이 없거나 비어 있어 추가 검색 시도")
            
            keywords = ["crops", "crop", "생육", "cultivation", "harvest", "수확"]
            crops_data = []
            
            for keyword in keywords:
                found_items = [
                    item for item in source_data["metadatas"] 
                    if keyword in str(item).lower()
                ]
                if found_items:
                    logger.info(f"키워드 '{keyword}'로 {len(found_items)}건의 데이터 발견")
                    crops_data.extend(found_items)
                    break

            if not crops_data:
                logger.warning(f" ##### 작물 데이터를 찾을 수 없어 기본 작물 데이터 생성:{keywords}")
                current_datetime = datetime.now()
                current_date = current_datetime.strftime("%Y-%m-%d")
                last_month = (current_datetime - timedelta(days=30)).strftime("%Y-%m-%d")
                
                default_crop_data = {
                    "farm_id": 1,
                    "house_id": 1,
                    "record_datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "data_kind": "CROPS",
                    "crop_strt_date": last_month,
                    "crop_end_date": current_date,
                    "crop_qtty": 100,
                    "crop_grde_qtty_1": 80,
                    "grade_1_ratio": 0.8,
                    "rmks": "기본 생성 데이터",
                    "record_datetime": current_datetime.strftime("%Y-%m-%d %H:%M:%S"),
                    "hour_of_day": current_datetime.hour
                }
                
                crops_data = [default_crop_data]
                logger.info("기본 작물 데이터 생성 완료")
            
            if crops_data:
                os.makedirs(os.path.dirname(crops_df_path), exist_ok=True)
                with open(crops_df_path, 'w', encoding='utf-8') as f:
                    json.dump(crops_data, f, ensure_ascii=False, indent=2)
                logger.info(f"crops_data.json 파일 재생성: {len(crops_data)}건")        
        
        if not os.path.exists(units_df_path) and not os.path.exists(crops_df_path):
            logger.info(f" 임시 데이터 파일이 없습니다. units: [{units_df_path}]-[{os.path.exists(units_df_path)}] \n crops: [{crops_df_path}]-[{os.path.exists(crops_df_path)}]")
            return False
    except Exception as e:
        logger.error(f"데이터 처리 중 심각한 오류 발생: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False    
        
    try:
        units_df = load_data_file(units_df_path, "units")
        units_df = ensure_required_columns(units_df, "units")
        if units_df.empty:
            logger.warning(f" ##### ===>>> 정제된 장치 데이터프레임이 비어 있음 - 기본 stats 데이터 저장")
            empty_meta = {
                "record_datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "data_type": "stats_data_empty",
                "is_learned_flag": True,
                "reason": "units_df_empty"
            }
            empty_doc = json.dumps({"message": "no valid units data"}, ensure_ascii=False)
            empty_id = cra._doc_id_generator("stats", "0", "0", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            cra.upsert_collection_data("analyze_ten_minutes_stats", cfg.stats_collection(), empty_id, empty_doc, empty_meta)

        crops_df = load_data_file(crops_df_path, "crops")
        crops_df = ensure_required_columns(crops_df, "crops")
        if crops_df.empty:
            logger.warning(f" ##### ===>>> 정제된 작물 데이터프레임이 비어 있음 - 기본 optimal 데이터 저장")
            empty_meta = {
                "record_datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "data_type": "optimal_data_empty",
                "is_learned_flag": True,
                "reason": "crops_df_empty"
            }
            empty_doc = json.dumps({"message": "no valid crops data"}, ensure_ascii=False)
            empty_id = cra._doc_id_generator("optimal", "0", "0", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            cra.upsert_collection_data("process_stats_and_optimal_data", cfg.optimal_collection(), empty_id, empty_doc, empty_meta)

        if units_df is not None and 'house_id' in units_df.columns:
            units_df.rename(columns={'house_id': 'house_id'}, inplace=True)
            
            if 'record_datetime' in units_df.columns:
                units_df = ensure_record_datetime_exists(units_df, label="units_df")
                units_df['hour_of_day'] = units_df['record_datetime'].dt.hour
                units_df['ten_minute_interval'] = (units_df['record_datetime'].dt.minute // 10)
                units_df['time_interval_id'] = units_df['hour_of_day'].astype(str) + '_' + units_df['ten_minute_interval'].astype(str)
            else:
                logger.warning(f"'record_datetime' 컬럼이 없습니다. 실제 키: {units_df.columns}")
        else:
            units_df = pd.DataFrame()
            logger.warning("units_df 파일이 존재하지 않습니다.")
            return False            
            
        try:
            stats_result = cra.get_documents(collection_name=cfg.stats_collection())
            if "error" in stats_result:
                logger.info(f" stats_collection 접근 실패: {stats_result['error']}")
                return False
        except Exception as e:
            logger.info(f" stats_collection 접근 실패: {e}")
            return False
            
        try:
            optimal_result = cra.get_documents(collection_name=cfg.optimal_collection())
            if "error" in optimal_result:
                logger.info(f" optimal_collection 접근 실패: {optimal_result['error']}")
                return False
        except Exception as e:
            logger.info(f" optimal_collection 접근 실패: {e}")
            return False

        try:
            last_run_id = "last_learned_datetime"
            current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            result = cra.upsert_collection_data("process_stats_and_optimal_data", cfg.job_status_collection(), last_run_id, f"마지막실행일시: {current_datetime}", {"last_run": current_datetime})
            logger.info(f" 마지막 실행 시간 기록 {result}: {current_datetime}")
        except Exception as e:
            logger.error(f" 마지막 실행 시간 기록 중 오류: {e}")

        if not units_df.empty:
            if 'farm_id' in units_df.columns:
                if pd.api.types.is_numeric_dtype(units_df['farm_id']):
                    units_df['farm_id'] = units_df['farm_id'].astype(str)
                
            if 'house_id' in units_df.columns:
                if pd.api.types.is_numeric_dtype(units_df['house_id']):
                    units_df['house_id'] = units_df['house_id'].astype(str)

            grouped = units_df.groupby(['farm_id', 'house_id']) 
            for (farm_id, house_id), group_df in grouped:
                analyze_ten_minutes_stats(farm_id, house_id, group_df)       

            if not crops_df.empty:
                crops_df = ensure_record_datetime_exists(crops_df, label="crops_df")
                
                for (farm_id, house_id), group_df in grouped:
                    if group_df.empty:
                        continue

                    start_time = group_df['record_datetime'].min().replace(second=0, microsecond=0)
                    end_time = group_df['record_datetime'].max().replace(second=0, microsecond=0)
                    total_minutes = int((end_time - start_time).total_seconds() // 60)

                    for i in range(0, total_minutes + 1, interval_min):
                        t_start = start_time + timedelta(minutes=i)
                        t_end = t_start + timedelta(minutes=interval_min)

                        units_slice = group_df[
                            (group_df['record_datetime'] >= t_start) & (group_df['record_datetime'] < t_end)
                        ]

                        if "farm_id" not in crops_df.columns:
                            crops_df["farm_id"] = "0"
                        if "house_id" not in crops_df.columns:
                            crops_df["house_id"] = "0"

                        crops_slice = crops_df[
                            (crops_df['farm_id'].astype(str) == str(farm_id)) &
                            (crops_df['house_id'].astype(str) == str(house_id)) &
                            (crops_df['record_datetime'] >= t_start) &
                            (crops_df['record_datetime'] < t_end)
                        ]

                        if units_slice.empty and crops_slice.empty:
                            continue

                        sensor_stats, relay_stats = {}, {}
                        sensor_keys = cfg.get_sensor_keys() 
                        for key in sensor_keys:
                            if key in units_slice.columns:
                                values = clean_numeric_column(units_slice[key]).dropna()
                                if not values.empty:
                                    sensor_stats[key] = {
                                        "mean": float(values.mean()),
                                        "min": float(values.min()),
                                        "max": float(values.max()),
                                        "std": float(values.std()) if len(values) > 1 else 0
                                    }

                        for key in cfg.RELAY_KEYS:
                            if key in units_slice.columns:
                                values = units_slice[key].dropna()
                                if not values.empty:
                                    on_ratio = float(values.mean())
                                    relay_stats[key] = {
                                        "on_ratio": on_ratio,
                                        "on_minutes": on_ratio * interval_min
                                    }

                        sensor_means = {k: v["mean"] for k, v in sensor_stats.items()}
                        relay_means = {k: v["on_ratio"] for k, v in relay_stats.items()}

                        analyze_ten_minutes_optimal(
                            farm_id=farm_id,
                            house_id=house_id,
                            farm_name=cfg.get_farm_name(farm_id, house_id)[0],
                            house_name=cfg.get_farm_name(farm_id, house_id)[1],
                            agg_time=t_end,
                            sensor_means=sensor_means,
                            relay_means=relay_means,
                            crops_df=crops_df
                        )

                    stats_data = fetch_data_from_json(limit=100000)
                    if not stats_data:
                        logger.info(" 분석할 데이터가 없습니다.")
                        return

                    try:
                        all_units = []
                        all_crops = []

                        for item in stats_data:
                            all_units.extend(item.get("units", []))
                            all_crops.extend(item.get("crops", []))

                        units_df = pd.DataFrame(all_units)
                        crops_df = pd.DataFrame(all_crops)

                        if units_df.empty and crops_df.empty:
                            logger.warning("장치 및 생육 데이터프레임이 모두 비어 있음")
                            return

                        units_df = ensure_record_datetime_exists(units_df, label="units_df")
                        crops_df = ensure_record_datetime_exists(crops_df, label="crops_df")

                        if "farm_id" not in crops_df.columns:
                            crops_df["farm_id"] = "0"
                        if "house_id" not in crops_df.columns:
                            crops_df["house_id"] = "0"
                        if "농장코드" not in crops_df.columns:
                            crops_df["농장코드"] = crops_df["farm_id"]
                        if "농장코드" not in units_df.columns:
                            units_df["농장코드"] = units_df["farm_id"] if "farm_id" in units_df.columns else "0"

                        units_df = units_df.dropna(subset=["record_datetime"])
                        crops_df = crops_df.dropna(subset=["record_datetime"])

                        units_df["집계시간"] = units_df["record_datetime"].dt.floor(f"{cfg.STATS_INTERVAL_MINUTES}min")
                        crops_df["집계시간"] = crops_df["record_datetime"].dt.floor(f"{cfg.STATS_INTERVAL_MINUTES}min")

                        grouped = pd.concat([units_df, crops_df], axis=0).dropna(subset=["집계시간"])
                        hour_groups = grouped.groupby("집계시간")

                        saved_count = 0
                        for hour_time, group in hour_groups:
                            units_slice = units_df[units_df["집계시간"] == hour_time]
                            crops_slice = crops_df[crops_df["집계시간"] == hour_time]

                            if crops_slice.empty:
                                crops_slice = pd.DataFrame([{
                                    "farm_id": "0",
                                    "house_id": "0",
                                    "record_datetime": hour_time,
                                    "농장코드": "0",
                                    "기록일시": hour_time.strftime("%Y-%m-%d %H:%M:%S"),
                                    "crop_qtty": 0,
                                    "grade_1_ratio": 0.0
                                }])

                            if units_slice.empty and crops_slice.empty:
                                continue

                            farm_id = units_slice["농장코드"].iloc[0] if not units_slice.empty else crops_slice["농장코드"].iloc[0]
                            doc_id = cra._doc_id_generator("stats", farm_id, 0, str(hour_time))

                            stats_meta_data = {
                                "farm_id": str(farm_id),
                                "record_datetime": str(hour_time),
                                "data_type": "stats_data",
                                "interval": f"{cfg.STATS_INTERVAL_MINUTES}min"
                            }

                            stats_text_data = f"통계데이터 - 농장 {farm_id}, 시간 {hour_time}"

                            result = cra.upsert_collection_data(
                                calledby="process_stats_and_optimal_data",
                                collection=cfg.stats_collection(),
                                doc_id=doc_id,
                                document=stats_text_data,
                                metadata=stats_meta_data
                            )

                            if result in ["added", "updated"]:
                                saved_count += 1

                        logger.info(f" stats_collection 저장 완료 건수: {saved_count}건")

                    except Exception as e:
                        logger.error(f" process_stats_and_optimal_data 전체 오류: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
        try:
            stats_items = cra.get_documents(collection_name=cfg.stats_collection(), limit=50000)
            stats_count = len(stats_items.get("ids", [])) if "error" not in stats_items else 0
            logger.info(f" 장치 통계 데이터 항목 수: {stats_count} 건")

            optimal_items = cra.get_documents(collection_name=cfg.optimal_collection())
            optimal_count = len(optimal_items.get("ids", [])) if "error" not in optimal_items else 0
            logger.info(f" 생육 최적 데이터 항목 수: {optimal_count} 건")

            source_items = cra.get_documents(collection_name=cfg.source_collection())
            source_count = len(source_items.get("ids", [])) if "error" not in source_items else 0
            logger.info(f" 농장 원본 데이터 항목 수: {source_count} 건")
            
            if os.path.exists(units_df_path):
                units_size = os.path.getsize(units_df_path) / 1024
                logger.debug(f" 임시 장치 데이터 파일 크기: {units_size:.2f} KB")
            
            if os.path.exists(crops_df_path):
                crops_size = os.path.getsize(crops_df_path) / 1024
                logger.debug(f" 임시 생육 데이터 파일 크기: {crops_size:.2f} KB")
        except Exception as e:
            logger.error(f" 컬렉션 항목 조회 실패: {e}")
        
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        
        # 처리 건수 계산
        units_count = len(units_df) if 'units_df' in locals() and units_df is not None and not units_df.empty else 0
        crops_count = len(crops_df) if 'crops_df' in locals() and crops_df is not None and not crops_df.empty else 0
        
        logger.debug(f" 통계 및 최적 환경 데이터 처리 완료: 장치 데이터 {units_count}건, 생육 데이터 {crops_count}건 처리 (처리시간: {processing_time:.3f}초)")
        logger.debug("-"*100)
        return True
        
    except Exception as e:
        logger.error(f" process_stats_and_optimal_data 2 통계 및 최적 환경 데이터 처리 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        logger.info(f" 통계 및 최적 환경 데이터 처리 실패 (처리시간: {processing_time:.3f}초)")
        logger.info("="*100)
        return False

# ------------------------------------------------------------------------------------------------------
# ** 기록 일시 정형화
# 데이터프레임에 'record_datetime' 컬럼이 없고, '기록일시'가 존재하면 이를 datetime으로 변환하여 생성한다.
# 없을 경우 로그를 출력하고 NaT로 채운다.
# ------------------------------------------------------------------------------------------------------
def ensure_record_datetime_exists(df, label="df"):
    if df.empty:
        df["record_datetime"] = pd.NaT
        return df
    
    if "record_datetime" not in df.columns:
        if "기록일시" in df.columns:
            df["record_datetime"] = pd.to_datetime(df["기록일시"], errors="coerce")
        else:
            logger.warning(f"[{label}]에 '기록일시' 없음 → record_datetime 생성 불가")
            logger.warning(f"[{label}] 컬럼 목록: {list(df.columns)}")
            logger.warning(f"[{label}] 행 수: {len(df)}")

            preview = df.head(5).to_dict(orient="records")
            logger.warning(f"[{label}] 샘플 데이터 (상위 5행): {json.dumps(preview, ensure_ascii=False)}")
            df["record_datetime"] = pd.NaT

    return df
        
# -----------------------------------------------------------
# ** 시간대별 통계 분석
#    시간대별 센서 및 릴레이 통계 분석
# -----------------------------------------------------------
def analyze_ten_minutes_stats(farm_id, house_id, df):
    try:
        if 'record_datetime' not in df.columns:
            logger.warning("record_datetime 컬럼이 없습니다.")
            return

        farm_name, house_name = cfg.get_farm_name(farm_id=farm_id, house_id=house_id)
        if not pd.api.types.is_datetime64_any_dtype(df['record_datetime']):
            df['record_datetime'] = pd.to_datetime(df['record_datetime'], errors='coerce')

        df = df.dropna(subset=['record_datetime'])
        if df.empty:
            logger.warning("유효한 record_datetime이 없습니다.")
            return

        df = df.sort_values(by='record_datetime')
        start_time = df['record_datetime'].min().replace(second=0, microsecond=0)
        end_time = df['record_datetime'].max().replace(second=0, microsecond=0)

        interval_minutes = cfg.STATS_INTERVAL_MINUTES or 10
        total_minutes = int((end_time - start_time).total_seconds() // 60)
        total_minutes = max(interval_minutes, total_minutes)

        for i in range(0, total_minutes + 1, interval_minutes):
            t_start = start_time + timedelta(minutes=i)
            t_end = t_start + timedelta(minutes=interval_minutes)
            slice_df = df[(df['record_datetime'] >= t_start) & (df['record_datetime'] < t_end)]

            if slice_df.empty:
                continue

            agg_time = t_end
            sensor_stats = {}
            sensor_keys = cfg.get_sensor_keys() 
            for key in sensor_keys:
                if key in slice_df.columns:
                    values = clean_numeric_column(slice_df[key]).dropna()
                    if not values.empty:
                        sensor_stats[key] = {
                            "mean": float(values.mean()),
                            "min": float(values.min()),
                            "max": float(values.max()),
                            "std": float(values.std()) if len(values) > 1 else 0
                        }

            relay_stats = {}
            for key in cfg.RELAY_KEYS:
                if key in slice_df.columns:
                    values = slice_df[key].dropna()
                    if not values.empty:
                        on_ratio = float(values.mean())
                        relay_stats[key] = {
                            "on_ratio": on_ratio,
                            "on_minutes": on_ratio * interval_minutes
                        }

            recommended_relays = {}

            stats_meta = {
                "farm_id": farm_id,
                "farm_name": farm_name,
                "house_id": house_id,
                "house_name": house_name,
                "date": agg_time.date().strftime('%Y-%m-%d'),
                "hour_of_day": agg_time.hour,
                "minute_interval": interval_minutes,
                "data_type": "hourly_stats",
                "sensor_stats": json.dumps(sensor_stats, ensure_ascii=False),
                "relay_stats": json.dumps(relay_stats, ensure_ascii=False),
                "recommended_relays": json.dumps(recommended_relays, ensure_ascii=False),
                "is_learned_flag": True,
                "record_datetime": agg_time.strftime("%Y-%m-%d %H:%M:%S")
            }

            stats_text = (
                f"농장코드: {farm_id}, 재배사코드: {house_id}, "
                f"날짜: {agg_time.strftime('%Y-%m-%d')}, 시간대: {agg_time.hour}시 {agg_time.minute:02d}분\n\n "
                f"[센서 통계]\n"
            )
            for key, stat in sensor_stats.items():
                stats_text += f"{cfg.get_sensor_name(key)}: 평균 {stat['mean']:.1f}, 최소 {stat['min']:.1f}, 최대 {stat['max']:.1f}\n"

            stats_text += "\n[릴레이 통계]\n"
            for key, stat in relay_stats.items():
                stats_text += f"{cfg.search_relay_function('rfm', 'relay_name', key, 'function_detail')}: {stat['on_ratio']:.2f} 가동률 ({stat['on_minutes']:.1f}분)\n"

            stats_text += "\n[릴레이 권장 설정]\n"
            for key, value in recommended_relays.items():
                stats_text += f"{cfg.search_relay_function('rfm', 'relay_name', key, 'function_detail')}: 권장 가동률 {value:.2f}\n"

            try:
                doc_id = cra._doc_id_generator("stats", farm_id, house_id, agg_time.strftime("%Y-%m-%d %H:%M:%S"))
                cra.upsert_collection_data("analyze_ten_minutes_stats", cfg.stats_collection(), doc_id, stats_text, stats_meta)
                logger.debug(f"[STATS 저장 완료] → {doc_id}")
            except Exception as e:
                logger.error(f"STATS 저장 실패: {e}")
                import traceback
                logger.error(traceback.format_exc())
    except Exception as e:
        logger.error(f"analyze_ten_minutes_stats 처리 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())

# ----------------------------------------------------------------------------------------------------------
# 
# ----------------------------------------------------------------------------------------------------------
def analyze_ten_minutes_optimal(farm_id, house_id, farm_name, house_name, agg_time, sensor_means, relay_means, crops_df):
    try:
        crops_df["record_datetime"] = pd.to_datetime(crops_df["record_datetime"], errors="coerce")
        crops_df = crops_df.dropna(subset=["record_datetime"])

        crop_match = crops_df[
            (crops_df["farm_id"] == int(farm_id)) &
            (crops_df["house_id"] == int(house_id)) &
            (crops_df["record_datetime"] >= agg_time - timedelta(minutes=cfg.STATS_INTERVAL_MINUTES)) &
            (crops_df["record_datetime"] < agg_time)
        ]
        if crop_match.empty:
            logger.debug(f"[OPTIMAL] 스킵됨 - 생육 데이터 없음 (farm={farm_id}, house={house_id}, time={agg_time})")
            return

        if not sensor_means or len(sensor_means) < 3:
            logger.debug(f"[OPTIMAL] 스킵됨 - 유효 센서 평균 부족 ({len(sensor_means)}개): {agg_time}")
            return

        indoor_temp = sensor_means.get("indoor_temperature_value", 0)
        if indoor_temp <= 0:
            logger.warning(f"[OPTIMAL] 스킵됨 - 유효 indoor_temp 없음 또는 0 이하: {agg_time}")
            return

        is_daytime = 6 <= agg_time.hour < 18
        recommended_relays = {}

        # 수온히터 (온도가 낮을 때)
        if indoor_temp < 18:
            recommended_relays["relay_1st_flag"] = 0.8
        else:
            recommended_relays["relay_1st_flag"] = 0.2

        # 환풍기 (온도가 높을 때, 주간)
        if indoor_temp > 25 and is_daytime:
            recommended_relays["relay_5st_flag"] = 0.9
            recommended_relays["relay_6st_flag"] = 0.9
        else:
            recommended_relays["relay_5st_flag"] = relay_means.get("relay_5st_flag", 0.5)
            recommended_relays["relay_6st_flag"] = relay_means.get("relay_6st_flag", 0.5)

        # 내부히터 (온도가 낮을 때, 야간)
        if indoor_temp < 18 and not is_daytime:
            recommended_relays["relay_9st_flag"] = 0.9
        else:
            recommended_relays["relay_9st_flag"] = 0.1

        recommended_relays["relay_2st_flag"] = relay_means.get("relay_2st_flag", 0.6)
        recommended_relays["relay_7st_flag"] = 0.9 if is_daytime else 0.1
        recommended_relays["relay_10st_flag"] = relay_means.get("relay_10st_flag", 0.7)

        optimal_text = (
            f"농장코드: {farm_id}, 재배사코드: {house_id}, "
            f"날짜: {agg_time.strftime('%Y-%m-%d')}, 시간대: {agg_time.hour}시 {agg_time.minute:02d}분\n\n"
            f"[최적 환경 조건 - 생육 데이터 기반]\n센서 평균 기반으로 도출된 권장 릴레이 설정입니다.\n"
        )
        for key, value in recommended_relays.items():
            relay_name = cfg.search_relay_function('rfm', 'relay_name', key, 'function_detail')
            optimal_text += f"{relay_name}: 권장 가동률 {value:.2f}\n"

        optimal_meta = {
            "farm_id": farm_id,
            "farm_name": farm_name,
            "house_id": house_id,
            "house_name": house_name,
            "date": agg_time.date().strftime('%Y-%m-%d'),
            "hour_of_day": agg_time.hour,
            "minute_interval": cfg.STATS_INTERVAL_MINUTES,
            "data_type": "optimal_conditions",
            "recommended_relays": json.dumps(recommended_relays, ensure_ascii=False),
            "sensor_means": json.dumps(sensor_means, ensure_ascii=False),
            "relay_means": json.dumps(relay_means, ensure_ascii=False),
            "record_datetime": agg_time.strftime("%Y-%m-%d %H:%M:%S")
        }

        doc_id = cra._doc_id_generator("optimal", farm_id, house_id, agg_time.strftime("%Y-%m-%d %H:%M:%S"))
        cra.upsert_collection_data("analyze_ten_minutes_optimal", cfg.optimal_collection(), doc_id, optimal_text, optimal_meta)
        logger.info(f"[OPTIMAL] 저장 성공: {doc_id}")

    except Exception as e:
        logger.error(f"[OPTIMAL] 저장 실패 - {agg_time}: {e}")
        import traceback
        logger.error(traceback.format_exc())


# -----------------------------------------------------------
# **  데이터프레임 정제
#     데이터프레임 정제 및 변환
#     데이터프레임 정제 및 시간 집계 컬럼 추가
#     VectorDB 저장 주기에 맞게 집계 필드를 추가합니다.
#   - source_collection: 3분단위 집계
#   - stats_collection: 10분단위 집계
#   - optimal_collection: 10분단위 집계
#   - learned_collection: 1시간단위 집계
# -----------------------------------------------------------
def clean_dataframe(df):
    if df is None or df.empty:
        logger.warning(" 데이터프레임 정제: 입력이 None이거나 비어 있음")
        return pd.DataFrame()

    try:
        logger.info(f" 데이터프레임 정제 시작: {len(df)}행")

        df = standardize_column_names(df)
        df = process_datetime_fields(df)

        df_cleaned = clean_numeric_fields(df)
        if df_cleaned is None:
            logger.warning(" clean_numeric_fields() 결과가 None → 원본 유지")
            df_cleaned = df
        df = df_cleaned

        df_bool = process_boolean_fields(df)
        if df_bool is None:
            logger.warning(" process_boolean_fields() 결과가 None → 원본 유지")
            df_bool = df
        df = df_bool

        final_len = len(df)
        logger.info(f" 데이터프레임 정제 완료: {final_len}행")
        
        return df

    except Exception as e:
        logger.error(f" clean_dataframe 처리 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return pd.DataFrame()

# -----------------------------------------------------------
# 표준화된 컬럼명 생성
# -----------------------------------------------------------
def standardize_column_names(df):
    if df is None or df.empty:
        logger.warning(" 수치 필드 정제: (standardize_column_names)데이터프레임이 비어 있거나 None입니다.")
        return pd.DataFrame() 
        
    camel_case_mapping = {key: key for key in cfg.SENSOR_FIELD_MAPPING.keys()}
    
    for old_col, new_col in camel_case_mapping.items():
        if old_col in df.columns and new_col not in df.columns:
            df[new_col] = df[old_col]
    
    return df

# -----------------------------------------------------------
# 날짜 관련 필드 처리
# -----------------------------------------------------------
def process_datetime_fields(df):
    if df is None or df.empty:
        return pd.DataFrame() 
        
    try:
        if 'record_datetime' in df.columns:
            before_type = df['record_datetime'].dtype
            df['record_datetime'] = pd.to_datetime(df['record_datetime'], errors='coerce')
            after_type = df['record_datetime'].dtype
            na_count = df['record_datetime'].isna().sum()
            logger.debug(f" 학습 기초 데이터 record_datetime 변환: {before_type} -> {after_type}, NA 개수: {na_count}")
            
            valid_dates = ~df['record_datetime'].isna()
            if valid_dates.any():
                dates = df.loc[valid_dates, 'record_datetime']
                
                minutes_mod_3 = dates.dt.minute % 3
                df.loc[valid_dates, 'source_agg'] = dates - pd.to_timedelta(minutes_mod_3, unit='m') - pd.to_timedelta(dates.dt.second, unit='s') - pd.to_timedelta(dates.dt.microsecond, unit='us')
                
                minutes_mod_10 = dates.dt.minute % 10
                df.loc[valid_dates, 'stats_agg'] = dates - pd.to_timedelta(minutes_mod_10, unit='m') - pd.to_timedelta(dates.dt.second, unit='s') - pd.to_timedelta(dates.dt.microsecond, unit='us')
                
                df.loc[valid_dates, 'hour_agg'] = dates - pd.to_timedelta(dates.dt.minute, unit='m') - pd.to_timedelta(dates.dt.second, unit='s') - pd.to_timedelta(dates.dt.microsecond, unit='us')
            
            if (~valid_dates).any():
                df.loc[~valid_dates, ['source_agg', 'stats_agg', 'hour_agg']] = None
        
        if 'crop_strt_date' in df.columns:
            df['crop_strt_date'] = pd.to_datetime(df['crop_strt_date'], errors='coerce')
        
        if 'crop_end_date' in df.columns:
            df['crop_end_date'] = pd.to_datetime(df['crop_end_date'], errors='coerce')
    except Exception as e:
        logger.error(f" record_datetime 처리 중 오류 컬럼내용: {df.columns}, 오류내용: {e}")
    return df

# -----------------------------------------------------------
# 수치형 필드 정제
# -----------------------------------------------------------
def clean_numeric_fields(df):
    if df is None or df.empty:
        logger.warning("수치 필드 정제: (clean_numeric_fields)데이터프레임이 비어 있거나 None입니다.")
        return df if df is not None else pd.DataFrame()

    sensor_columns = list(cfg.SENSOR_FIELD_MAPPING.keys())

    other_numeric_columns = [
        'crop_qtty', 'crop_grde_qtty_1', 'crop_grde_qtty_2', 'crop_grde_qtty_3',
        'crop_grde_qtty_4', 'crop_grde_qtty_5', 'crop_grde_amut_1', 'crop_grde_amut_2',
        'crop_grde_amut_3', 'crop_grde_amut_4', 'crop_grde_amut_5'
    ]
    
    numeric_columns = sensor_columns + other_numeric_columns

    available_columns = [col for col in numeric_columns if col in df.columns]
    if not available_columns:
        logger.warning("수치 필드 정제: (clean_numeric_fields) 유효한 숫자 컬럼이 없음")
        return df

    try:
        df = df.dropna(subset=available_columns, how='all')
    except Exception as e:
        logger.error(f"clean_numeric_fields: dropna 실패 → {available_columns} → {e}")
    
    return df

# -----------------------------------------------------------
# 불리언 필드 처리
# -----------------------------------------------------------
def process_boolean_fields(df):
    if df is None or df.empty:
        logger.warning("수치 필드 정제: (process_boolean_fields)데이터프레임이 비어 있거나 None입니다.")
        return df if df is not None else pd.DataFrame()

    for col in cfg.RELAY_KEYS:
        if col in df.columns:
            df[col] = df[col].astype(str).str.lower().map({'true': True, 'false': False, '1': True, '0': False})

    return df

# -----------------------------------------------------------
# ** 숫자 컬럼 정제
# -----------------------------------------------------------
def clean_numeric_column(column):
    logger.debug(f" 숫자 컬럼 정제: {column.name if hasattr(column, 'name') else '이름 없음'}")

    try:
        cleaned = column.apply(lambda x: cfg.clean_sensor_value(x))
        numeric = pd.to_numeric(cleaned, errors='coerce')

        mean = numeric.mean(skipna=True)
        std = numeric.std(skipna=True)

        if not pd.isna(mean) and not pd.isna(std) and std > 0:
            lower_bound = mean - 3 * std
            upper_bound = mean + 3 * std
            numeric = numeric.clip(lower=lower_bound, upper=upper_bound)

        return numeric
    except Exception as e:
        logger.info(f" 숫자 컬럼 정제 중 오류: {e}")
        return pd.Series([None] * len(column))

# -------------------------------------------------------------------
# 현재 센서 데이터를 기반으로 릴레이 권장 설정을 계산
# -------------------------------------------------------------------
def analyze_relay_recommendations(farm_id, hour, sensor_data):
    """Removed unused function."""
    pass

# -----------------------------------------------------------
# ** 데이터 파일 로드 및 정제
# -----------------------------------------------------------
def load_data_file(file_path, data_type):
    if not os.path.exists(file_path):
        logger.warning(f" {data_type} 데이터 파일이 존재하지 않습니다: {file_path}")
        return pd.DataFrame()

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        df = pd.DataFrame(data)
        logger.info(f" {data_type} 데이터 로드 성공: {len(df)}건")

        if df is None or df.empty:
            logger.warning(f" {data_type} 원본 데이터프레임이 비어 있음")
            return pd.DataFrame()

        df = clean_dataframe(df)
        if df.empty:
            logger.warning(f" {data_type} 정제 결과 DataFrame이 비어 있음")
            return pd.DataFrame()

        if 'record_datetime' in df.columns:
            df['record_datetime'] = pd.to_datetime(df['record_datetime'], errors='coerce')

            if data_type == 'units':
                df['hour_of_day'] = df['record_datetime'].dt.hour
                df['ten_minute_interval'] = df['record_datetime'].dt.minute // 10
                df['time_interval_id'] = df['hour_of_day'].astype(str) + '_' + df['ten_minute_interval'].astype(str)

        for id_col in ['farm_id', 'house_id']:
            if id_col in df.columns and pd.api.types.is_numeric_dtype(df[id_col]):
                df[id_col] = df[id_col].astype(str)

        return df

    except Exception as e:
        logger.error(f" {data_type} 데이터 파일 로드 및 정제 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return pd.DataFrame()
    
# --------------------------------------------------------------------------
# json 저장시 기록일시, 농장 정보 필수 데이터 조립 
# --------------------------------------------------------------------------
def ensure_required_columns(df, name):
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    farm_id_default = "0"

    if "record_datetime" not in df.columns and "기록일시" in df.columns:
        df["record_datetime"] = pd.to_datetime(df["기록일시"], errors="coerce")
    elif "record_datetime" not in df.columns:
        df["record_datetime"] = pd.to_datetime(now)

    if "기록일시" not in df.columns and "record_datetime" in df.columns:
        df["기록일시"] = df["record_datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    elif "기록일시" not in df.columns:
        df["기록일시"] = now

    if "farm_id" not in df.columns and "농장번호" in df.columns:
        df["farm_id"] = df["농장번호"]
    elif "farm_id" not in df.columns:
        df["farm_id"] = farm_id_default

    if "농장번호" not in df.columns and "farm_id" in df.columns:
        df["농장번호"] = df["farm_id"]
    elif "농장번호" not in df.columns:
        df["농장번호"] = farm_id_default

    return df
    
# --------------------------------------------------------------------------------------
# 원문에서 구조화된 핵심 정보를 추출하는 함수
#       document_content (str): 원문 내용
#       document_type (str): 문서 유형 (crop_info, disease_info, cultivation 등)
# --------------------------------------------------------------------------------------
def extract_structured_information(document_content, document_type='crop_info'):
    structured_info = {
        "document_type": document_type,
        "extracted_data": {},
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    try:
        if document_type == 'crop_info':
            crop_patterns = {
                "상황버섯": r'상황\s*버섯',
                "작약": r'작약',
                "쇠무릎": r'쇠\s*무릎'
            }
            
            crop_name = None
            first_chunk = document_content[:1000]
            
            for crop, pattern in crop_patterns.items():
                if re.search(pattern, first_chunk, re.IGNORECASE):
                    crop_name = crop
                    break
            
            if crop_name:
                structured_info["extracted_data"]["crop_name"] = crop_name
                
                extractors = {
                    "상황버섯": extract_sangwhang_info,
                    "작약": extract_paeonia_info,
                    "쇠무릎": extract_achyranthes_info
                }
                
                if crop_name in extractors:
                    extractors[crop_name](document_content, structured_info)
                
        elif document_type == 'disease_info':
            extract_disease_info(document_content, structured_info)
        
        return structured_info
        
    except Exception as e:
        logger.error(f"구조화 정보 추출 중 오류: {e}")
        structured_info["error"] = str(e)
        return structured_info

# --------------------------------------------------------------------------------------
# 상황버섯 정보 추출 함수
# --------------------------------------------------------------------------------------
def extract_sangwhang_info(document_content, structured_info):
    # 추출 패턴을 사전으로 정의하여 코드 간결화
    extraction_patterns = {
        "general_info": (r'Ⅰ\.\s*상황버섯\s*일반현황\s*(.*?)(?=Ⅱ\.)', "일반현황"),
        "benefits": (r'Ⅱ\.\s*상황버섯\s*효능\s*(.*?)(?=Ⅲ\.)', "효능"),
        "cultivation": (r'Ⅲ\.\s*상황버섯\s*재배방법\s*(.*?)(?=\s*\d+\.\s*참고)', "재배방법"),
        "spawn_production": (r'1\.\s*종균\s*생산\s*(.*?)(?=2\.)', "종균생산"),
        "fruiting_conditions": (r'4\.\s*상황버섯\s*자실체\s*발생\s*(.*?)(?=5\.)', "자실체 발생")
    }
    
    for key, (pattern, description) in extraction_patterns.items():
        match = re.search(pattern, document_content, re.DOTALL)
        if match:
            extracted_text = match.group(1).strip()
            structured_info["extracted_data"][key] = extracted_text
            logger.debug(f" '{description}' 정보 추출 성공: {len(extracted_text)} 자")
        else:
            logger.debug(f" '{description}' 정보 추출 실패")

# --------------------------------------------------------------------------------------
# 작약 정보 추출 함수
# --------------------------------------------------------------------------------------
def extract_paeonia_info(document_content, structured_info):
    characteristics_match = re.search(r'2\.\s*식물의\s*성상\s*(.*?)(?=3\.)', document_content, re.DOTALL)
    if characteristics_match:
        structured_info["extracted_data"]["plant_characteristics"] = characteristics_match.group(1).strip()
    
    components_match = re.search(r'라\.\s*주요\s*성분\s*및\s*효능\s*(.*?)(?=3\.)', document_content, re.DOTALL)
    if components_match:
        structured_info["extracted_data"]["components_benefits"] = components_match.group(1).strip()
    
    environment_match = re.search(r'3\.\s*재배환경\s*(.*?)(?=4\.)', document_content, re.DOTALL)
    if environment_match:
        structured_info["extracted_data"]["cultivation_environment"] = environment_match.group(1).strip()
    
    cultivation_match = re.search(r'4\.\s*재배법\s*(.*?)(?=5\.)', document_content, re.DOTALL)
    if cultivation_match:
        structured_info["extracted_data"]["cultivation_method"] = cultivation_match.group(1).strip()
    
    disease_match = re.search(r'5\.\s*병해충\s*방제\s*(.*?)(?=6\.)', document_content, re.DOTALL)
    if disease_match:
        structured_info["extracted_data"]["disease_control"] = disease_match.group(1).strip()
    
    harvest_match = re.search(r'6\.\s*수확\s*및\s*조제\s*(.*?)(?=7\.)', document_content, re.DOTALL)
    if harvest_match:
        structured_info["extracted_data"]["harvest_processing"] = harvest_match.group(1).strip()

# --------------------------------------------------------------------------------------
# 쇠무릎 정보 추출 함수
# --------------------------------------------------------------------------------------
def extract_achyranthes_info(document_content, structured_info):
    general_info = re.search(r'쇠무릎(.*?)(?=\n\s*\d+\.|\Z)', document_content, re.DOTALL)
    if general_info:
        structured_info["extracted_data"]["general_info"] = general_info.group(1).strip()
    
    components_match = re.search(r'다\.\s*주요\s*성분\s*및\s*용도\s*(.*?)(?=\n\s*\d+\.)', document_content, re.DOTALL)
    if components_match:
        structured_info["extracted_data"]["components_uses"] = components_match.group(1).strip()
    
    env_match = re.search(r'3\.\s*재배환경\s*(.*?)(?=\n\s*\d+\.)', document_content, re.DOTALL)
    if env_match:
        structured_info["extracted_data"]["cultivation_environment"] = env_match.group(1).strip()

# --------------------------------------------------------------------------------------
# 병해충 정보 추출 함수
# --------------------------------------------------------------------------------------
def extract_disease_info(document_content, structured_info):
    disease_matches = re.finditer(r'(\d+\)\s*([^\n]+)병[^\n]*)\s*\n\s*가\)\s*병원균[^\n]*\n(.*?)(?=\s*\d+\)\s*|\Z)', document_content, re.DOTALL)
    diseases = []
    for match in disease_matches:
        disease_name = match.group(2).strip() + "병"
        description = match.group(3).strip()
        
        pathogen_match = re.search(r'병원균은\s*([^\.]+)\.', description)
        pathogen = pathogen_match.group(1).strip() if pathogen_match else ""
        
        symptom_match = re.search(r'병징\s*\n(.*?)(?=\s*나\))', description, re.DOTALL)
        symptom = symptom_match.group(1).strip() if symptom_match else ""
        
        prevention_match = re.search(r'예방\s*및\s*방제\s*\n(.*?)(?=\s*\d+\)|\Z)', description, re.DOTALL)
        prevention = prevention_match.group(1).strip() if prevention_match else ""
        
        diseases.append({
            "name": disease_name,
            "pathogen": pathogen,
            "symptom": symptom,
            "prevention": prevention
        })
    
    if diseases:
        structured_info["extracted_data"]["diseases"] = diseases

# ------------------------------------------------------------------------------------------
# 시간 패턴 초기화 함수
# ------------------------------------------------------------------------------------------
def initialize_time_patterns(current_hour):
    return {
        "hour_of_day": current_hour,
        "daily": {
            "temperature": {},
            "humidity": {},
            "co2": {},
            "relay_usage": {}
        },
        "seasonal": {},
        "relay_correlation": {},
        "sensor_correlation": {}
    }

# ------------------------------------------------------------------------------------------
# 센서 데이터 수집 함수
# ------------------------------------------------------------------------------------------
def collect_sensor_data(hour_units):
    sensor_data = {
        "temperature": [],
        "humidity": [],
        "co2": []
    }
    
    for unit in hour_units:
        sensor_data_obj = unit.get("sensor_value", {})
        
        temp_keys = ["indoor_temperature_value", "indoor_temperature_value"]
        for key in temp_keys:
            temp_value = sensor_data_obj.get(key)
            if temp_value is not None:
                sensor_data["temperature"].append(temp_value)
                break
        
        humidity_keys = ["indoor_humidity_value", "indoor_humidity_value"]
        for key in humidity_keys:
            humidity_value = sensor_data_obj.get(key)
            if humidity_value is not None:
                sensor_data["humidity"].append(humidity_value)
                break
        
        co2_keys = ["co2_concentration_value", "co2_concentration_value"]
        for key in co2_keys:
            co2_concentration_valuee = sensor_data_obj.get(key)
            if co2_concentration_valuee is not None:
                sensor_data["co2"].append(co2_concentration_valuee)
                break
    
    return sensor_data

# ------------------------------------------------------------------------------------------
# 센서 데이터로 시간 패턴 업데이트
# ------------------------------------------------------------------------------------------
def update_time_patterns_with_sensor_data(time_patterns, sensor_data, current_hour):
    current_hour_str = str(current_hour)
    
    if sensor_data["temperature"]:
        time_patterns["daily"]["temperature"][current_hour_str] = round(np.mean(sensor_data["temperature"]), 1)
    
    if sensor_data["humidity"]:
        time_patterns["daily"]["humidity"][current_hour_str] = round(np.mean(sensor_data["humidity"]), 1)
    
    if sensor_data["co2"]:
        time_patterns["daily"]["co2"][current_hour_str] = round(np.mean(sensor_data["co2"]), 1)
        
# ------------------------------------------------------------------------------------------
# 릴레이 데이터 분석 및 시간 패턴 업데이트
# ------------------------------------------------------------------------------------------
def analyze_relay_data_for_time_patterns(time_patterns, hour_units, current_hour):
    for key in cfg.RELAY_KEYS:
        relay_values = []
        
        for unit in hour_units:
            relay_data = unit.get("relay_status", {})
            if key in relay_data:
                relay_values.append(relay_data.get(key, False))
        
        if relay_values:
            on_ratio = sum(1 for v in relay_values if v) / len(relay_values)
            
            if "relay_usage" not in time_patterns["daily"]:
                time_patterns["daily"]["relay_usage"] = {}
            
            if key not in time_patterns["daily"]["relay_usage"]:
                time_patterns["daily"]["relay_usage"][key] = {}
            
            time_patterns["daily"]["relay_usage"][key][str(current_hour)] = round(on_ratio, 2)
