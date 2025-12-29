# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# JSON 데이터 로더 모듈
# JSON 형식의 데이터 파일을 읽어와 파싱하고 검증하여
# 시스템에서 사용 가능한 형태로 로드합니다.
# --->
# get_training_json_path: 학습용 JSON 파일 경로 반환
# get_units_json_path: Units JSON 파일 경로 반환
# get_crops_json_path: Crops JSON 파일 경로 반환
# fetch_data_from_json: JSON 파일에서 농장 운용 데이터 읽기
# safe_float: 안전한 float 변환
# json_to_vcdb: JSON 데이터를 Vector DB에 저장
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import json

from agri_ai_core.log_utils.log_handlers import setup_logger
from agri_ai_core.shared_modules.config.settings import settings
from agri_ai_core.shared_modules.common.validators import clean_sensor_value, parse_boolean
from agri_ai_core.database.chromadb.client import heartbeat
from agri_ai_core.data_pipeline.data_processor import process_unit_data, process_crop_data

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 학습용 JSON 파일 경로 반환
# --->
# 학습용 JSON 파일 경로 반환
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_training_json_path():
    cache_path = settings.vector.vector_cache or ""
    cache_dir = os.path.dirname(cache_path)
    if cache_dir and not cache_dir.endswith('/'):
        cache_dir = cache_dir + '/'
    filename = settings.house_source_json or ""
    return (cache_dir or "") + filename


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Units JSON 파일 경로 반환
# --->
# Units JSON 파일 경로 반환
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_units_json_path():
    cache_path = settings.vector.vector_cache or ""
    cache_dir = os.path.dirname(cache_path)
    if cache_dir and not cache_dir.endswith('/'):
        cache_dir = cache_dir + '/'
    filename = settings.units_temp_json or ""
    return (cache_dir or "") + filename


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Crops JSON 파일 경로 반환
# --->
# Crops JSON 파일 경로 반환
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_crops_json_path():
    cache_path = settings.vector.vector_cache or ""
    cache_dir = os.path.dirname(cache_path)
    if cache_dir and not cache_dir.endswith('/'):
        cache_dir = cache_dir + '/'
    filename = settings.crops_temp_json or ""
    return (cache_dir or "") + filename


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# JSON 파일에서 데이터 읽기
# --->
# JSON 파일에서 농장 운용 데이터 읽기
# Args:
# limit: 최대 데이터 수
# Returns:
# list: 데이터 목록 또는 None
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def fetch_data_from_json(limit=100000):
    try:
        json_source_file = get_training_json_path()
        if not os.path.exists(json_source_file):
            logger.error(f"JSON 파일이 존재하지 않습니다: {json_source_file}")
            return None

        try:
            with open(json_source_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 실패: {e}")
            return None
        except UnicodeDecodeError:
            try:
                with open(json_source_file, 'r', encoding='cp949') as f:
                    data = json.load(f)
            except Exception as e:
                logger.error(f"다른 인코딩으로도 JSON 파싱 실패: {e}")
                return None

        if data and isinstance(data, list) and len(data) > limit:
            data = data[:limit]

        units_total = sum(len(item.get("units", [])) for item in data)
        crops_total = sum(len(item.get("crops", [])) for item in data)
        logger.info(f"로컬 JSON 파일에서 데이터 읽기 성공 -> 장치: {units_total}건, 생육: {crops_total}건")
        return data
    except Exception as e:
        logger.error(f"JSON 데이터 읽기 중 예외 발생: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 안전한 float 변환
# --->
# 안전한 float 변환
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def safe_float(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# JSON 데이터를 Vector DB로 변환
# --->
# JSON 데이터를 Vector DB에 저장
# Args:
# data_limit: 최대 데이터 수
# Returns:
# bool: 성공 여부
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def json_to_vcdb(data_limit=100000):
    try:
        status = heartbeat()
        if "error" in status:
            logger.error(f"ChromaDB REST API 연결 실패: {status.get('error')}")
            return False

        datas = fetch_data_from_json(limit=data_limit)
        if not datas:
            logger.info("가져올 데이터가 없습니다 !!!")
            return False

        try:
            all_units_data = []
            all_crops_data = []

            for idx, item in enumerate(datas, 1):
                if "units" in item and item["units"]:
                    try:
                        process_unit_data(item)
                    except Exception as e:
                        logger.warning(f"process_unit_data 처리 중 오류: {e}")

                    for unit in item["units"]:
                        if len(unit) < 12:
                            continue
                        try:
                            unit_data = {
                                "farm_id": unit.get("농장코드"),
                                "farm_name": unit.get("농장명"),
                                "house_id": unit.get("재배사코드"),
                                "house_name": unit.get("재배사명"),
                                "data_kind": "UNITS",
                                "record_datetime": unit.get("기록일시"),
                                "indoor_temperature_value": clean_sensor_value(unit.get("내부온도", "0")),
                                "indoor_humidity_value": clean_sensor_value(unit.get("내부습도", "0")),
                                "outdoor_temperature_value": clean_sensor_value(unit.get("외부온도", "0")),
                                "outdoor_humidity_value": clean_sensor_value(unit.get("외부습도", "0")),
                                "co2_concentration_value": clean_sensor_value(unit.get("co2", "0")),
                                "water_temperature_value": clean_sensor_value(unit.get("수온", "0")),
                                "light_level_value": clean_sensor_value(unit.get("광량", "0")),
                                "water_level_value": clean_sensor_value(unit.get("수위", "0")),
                                "relay_1st_flag": parse_boolean(unit.get("수온히터", False)),
                                "relay_2st_flag": parse_boolean(unit.get("습도모터", False)),
                                "relay_3st_flag": parse_boolean(unit.get("배수밸브", False)),
                                "relay_5st_flag": parse_boolean(unit.get("흡입모터", False)),
                                "relay_6st_flag": parse_boolean(unit.get("배출모터", False)),
                                "relay_7st_flag": parse_boolean(unit.get("조명토글", False)),
                                "relay_8st_flag": parse_boolean(unit.get("관수토글", False)),
                                "relay_9st_flag": parse_boolean(unit.get("내부히터", False)),
                                "relay_10st_flag": parse_boolean(unit.get("순환밸브", False)),
                                "relay_11st_flag": parse_boolean(unit.get("흡입밸브", False)),
                                "relay_14st_flag": parse_boolean(unit.get("배출밸브", False)),
                                "relay_15st_flag": parse_boolean(unit.get("히터밸브", False) if "히터밸브" in unit else False)
                            }
                            all_units_data.append(unit_data)
                        except Exception as e:
                            logger.debug(f"장치 데이터 변환 중 오류: {str(e)}")

                if "crops" in item and item["crops"]:
                    try:
                        process_crop_data(item)
                    except Exception as e:
                        logger.warning(f"process_crop_data 처리 중 오류: {e}")

                    for crop in item["crops"]:
                        try:
                            crop_data = {
                                "farm_id": crop.get("농장코드"),
                                "farm_name": crop.get("농장명"),
                                "house_id": crop.get("재배사코드"),
                                "house_name": crop.get("재배사명"),
                                "data_kind": "CROPS",
                                "record_datetime": crop.get("기록일시"),
                                "crop_strt_date": crop.get("작물시작일자", ""),
                                "crop_end_date": crop.get("작물종료일자", ""),
                                "code_name": crop.get("작물코드명", ""),
                                "crop_qtty": safe_float(crop.get("작물량", "0")),
                                "crop_grde_qtty_1": safe_float(crop.get("작물등급량1", "0")),
                                "crop_grde_qtty_2": safe_float(crop.get("작물등급량2", "0")),
                                "crop_grde_qtty_3": safe_float(crop.get("작물등급량3", "0")),
                                "crop_grde_qtty_4": safe_float(crop.get("작물등급량4", "0")),
                                "crop_grde_qtty_5": safe_float(crop.get("작물등급량5", "0")),
                                "crop_grde_amut_1": safe_float(crop.get("작물등급금액1", "0")),
                                "crop_grde_amut_2": safe_float(crop.get("작물등급금액2", "0")),
                                "crop_grde_amut_3": safe_float(crop.get("작물등급금액3", "0")),
                                "crop_grde_amut_4": safe_float(crop.get("작물등급금액4", "0")),
                                "crop_grde_amut_5": safe_float(crop.get("작물등급금액5", "0")),
                                "rmks": crop.get("비고", "")
                            }
                            all_crops_data.append(crop_data)
                        except Exception as e:
                            logger.debug(f"생육 데이터 변환 중 오류: {str(e)}")

        except Exception as e:
            logger.error(f"데이터 처리 및 저장 중 오류: {e}")
            import traceback
            logger.error(traceback.format_exc())

        try:
            if all_units_data:
                units_df_path = get_units_json_path()
                with open(units_df_path, 'w', encoding='utf-8') as f:
                    json.dump(all_units_data, f, ensure_ascii=False, indent=2, default=str)

            if all_crops_data:
                crops_df_path = get_crops_json_path()
                with open(crops_df_path, 'w', encoding='utf-8') as f:
                    json.dump(all_crops_data, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.error(f"분석용 데이터 저장 중 오류: {e}")
            import traceback
            logger.error(traceback.format_exc())

        json_source_file = get_training_json_path()
        unit_house_count = len({(unit.get("farm_id"), unit.get("house_id")) for unit in all_units_data})
        logger.info(f"전체 농장 운용 기본정보 장치정보: {unit_house_count}건, 센서정보: {len(all_units_data)}건, 생육정보: {len(all_crops_data)}건")
        logger.info(f"JSON 파일 {json_source_file} 에서 VectorDB로 저장 완료했습니다.")
        logger.info("Vector DB에 데이터 저장 완료했습니다.")
        return True
    except Exception as e:
        logger.error(f"데이터 처리 중 전체 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
