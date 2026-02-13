# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 모델 학습 관리 모듈
# LLM 파인튜닝, 임베딩 모델 학습 등의 프로세스를 관리하고,
# 학습 진행 상황을 모니터링하며 결과를 저장합니다.
# --->
# verify_chroma_connection: ChromaDB 연결 상태 확인
# create_default_crop_entry: 기본 작물 데이터 생성
# create_default_units_entry: 기본 장치 데이터 생성
# supplement_optimal_conditions: 최적 조건 보완 데이터 병합
# process_farm_hour_data: 농장별 시간대 데이터 처리
# update_ollama_model: LLM 모델 학습
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import json
import pandas as pd
from datetime import datetime

from agri_ai_core.src.logs import setup_logger
from agri_ai_core.src.chroma.collections import source_collection, learned_collection
from agri_ai_core.src.utils.date_utils import parse_datetime
from agri_ai_core.src.utils.conversion import convert_sensor_relay_data
from agri_ai_core.src.chroma.client import heartbeat
from agri_ai_core.src.chroma.operations import (
    get_documents,
    upsert_collection_data,
    generate_doc_id
)
# NOTE: run_data_export was removed during restructuring - json files should already exist
# from agri_ai_core.data_ingestion.json_exporter import run_data_export
from agri_ai_core.src.ai.rag.json_loader import json_to_vcdb
from agri_ai_core.src.chroma.loader import (
    get_unlearned_data,
    update_learned_source_data,
    update_learned_last_status
)
from agri_ai_core.src.ai.learning.data_analyzer import (
    analyze_farm_optimal_conditions,
    analyze_farm_time_patterns,
    process_stats_and_optimal_data
)

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ChromaDB 연결 상태 확인
# --->
# ChromaDB 연결 상태 확인
# Returns:
# bool: 연결 상태
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def verify_chroma_connection():
    try:
        status = heartbeat()
        if "error" in status:
            logger.error(f"ChromaDB 연결 실패: {status['error']}")
            return False
        else:
            return True
    except Exception as e:
        logger.error(f"ChromaDB 연결 확인 중 오류: {e}")
        return False


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 기본 작물 데이터 생성
# --->
# 기본 작물 데이터 생성
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def create_default_crop_entry(farm_id, house_id="0"):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_str = now_str.split(" ")[0]
    return {
        "farm_id": farm_id,
        "house_id": house_id,
        "record_datetime": now_str,
        "기록일시": now_str,
        "농장번호": farm_id,
        "farm_name": "",
        "house_name": "",
        "data_kind": "crops",
        "crop_strt_date": today_str,
        "crop_end_date": today_str,
        "code_name": "",
        "crop_qtty": 0,
        "crop_grde_qtty_1": 0,
        "crop_grde_qtty_2": 0,
        "crop_grde_qtty_3": 0,
        "crop_grde_qtty_4": 0,
        "crop_grde_qtty_5": 0,
        "crop_grde_amut_1": 0,
        "crop_grde_amut_2": 0,
        "crop_grde_amut_3": 0,
        "crop_grde_amut_4": 0,
        "crop_grde_amut_5": 0,
        "grade_1_ratio": 0.0,
        "rmks": "empty_crop_data",
        "source_agg": {},
        "stats_agg": {},
        "hour_agg": {}
    }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 기본 장치 데이터 생성
# --->
# 기본 장치 데이터 생성
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def create_default_units_entry(farm_id, house_id="0"):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "farm_id": farm_id,
        "house_id": house_id,
        "record_datetime": now_str,
        "sensor_value": {},
        "relay_status": {}
    }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 최적 조건 보완
