# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 데이터 분석 모듈
# 센서 데이터, 제어 이력 등을 통계 분석하여 패턴을 찾고,
# 최적 제어 조건을 도출하기 위한 인사이트를 제공합니다.
# --->
# get_growth_status_rank: 생육상태 순위 점수 반환
# is_positive_remark: 리마크 긍정/부정 분석
# initialize_optimal_conditions: 최적 환경 조건 초기화
# initialize_time_patterns: 시간 패턴 초기화
# select_top_crops: 최적 작물 선택
# collect_optimal_data: 최적 환경 데이터 수집
# analyze_temperature_conditions: 온도 조건 분석
# analyze_humidity_conditions: 습도 조건 분석
# analyze_co2_conditions: CO2 조건 분석
# analyze_water_temperature_conditions: 수온 조건 분석
# analyze_light_level_conditions: 광량 조건 분석
# analyze_optimal_conditions: 수집된 데이터를 분석하여 최적 조건 도출
# analyze_farm_optimal_conditions: 농장별 최적 조건 분석
# collect_sensor_data: 센서 데이터 수집
# update_time_patterns_with_sensor_data: 센서 데이터로 시간 패턴 업데이트
# analyze_relay_data_for_time_patterns: 릴레이 데이터 분석 및 시간 패턴 업데이트
# analyze_farm_time_patterns: 농장별 시간 패턴 분석
# process_stats_and_optimal_data: 통계 및 최적 환경 데이터 처리
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import numpy as np
from datetime import datetime

from agri_ai_core.src.logs import setup_logger
from agri_ai_core.config import STATS_INTERVAL_MINUTES, RELAY_KEYS
from agri_ai_core.src.chroma.collections import job_status_collection
from agri_ai_core.src.utils import clean_sensor_value
from agri_ai_core.src.chroma.operations import upsert_collection_data

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 생육상태 순위 키워드
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
RANK_KEYWORDS = {
    "최상": 5, "특상": 5, "특급": 5,
    "상": 4, "1등급": 4, "A급": 4, "우수": 4,
    "중상": 3, "양호": 3, "B급": 3, "2등급": 3,
    "중": 2, "보통": 2, "C급": 2, "3등급": 2,
    "하": 1, "미흡": 1, "D급": 1, "4등급": 1
}
POSITIVE_KEYWORDS = ["좋음", "양호", "우수", "성공", "높음", "품질", "맛", "색상", "크기"]
NEGATIVE_KEYWORDS = ["벌레", "문제", "부족", "실패", "병해", "충해", "질병", "곰팡이", "나쁨", "이상", "낮음"]


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 생육상태 순위 점수 반환
# --->
# 생육상태 순위 점수 반환
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_growth_status_rank(status):
    logger.debug(f"생육상태 순위 분석: {status}")

    if not status or not isinstance(status, str):
        return 0

    for keyword, score in RANK_KEYWORDS.items():
        if keyword in status:
            logger.debug(f"생육상태 '{status}'에서 키워드 '{keyword}' 발견, 점수: {score}")
            return score

    return 0


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 리마크 긍정/부정 분석
# --->
# 리마크 긍정/부정 분석
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 최적 환경 조건 초기화
# --->
# 최적 환경 조건 초기화
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 시간 패턴 초기화
# --->
# 시간 패턴 초기화
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 최적 작물 선택
# --->
# 최적 작물 선택
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 최적 환경 데이터 수집
# --->
# 최적 환경 데이터 수집
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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
            logger.info(f"날짜 변환 오류: {e}")
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
                    logger.info(f"장치 데이터 날짜 변환 오류: {e2}")
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 온도 조건 분석
# --->
# 온도 조건 분석
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def analyze_temperature_conditions(sensor_data, optimal_conditions):
    day_temps = []
    night_temps = []

    for entry in sensor_data:
        temp_value = None
        if "values" in entry and "indoor_temperature_value" in entry["values"]:
            temp_value = clean_sensor_value(entry["values"]["indoor_temperature_value"])
        elif "indoor_temperature_value" in entry:
            temp_value = clean_sensor_value(entry["indoor_temperature_value"])

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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 습도 조건 분석
# --->
# 습도 조건 분석
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# CO2 조건 분석
# --->
# CO2 조건 분석
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def analyze_co2_conditions(sensor_data, optimal_conditions):
    co2_concentration_values = [entry["values"].get("co2_concentration_value", 0)
                                for entry in sensor_data
                                if entry["values"].get("co2_concentration_value")]
    if co2_concentration_values:
        optimal_conditions["co2"]["min"] = round(np.percentile(co2_concentration_values, 25), 1)
        optimal_conditions["co2"]["max"] = round(np.percentile(co2_concentration_values, 75), 1)
        optimal_conditions["co2"]["optimal"] = round(np.mean(co2_concentration_values), 1)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 수온 조건 분석
