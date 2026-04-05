# ══════════════════════════════════════════════════
# 모델 학습 관리: 농장 데이터 분석 및 ChromaDB 저장.
# ══════════════════════════════════════════════════
import json
import traceback
import pandas as pd
from datetime import datetime

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.chroma.collections import farm_knowledge_collection
from agri_ai_core.src.utils.date_utils import parse_datetime
from agri_ai_core.src.utils.conversion import convert_sensor_relay_data
from agri_ai_core.src.chroma.client import heartbeat
from agri_ai_core.src.chroma.operations import (
    get_documents,
    upsert_collection_data,
)
from agri_ai_core.src.chroma.utils import generate_doc_id
from agri_ai_core.src.chroma.loader import (
    get_unlearned_data,
    update_learned_last_status
)
from agri_ai_core.src.ai.learning.data_analyzer import (
    analyze_farm_optimal_conditions,
    analyze_farm_time_patterns,
    update_learning_timestamp
)

logger = setup_logger(__name__)


# ═══════════════════════
# ChromaDB 연결 상태 확인
# ═══════════════════════
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


# ═════════════════════════
# 농장별 시간대 데이터 처리
# ═════════════════════════
def process_farm_hour_data(farm_id, hour, data, hour_timestamp=None):
    if not farm_id or hour is None:
        logger.warning("농장코드 또는 시간대가 유효하지 않습니다.")
        return None

    start_time = datetime.now()

    if not data["units_data"] and not data["crops_data"]:
        logger.debug(f"농장 {farm_id}의 시간대 {hour}시 처리할 데이터가 없습니다.")
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
                except Exception:
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


# ════════════════════════
# LLM 모델 업데이트 (학습)
# ════════════════════════
def update_ollama_model(after_date=None, top_cnt=0):
    start_time = datetime.now()
    current_hour = start_time.hour

    logger.debug("=" * 100)
    logger.debug(f"LLM 학습 시작 - 시간대: {current_hour}시, 시작일자: {after_date}, 건수: {top_cnt})")

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
                logger.debug(f"after_date 1 필터링 완료: {before}건 → {len(unlearned_datas)}건")
            except Exception as e:
                logger.warning(f"after_date 1 필터링 중 오류: {e}")

        if not unlearned_datas:
            logger.debug("학습할 신규 데이터가 없습니다.")
            end_time = datetime.now()
            processing_time = (end_time - start_time).total_seconds()
            logger.debug(f"LLM 학습 종료: 처리할 데이터 없음 (처리시간: {processing_time:.3f}초)")
            logger.debug("=" * 100)
            return []

        data_count = len(unlearned_datas)
        logger.debug(f"신규 데이터 {data_count}건 학습 시작")

        # 통계 및 최적 환경 데이터 처리
        stats_start = datetime.now()
        try:
            update_learning_timestamp()
            stats_end = datetime.now()
            stats_time = (stats_end - stats_start).total_seconds()
            logger.debug(f"통계 및 최적 환경 데이터 처리 완료 (처리시간: {stats_time:.3f}초)")
        except Exception as e:
            logger.error(f"update_ollama_model 통계 및 최적 환경 데이터 처리 중 오류: {e}")
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
                        **{f"crop_grde_qtty_{i}": data.get(f"grade_{i}_yield") for i in range(2, 6)},
                        **{f"crop_grde_amut_{i}": data.get(f"grade_{i}_price") for i in range(1, 6)},
                        "rmks": data.get("alert"),
                        "grade_1_ratio": grade_1_ratio
                    }

                    farm_hour_data[farm_hour_key]["crops_data"].append(crop_entry)

                processed_count += 1
        except Exception as e:
            logger.error(f"데이터 변환 중 오류: {e}")
            logger.error(traceback.format_exc())

        transform_processed_count = processed_count
        farm_hours_count = len(farm_hour_data)
        units_count = sum(len(data.get("units_data", [])) for data in farm_hour_data.values())
        crops_count = sum(len(data.get("crops_data", [])) for data in farm_hour_data.values())

        logger.debug(f"데이터 변환 완료: {transform_processed_count}건 처리, {skipped_count}건 건너뜀")
        logger.debug(f"농장-시간대 조합: {farm_hours_count}개, 장치 데이터: {units_count}건, 작물 데이터: {crops_count}건")

        learned_results = []
        process_success_count = 0
        process_error_count = 0

        for farm_hour_key, data in farm_hour_data.items():
            try:
                farm_id = data.get("farm_id")
                hour = data.get("hour")
                house_id = data.get("house_id", "0")

                # crops_data / units_data 없으면 스킵 (더미 데이터 생성 대신 건너뜀)
                if not data.get("crops_data"):
                    logger.debug(f"농장 {farm_id}, 시간대 {hour} crops_data 없음 → 스킵")
                    continue

                if not data.get("units_data"):
                    logger.debug(f"농장 {farm_id}, 시간대 {hour} units_data 없음 → 스킵")
                    continue

                # 학습 실행
                farm_learned_data = process_farm_hour_data(
                    farm_id, hour, data, data.get("hour_timestamp")
                )

                if farm_learned_data:
                    learned_results.append(farm_learned_data)
                    process_success_count += 1

            except Exception as e:
                logger.error(f"농장 {farm_id}, 시간대 {hour}시 처리 중 오류: {e}")
                logger.error(traceback.format_exc())
                process_error_count += 1

        logger.debug(f"농장-시간대 조합 처리 완료: {process_success_count}개 성공, {process_error_count}개 실패")

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
                            collection=farm_knowledge_collection(),
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
                        logger.error(traceback.format_exc())

                if success_count > 0:
                    update_learned_last_status()

                    try:
                        learned_items = get_documents(collection_name=farm_knowledge_collection())
                        learned_count = len(learned_items.get("ids", [])) if "error" not in learned_items else 0
                        logger.debug(f"학습 완료: 총 {len(unlearned_datas)}건 처리, farm_knowledge에 {success_count}건 저장됨 (총 {learned_count}건)")
                    except Exception as e:
                        logger.debug(f"학습 완료: 저장 건수 {success_count}건 (컬렉션 조회 실패: {e})")
                else:
                    logger.error(f"저장 실패 - 총 {len(learned_results)}건 중 {success_count}건 성공")

            except Exception as e:
                logger.error(f"학습 결과 저장 중 오류: {e}")
                logger.error(traceback.format_exc())
        else:
            logger.debug("학습 결과가 없습니다.")

    except Exception as e:
        logger.error(f"LLM 학습 중 최상위 오류: {e}")

        logger.error(traceback.format_exc())

    end_time = datetime.now()
    processing_time = (end_time - start_time).total_seconds()
    results_count = len(learned_results)
    data_count = len(unlearned_datas) if 'unlearned_datas' in locals() and unlearned_datas else 0
    logger.debug(f"LLM 학습 종료: 원본 데이터 {data_count}건, 학습 결과 {results_count}건 (처리시간: {processing_time:.3f}초)")
    logger.debug(
        f"[PERF:대화학습] 모델학습-전체={processing_time:.1f}s, "
        f"원본={data_count}건, 학습결과={results_count}건"
    )
    logger.debug("=" * 100)

    return learned_results