# --->
# 최적 조건 보완 데이터 병합
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def supplement_optimal_conditions(original, supplement):
    if not original:
        return supplement

    if not supplement:
        return original

    result = original.copy()

    # 주요 필드가 0이거나 비어있는 경우 보완 데이터로 대체
    for time_of_day in ["day", "night"]:
        for field in ["temperature", "humidity"]:
            if field in result and time_of_day in result[field]:
                for measure in ["min", "max", "optimal"]:
                    if (result[field][time_of_day][measure] == 0 and
                        supplement.get(field, {}).get(time_of_day, {}).get(measure, 0) != 0):
                        result[field][time_of_day][measure] = supplement[field][time_of_day][measure]

    # 다른 센서 필드 확인
    for field in ["co2", "water_temperature", "light_level"]:
        if field in result:
            for measure in ["min", "max", "optimal"]:
                if (result[field][measure] == 0 and
                    supplement.get(field, {}).get(measure, 0) != 0):
                    result[field][measure] = supplement[field][measure]

    # 릴레이 설정
    if not result.get("relay_settings") and supplement.get("relay_settings"):
        result["relay_settings"] = supplement["relay_settings"]
    elif result.get("relay_settings") and supplement.get("relay_settings"):
        for relay_key, relay_setting in supplement["relay_settings"].items():
            if relay_key not in result["relay_settings"]:
                result["relay_settings"][relay_key] = relay_setting

    return result


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 농장별 시간대 데이터 처리
# --->
# 농장별 시간대 데이터 처리
# Args:
# farm_id: 농장 ID
# hour: 시간대
# data: 데이터 딕셔너리
# hour_timestamp: 시간 타임스탬프
# Returns:
# dict: 학습된 데이터 또는 None
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def process_farm_hour_data(farm_id, hour, data, hour_timestamp=None):
    if not farm_id or hour is None:
        logger.warning("농장코드 또는 시간대가 유효하지 않습니다.")
        return None

    start_time = datetime.now()

    if not data["units_data"] and not data["crops_data"]:
        logger.info(f"농장 {farm_id}의 시간대 {hour}시 처리할 데이터가 없습니다.")
        return None

    units_count = len(data["units_data"])
    crops_count = len(data["crops_data"])

    # 센서와 릴레이 데이터 변환
    for unit in data["units_data"]:
        converted_data = convert_sensor_relay_data(unit)
        unit["sensor_value"] = converted_data["sensor_data"]
        unit["relay_status"] = converted_data["relay_data"]

    # 최적 환경 조건 분석
    try:
        logger.debug(f"농장 {farm_id} 최적 환경 분석 시작: 장치 데이터 {units_count}건, 작물 데이터 {crops_count}건")
        farm_optimal_conditions = analyze_farm_optimal_conditions(data)
        logger.debug(f"농장 {farm_id} 시간대 {hour}시 최적 환경 조건 분석 완료")
    except Exception as e:
        logger.error(f"최적 환경 조건 분석 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        farm_optimal_conditions = {
            "hour_of_day": hour,
            "is_manual": False,
            "temperature": {"day": {"min": 0, "max": 0, "optimal": 0}, "night": {"min": 0, "max": 0, "optimal": 0}},
            "humidity": {"day": {"min": 0, "max": 0, "optimal": 0}, "night": {"min": 0, "max": 0, "optimal": 0}},
            "co2": {"min": 0, "max": 0, "optimal": 0},
            "water_temperature": {"min": 0, "max": 0, "optimal": 0},
            "light_level": {"min": 0, "max": 0, "optimal": 0},
            "relay_settings": {}
        }

    # 시간 패턴 분석
    try:
        farm_time_patterns = analyze_farm_time_patterns(data, hour)
    except Exception as e:
        logger.error(f"시간 패턴 분석 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        farm_time_patterns = {
            "hour_of_day": hour,
            "daily": {"temperature": {}, "humidity": {}, "co2": {}, "relay_usage": {}},
            "seasonal": {},
            "relay_correlation": {},
            "sensor_correlation": {}
        }

    target_hour = hour
    filtered_datetimes = []

    if hour_timestamp is not None:
        base_dt = hour_timestamp
    else:
        for item in data.get("units_data", []) + data.get("crops_data", []):
            dt = item.get("record_datetime")
            if dt:
                try:
                    parsed = pd.to_datetime(dt)
                    if parsed.hour == target_hour:
                        filtered_datetimes.append(parsed)
                except:
                    continue

        if filtered_datetimes:
            base_dt = min(filtered_datetimes).replace(minute=0, second=0, microsecond=0)
        else:
            logger.warning(f"데이터 없음 → 농장 {farm_id}, 시간대 {hour}시 스킵")
            return None

    hour_agg = base_dt.strftime("%Y-%m-%d %H:%M:%S")

    farm_learned_data = {
        "farm_id": farm_id,
        "hour_of_day": hour,
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "optimal_conditions_str": json.dumps(farm_optimal_conditions, ensure_ascii=False),
        "time_patterns_str": json.dumps(farm_time_patterns, ensure_ascii=False),
        "is_manual": False,
        "data_type": "learned_data",
        "farm_id_str": farm_id,
        "hour_str": str(hour),
        "record_datetime": hour_agg,
        "hour_agg": hour_agg
    }

    end_time = datetime.now()
    processing_time = (end_time - start_time).total_seconds()
    logger.debug(f"농장 {farm_id} 시간대 {hour}시 데이터 처리 완료: 장치 {units_count}건, 작물 {crops_count}건 처리 (처리시간: {processing_time:.3f}초)")

    return farm_learned_data


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 모델 업데이트 (학습)
# --->
# LLM 모델 학습
# Args:
# after_date: 시작 일자
# top_cnt: 최대 처리 건수
# Returns:
# list: 학습 결과 목록
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def update_ollama_model(after_date=None, top_cnt=0):
    start_time = datetime.now()
    current_hour = start_time.hour

    logger.info("=" * 100)
    logger.info(f"LLM 학습 시작 - 시간대: {current_hour}시, 시작일자: {after_date}, 건수: {top_cnt})")

    learned_results = []

    if not verify_chroma_connection():
        logger.error("ChromaDB 연결 실패! 학습을 진행할 수 없습니다.")
        return learned_results

    try:
        now = datetime.now()
        hour_timestamp = now.replace(minute=0, second=0, microsecond=0)
        hour_time_str = hour_timestamp.strftime("%Y-%m-%d %H:00:00")

        logger.debug(f"1시간 단위 집계 시간: {hour_time_str}")

        unlearned_datas = get_unlearned_data(after_date, top_cnt)
        if after_date:
            try:
                if isinstance(after_date, str) and after_date.strip().lower() == "all":
                    parsed_after = pd.Timestamp("2000-01-01 00:00:00")
                else:
                    parsed_after = pd.to_datetime(after_date, errors="raise")

                before = len(unlearned_datas)
                unlearned_datas = [
                    d for d in unlearned_datas
                    if pd.to_datetime(d.get("record_datetime", "1970-01-01"), errors="coerce") > parsed_after
                ]
                logger.info(f"after_date 1 필터링 완료: {before}건 → {len(unlearned_datas)}건")
            except Exception as e:
                logger.warning(f"after_date 1 필터링 중 오류: {e}")

        source_results = get_documents(collection_name=source_collection())
        if "error" in source_results and "not found" in str(source_results.get("error", "")).lower():
            logger.info("source_collection이 없거나 데이터가 없습니다. 데이터 초기화를 시도합니다.")

            # NOTE: run_data_export() was removed - assuming JSON files already exist
            # run_data_export()
            # logger.info("PostgreSQL에서 JSON으로 데이터 추출 완료")

            json_to_vcdb()
            logger.info("기존 JSON에서 ChromaDB로 데이터 이관 완료")

            unlearned_datas = get_unlearned_data(after_date, top_cnt)

        if not unlearned_datas:
            logger.info("학습할 신규 데이터가 없습니다.")
            end_time = datetime.now()
            processing_time = (end_time - start_time).total_seconds()
            logger.info(f"LLM 학습 종료: 처리할 데이터 없음 (처리시간: {processing_time:.3f}초)")
            logger.info("=" * 100)
            return []

        data_count = len(unlearned_datas)
        logger.info(f"신규 데이터 {data_count}건 학습 시작 !!! 기타건수: {len(source_results)}")

        # 통계 및 최적 환경 데이터 처리
        stats_start = datetime.now()
        try:
            process_stats_and_optimal_data()
            stats_end = datetime.now()
            stats_time = (stats_end - stats_start).total_seconds()
            logger.debug(f"통계 및 최적 환경 데이터 처리 완료 (처리시간: {stats_time:.3f}초)")
        except Exception as e:
            logger.error(f"update_ollama_model 통계 및 최적 환경 데이터 처리 중 오류: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # 데이터 분류
        farm_hour_data = {}
        processed_count = 0
        skipped_count = 0

        try:
            logger.debug("데이터를 농장-시간별로 분류 시작")
            for data in unlearned_datas:
                farm_id = data.get("farm_id")
                if not farm_id:
                    skipped_count += 1
                    continue

                record_datetime = data.get("record_datetime")
                if not record_datetime:
                    record_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    logger.warning(f"record_datetime이 없어 현재 시간으로 대체: {record_datetime}")
                parsed_dt = parse_datetime(record_datetime) or datetime.now()
                data_hour = parsed_dt.hour if parsed_dt.hour is not None else current_hour

                hour_timestamp = parsed_dt.replace(minute=0, second=0, microsecond=0)
                hour_key = hour_timestamp.strftime("%Y-%m-%d %H:00:00")
                farm_hour_key = f"{farm_id}_{hour_key}"

                if farm_hour_key not in farm_hour_data:
                    farm_hour_data[farm_hour_key] = {
                        "farm_id": farm_id,
                        "hour": parsed_dt.hour,
                        "hour_timestamp": hour_timestamp,
                        "units_data": [],
                        "crops_data": []
                    }

                data_kind = str(data.get("data_kind")).lower()

                if "units" in data_kind:
                    converted_data = convert_sensor_relay_data(data)
                    sensor_data = converted_data.get("sensor_data", {})
                    relay_data = converted_data.get("relay_data", {})

                    unit_entry = {
                        "farm_id": farm_id,
                        "house_id": data.get("house_id"),
                        "record_datetime": record_datetime,
                        "hour_of_day": data_hour,
                        "sensor_value": sensor_data,
                        "relay_status": relay_data
                    }

                    farm_hour_data[farm_hour_key]["units_data"].append(unit_entry)

                elif "crops" in data_kind:
                    total_yield = data.get("total_yield", 0)
                    grade_1_yield = data.get("grade_1_yield", 0)
                    grade_1_ratio = grade_1_yield / total_yield if total_yield > 0 else 0

                    crop_entry = {
                        "farm_id": farm_id,
                        "house_id": data.get("house_id"),
                        "record_datetime": record_datetime,
                        "hour_of_day": data_hour,
                        "crop_strt_date": data.get("crop_strt_date"),
                        "crop_end_date": data.get("crop_end_date"),
                        "code_name": data.get("growth_status"),
                        "crop_qtty": total_yield,
                        "crop_grde_qtty_1": grade_1_yield,
                        "crop_grde_qtty_2": data.get("grade_2_yield"),
                        "crop_grde_qtty_3": data.get("grade_3_yield"),
                        "crop_grde_qtty_4": data.get("grade_4_yield"),
                        "crop_grde_qtty_5": data.get("grade_5_yield"),
                        "crop_grde_amut_1": data.get("grade_1_price"),
                        "crop_grde_amut_2": data.get("grade_2_price"),
                        "crop_grde_amut_3": data.get("grade_3_price"),
                        "crop_grde_amut_4": data.get("grade_4_price"),
                        "crop_grde_amut_5": data.get("grade_5_price"),
                        "rmks": data.get("alert"),
                        "grade_1_ratio": grade_1_ratio
                    }

                    farm_hour_data[farm_hour_key]["crops_data"].append(crop_entry)

                processed_count += 1
        except Exception as e:
            logger.error(f"데이터 변환 중 오류: {e}")
            import traceback
            logger.error(traceback.format_exc())

        transform_processed_count = processed_count
        farm_hours_count = len(farm_hour_data)
        units_count = sum(len(data.get("units_data", [])) for data in farm_hour_data.values())
        crops_count = sum(len(data.get("crops_data", [])) for data in farm_hour_data.values())

        logger.debug(f"데이터 변환 완료: {transform_processed_count}건 처리, {skipped_count}건 건너뜀")
        logger.info(f"농장-시간대 조합: {farm_hours_count}개, 장치 데이터: {units_count}건, 작물 데이터: {crops_count}건")

        learned_results = []
        process_success_count = 0
        process_error_count = 0

        for farm_hour_key, data in farm_hour_data.items():
            try:
                farm_id = data.get("farm_id")
                hour = data.get("hour")
                house_id = data.get("house_id", "0")

                # crops_data 보완
                if not data.get("crops_data"):
                    logger.debug(f"농장 {farm_id}, 시간대 {hour} crops_data가 없어 기본 데이터 추가")
                    data["crops_data"] = [create_default_crop_entry(str(farm_id or "0"), house_id)]

                # units_data 보완
                if not data.get("units_data"):
                    logger.info(f"농장 {farm_id}, 시간대 {hour} units_data가 없어 더미 추가")
                    data["units_data"] = [create_default_units_entry(farm_id, house_id)]

                # 학습 실행
                farm_learned_data = process_farm_hour_data(
                    farm_id, hour, data, data.get("hour_timestamp")
                )

                if farm_learned_data:
                    learned_results.append(farm_learned_data)
                    process_success_count += 1

            except Exception as e:
                logger.error(f"농장 {farm_id}, 시간대 {hour}시 처리 중 오류: {e}")
                import traceback
                logger.error(traceback.format_exc())
                process_error_count += 1

        logger.info(f"농장-시간대 조합 처리 완료: {process_success_count}개 성공, {process_error_count}개 실패")

        # 학습 결과 저장
        if learned_results:
            try:
                success_count = 0
                for result in learned_results:
                    try:
                        farm_id = result.get("farm_id")
                        hour = result.get("hour")

                        base_dt_str = result.get("record_datetime") or result.get("hour_agg")
                        base_dt = pd.to_datetime(base_dt_str)
                        base_dt = base_dt.replace(minute=0, second=0, microsecond=0)

                        text = json.dumps(result, ensure_ascii=False)
                        metadata = {
                            "farm_id": farm_id,
                            "hour": hour,
                            "record_datetime": base_dt.strftime("%Y-%m-%d %H:%M:%S"),
                            "data_type": "learned_data",
                            "is_learned_flag": True
                        }

                        doc_id = generate_doc_id("learned", farm_id, 0, base_dt.strftime("%Y-%m-%d %H:%M:%S"))
                        status = upsert_collection_data(
                            calledby="update_ollama_model",
                            collection=learned_collection(),
                            doc_id=doc_id,
                            document=text,
                            metadata=metadata
                        )

                        if status in ["added", "updated"]:
                            success_count += 1
                        else:
                            logger.warning(f"문서 저장 실패 - doc_id={doc_id}, status={status}")
                    except Exception as e:
                        logger.error(f"문서 저장 중 예외 발생: {e}")
                        import traceback
                        logger.error(traceback.format_exc())

                if success_count > 0:
                    update_learned_source_data(unlearned_datas)
                    update_learned_last_status()

                    try:
                        learned_items = get_documents(collection_name=learned_collection())
                        learned_count = len(learned_items.get("ids", [])) if "error" not in learned_items else 0
                        logger.info(f"학습 완료: 총 {len(unlearned_datas)}건 처리, learned_collection에 {success_count}건 저장됨 (총 {learned_count}건)")
                    except Exception as e:
                        logger.info(f"학습 완료: 저장 건수 {success_count}건 (컬렉션 조회 실패: {e})")
                else:
                    logger.error(f"저장 실패 - 총 {len(learned_results)}건 중 {success_count}건 성공")

            except Exception as e:
                logger.error(f"학습 결과 저장 중 오류: {e}")
                import traceback
                logger.error(traceback.format_exc())
        else:
            logger.info("학습 결과가 없습니다.")

    except Exception as e:
        logger.error(f"LLM 학습 중 최상위 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())

    end_time = datetime.now()
    processing_time = (end_time - start_time).total_seconds()
    results_count = len(learned_results)
    data_count = len(unlearned_datas) if 'unlearned_datas' in locals() and unlearned_datas else 0
    logger.info(f"LLM 학습 종료: 원본 데이터 {data_count}건, 학습 결과 {results_count}건 (처리시간: {processing_time:.3f}초)")
    logger.info("=" * 100)

    return learned_results