# --->
# 수온 조건 분석
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def analyze_water_temperature_conditions(sensor_data, optimal_conditions):
    water_temps = [entry["values"].get("water_temperature_value", 0)
                   for entry in sensor_data
                   if entry["values"].get("water_temperature_value")]
    if water_temps:
        optimal_conditions["water_temperature"]["min"] = round(np.percentile(water_temps, 25), 1)
        optimal_conditions["water_temperature"]["max"] = round(np.percentile(water_temps, 75), 1)
        optimal_conditions["water_temperature"]["optimal"] = round(np.mean(water_temps), 1)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 광량 조건 분석
# --->
# 광량 조건 분석
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def analyze_light_level_conditions(sensor_data, optimal_conditions):
    light_levels = [entry["values"].get("light_level_value", 0)
                    for entry in sensor_data
                    if entry["values"].get("light_level_value")]
    if light_levels:
        optimal_conditions["light_level"]["min"] = round(np.percentile(light_levels, 25), 1)
        optimal_conditions["light_level"]["max"] = round(np.percentile(light_levels, 75), 1)
        optimal_conditions["light_level"]["optimal"] = round(np.mean(light_levels), 1)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 최적 조건 분석
# --->
# 수집된 데이터를 분석하여 최적 조건 도출
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def analyze_optimal_conditions(optimal_data, current_hour):
    optimal_conditions = initialize_optimal_conditions(current_hour)

    sensor_data = optimal_data.get("sensor_data", [])

    if not sensor_data:
        return optimal_conditions

    analyze_temperature_conditions(sensor_data, optimal_conditions)
    analyze_humidity_conditions(sensor_data, optimal_conditions)
    analyze_co2_conditions(sensor_data, optimal_conditions)
    analyze_water_temperature_conditions(sensor_data, optimal_conditions)
    analyze_light_level_conditions(sensor_data, optimal_conditions)

    return optimal_conditions


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 농장별 최적 조건 분석
# --->
# 농장별 최적 조건 분석
# Args:
# data: 농장 데이터 딕셔너리
# Returns:
# dict: 최적 환경 조건
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def analyze_farm_optimal_conditions(data):
    current_hour = datetime.now().hour

    units_count = len(data.get("units_data", []))
    crops_count = len(data.get("crops_data", []))
    logger.debug(f"최적 조건 분석 입력 데이터: 장치 데이터 {units_count}건, 작물 데이터 {crops_count}건")

    optimal_conditions = initialize_optimal_conditions(current_hour)

    if not data.get("units_data"):
        logger.warning("최적 조건 분석: units_data 없음")
        return optimal_conditions

    if not data.get("crops_data"):
        logger.warning("최적 조건 분석: crops_data 없음 (빈 목록 처리)")

    try:
        top_crops = select_top_crops(data.get("crops_data", []))
        if not top_crops:
            top_crops = [{"crop_strt_date": datetime.now().strftime("%Y-%m-%d"),
                          "crop_end_date": datetime.now().strftime("%Y-%m-%d")}]

        optimal_data = collect_optimal_data(data["units_data"], top_crops, current_hour)

        optimal_conditions = analyze_optimal_conditions(optimal_data, current_hour)

    except Exception as e:
        logger.error(f"최적 환경 조건 분석 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())

    return optimal_conditions


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 센서 데이터 수집
# --->
# 센서 데이터 수집
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def collect_sensor_data(hour_units):
    sensor_data = {"temperature": [], "humidity": [], "co2": []}
    field_map = {
        "temperature": "indoor_temperature_value",
        "humidity": "indoor_humidity_value",
        "co2": "co2_concentration_value",
    }

    for unit in hour_units:
        sensor_data_obj = unit.get("sensor_value", {})
        for metric, field_key in field_map.items():
            raw_value = sensor_data_obj.get(field_key)
            if raw_value is None:
                continue
            sensor_data[metric].append(clean_sensor_value(raw_value))

    return sensor_data


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 센서 데이터로 시간 패턴 업데이트
# --->
# 센서 데이터로 시간 패턴 업데이트
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def update_time_patterns_with_sensor_data(time_patterns, sensor_data, current_hour):
    current_hour_str = str(current_hour)

    if sensor_data["temperature"]:
        time_patterns["daily"]["temperature"][current_hour_str] = round(np.mean(sensor_data["temperature"]), 1)

    if sensor_data["humidity"]:
        time_patterns["daily"]["humidity"][current_hour_str] = round(np.mean(sensor_data["humidity"]), 1)

    if sensor_data["co2"]:
        time_patterns["daily"]["co2"][current_hour_str] = round(np.mean(sensor_data["co2"]), 1)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 릴레이 데이터 분석 및 시간 패턴 업데이트
# --->
# 릴레이 데이터 분석 및 시간 패턴 업데이트
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def analyze_relay_data_for_time_patterns(time_patterns, hour_units, current_hour):
    for key in RELAY_KEYS:
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 농장별 시간 패턴 분석
# --->
# 농장별 시간 패턴 분석
# Args:
# data: 농장 데이터
# hour: 시간대
# Returns:
# dict: 시간 패턴
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def analyze_farm_time_patterns(data, hour):
    logger.debug("농장 시간 패턴 분석 시작")

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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 통계 및 최적 환경 데이터 처리
# --->
# 통계 및 최적 환경 데이터 처리
# Returns:
# bool: 성공 여부
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def process_stats_and_optimal_data():
    try:
        logger.info("-" * 100)
        logger.info("통계 및 최적 환경 데이터 처리 시작")
        start_time = datetime.now()

        now = datetime.now()
        interval_min = STATS_INTERVAL_MINUTES or 10
        if interval_min == 0:
            logger.warning("STATS_INTERVAL_MINUTES가 0입니다. 10으로 보정합니다.")
            interval_min = 10

        current_minute = (now.minute // interval_min) * interval_min
        stats_timestamp = now.replace(minute=current_minute, second=0, microsecond=0)
        stats_time_str = stats_timestamp.strftime("%Y-%m-%d %H:%M:00")
        logger.debug(f"{interval_min}분 단위 집계 시간: {stats_time_str}")

        # 마지막 실행 시간 기록
        try:
            last_run_id = "last_learned_datetime"
            current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            result = upsert_collection_data(
                "process_stats_and_optimal_data",
                job_status_collection(),
                last_run_id,
                f"마지막실행일시: {current_datetime}",
                {"last_run": current_datetime}
            )
            logger.info(f"마지막 실행 시간 기록 {result}: {current_datetime}")
        except Exception as e:
            logger.error(f"마지막 실행 시간 기록 중 오류: {e}")

        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()

        logger.debug(f"통계 및 최적 환경 데이터 처리 완료 (처리시간: {processing_time:.3f}초)")
        logger.debug("-" * 100)
        return True

    except Exception as e:
        logger.error(f"process_stats_and_optimal_data 통계 및 최적 환경 데이터 처리 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
