# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 데이터 처리 파이프라인 모듈
# 원시 데이터를 수집, 변환, 정제하는 ETL 프로세스를 구현하며,
# 다양한 소스의 데이터를 표준 형식으로 가공합니다.
# --->
# safe_float: 안전한 float 변환
# process_unit_data: 장치 데이터를 처리하여 벡터 DB에 저장
# process_crop_data: 생육 데이터를 처리하여 벡터 DB에 저장
# align_to_3min: 기능 설명 필요
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import json
import traceback
import pandas as pd
from datetime import timedelta
from collections import defaultdict, Counter

from agri_ai_core.src.logs import setup_logger
from agri_ai_core.src.chroma.collections import source_collection
from agri_ai_core.config import (
    SENSOR_MAPPING, RELAY_MAPPING, RELAY_FIELD_MAPPING
)
from agri_ai_core.src.utils import clean_sensor_value, parse_boolean
from agri_ai_core.src.chroma.operations import (
    generate_doc_id,
    upsert_collection_data
)

logger = setup_logger(__name__)


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
# 장치 데이터 처리
# --->
# 장치 데이터를 처리하여 벡터 DB에 저장
# Args:
# item: 농장/재배사 데이터 딕셔너리
# Returns:
# tuple: (성공 건수, 실패 건수)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def process_unit_data(item):
    success_count = 0
    failure_count = 0

    if "units" not in item or not item["units"]:
        logger.info("처리할 장치 데이터가 없습니다.")
        return 0, 0

    try:
        df = pd.DataFrame(item["units"])
        if df.empty or "기록일시" not in df.columns:
            logger.info("유효한 기록일시가 없어 집계 불가.")
            return 0, 0

        df["기록일시"] = pd.to_datetime(df["기록일시"])

        def align_to_3min(dt):
            m = dt.minute
            slot = ((m - 1) // 3 + 1) * 3 if m != 0 else 0
            if slot > 57:
                dt += timedelta(hours=1)
                slot = 0
            return dt.replace(minute=slot, second=0, microsecond=0)

        df["집계시간"] = df["기록일시"].apply(align_to_3min)
        grouped = df.groupby("집계시간")
        total_count = len(df)
        cumulative_cnt = 0

        for agg_time, group in grouped:
            unit_cnt = len(group)
            cumulative_cnt += unit_cnt

            logger.info(f"장치 데이터 집계 처리: {cumulative_cnt} / {total_count}건 -> {agg_time}")

            try:
                sensor_sums = defaultdict(float)
                sensor_counts = defaultdict(int)

                for _, unit in group.iterrows():
                    for kr_key, en_key in SENSOR_MAPPING.items():
                        try:
                            val = clean_sensor_value(unit.get(kr_key, "0"))
                            if val is not None:
                                sensor_sums[en_key] += float(val)
                                sensor_counts[en_key] += 1
                        except:
                            continue

                sensor_averages = {
                    k: round(sensor_sums[k] / sensor_counts[k], 2) if sensor_counts[k] > 0 else 0.0
                    for k in SENSOR_MAPPING.values()
                }

                relay_majority = {}
                for kr_key, en_key in RELAY_MAPPING.items():
                    flags = group[kr_key].map(parse_boolean)
                    flag_counts = Counter(flags)
                    relay_majority[en_key] = flag_counts.most_common(1)[0][0] if flag_counts else False

                first = group.iloc[0]
                units_meta_data = {
                    "farm_id": first.get("농장코드"),
                    "farm_name": first.get("농장명"),
                    "house_id": first.get("재배사코드"),
                    "house_name": first.get("재배사명"),
                    "data_kind": first.get("장치데이터"),
                    "record_datetime": str(agg_time),
                    "is_learned_flag": False
                }

                units_meta_data.update(sensor_averages)
                units_meta_data.update(relay_majority)

                units_text_data = (
                    f"농장코드: {units_meta_data['farm_id']}, "
                    f"농장명: {units_meta_data['farm_name']}, "
                    f"재배사코드: {units_meta_data['house_id']}, "
                    f"재배사명: {units_meta_data['house_name']}, "
                    f"장치데이터: {units_meta_data['data_kind']}, "
                    f"기록일시: {units_meta_data['record_datetime']}, "
                )
                units_text_data += ", ".join([f"{k}: {v}" for k, v in sensor_averages.items()])
                units_text_data += ", "
                units_text_data += ", ".join([
                    f"{RELAY_FIELD_MAPPING[k][0]}: {'작동중(True)' if units_meta_data[k] else '미작동(False)'}"
                    for k in relay_majority
                ])
                units_text_data += f", 학습여부: {units_meta_data['is_learned_flag']} "

                processed_meta = {
                    k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v or ""))
                    for k, v in units_meta_data.items()
                }

                doc_id = generate_doc_id(
                    kind="units",
                    farm_id=units_meta_data["farm_id"],
                    house_id=units_meta_data["house_id"],
                    timestamp=agg_time
                )
                status = upsert_collection_data(
                    calledby="process_unit_data",
                    collection=source_collection(),
                    doc_id=doc_id,
                    document=units_text_data,
                    metadata=processed_meta
                )
                if status in ["added", "updated"]:
                    success_count += 1
                else:
                    logger.warning(f"장치 데이터 저장 실패: {doc_id}")
                    failure_count += 1

            except Exception as e:
                logger.error(f"집계 데이터 처리 중 오류 발생: {e}")
                logger.error(traceback.format_exc())
                failure_count += 1

    except Exception as e:
        logger.error(f"전체 데이터 처리 실패: {e}")
        logger.error(traceback.format_exc())
        return 0, 1

    return success_count, failure_count


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 생육 데이터 처리
# --->
# 생육 데이터를 처리하여 벡터 DB에 저장
# Args:
# item: 농장/재배사 데이터 딕셔너리
# Returns:
# tuple: (성공 건수, 실패 건수)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def process_crop_data(item):
    success_count = 0
    failure_count = 0
    total_crops = len(item["crops"])
    cumulative_cnt = 0

    for crop in item["crops"]:
        cumulative_cnt += 1
        logger.info(f"생육 데이터 처리: {cumulative_cnt}/{total_crops}건 -> {crop.get('기록일시')}")

        try:
            crops_meta_data = {
                "farm_id": crop.get("농장코드"),
                "farm_name": crop.get("농장명"),
                "house_id": crop.get("재배사코드"),
                "house_name": crop.get("재배사명"),
                "data_kind": crop.get("장치데이터"),
                "record_datetime": str(crop.get("기록일시")),
                "crop_strt_date": crop.get("작물시작일자", ""),
                "crop_end_date": crop.get("작물종료일자", ""),
                "growth_status": crop.get("생육상태", ""),
                "total_yield": safe_float(crop.get("총수확량", "0")),
                "grade_1_yield": safe_float(crop.get("1등급수확량", "0")),
                "grade_2_yield": safe_float(crop.get("2등급수확량", "0")),
                "grade_3_yield": safe_float(crop.get("3등급수확량", "0")),
                "grade_4_yield": safe_float(crop.get("4등급수확량", "0")),
                "grade_5_yield": safe_float(crop.get("5등급수확량", "0")),
                "grade_1_price": safe_float(crop.get("1등급가격", "0")),
                "grade_2_price": safe_float(crop.get("2등급가격", "0")),
                "grade_3_price": safe_float(crop.get("3등급가격", "0")),
                "grade_4_price": safe_float(crop.get("4등급가격", "0")),
                "grade_5_price": safe_float(crop.get("5등급가격", "0")),
                "alert": crop.get("알림", ""),
                "is_learned_flag": False,
            }

            for i in range(1, 6):
                crops_meta_data[f"grade_{i}_revenue"] = (
                    crops_meta_data.get(f"grade_{i}_yield", 0) * crops_meta_data.get(f"grade_{i}_price", 0)
                )

            crops_meta_data["total_revenue"] = sum(
                crops_meta_data[f"grade_{i}_revenue"] for i in range(1, 6)
            )

            total_yield = crops_meta_data["total_yield"]
            crops_meta_data["grade_1_ratio"] = (
                crops_meta_data["grade_1_yield"] / total_yield if total_yield > 0 else 0
            )

            crops_text_data = (
                f"농장코드: {crops_meta_data['farm_id']}, "
                f"농장명: {crops_meta_data['farm_name']}, "
                f"재배사코드: {crops_meta_data['house_id']}, "
                f"재배사명: {crops_meta_data['house_name']}, "
                f"생육데이터: {crops_meta_data['data_kind']}, "
                f"기록일시: {crops_meta_data['record_datetime']}, "
                f"재배시작일: {crops_meta_data['crop_strt_date']}, "
                f"재배종료일: {crops_meta_data['crop_end_date']}, "
                f"생육상태: {crops_meta_data['growth_status']}, "
                f"총수확량: {crops_meta_data['total_yield']}, "
                f"등급1수확량: {crops_meta_data['grade_1_yield']}, "
                f"등급2수확량: {crops_meta_data['grade_2_yield']}, "
                f"등급3수확량: {crops_meta_data['grade_3_yield']}, "
                f"등급4수확량: {crops_meta_data['grade_4_yield']}, "
                f"등급5수확량: {crops_meta_data['grade_5_yield']}, "
                f"등급1판매가격: {crops_meta_data['grade_1_price']}, "
                f"등급2판매가격: {crops_meta_data['grade_2_price']}, "
                f"등급3판매가격: {crops_meta_data['grade_3_price']}, "
                f"등급4판매가격: {crops_meta_data['grade_4_price']}, "
                f"등급5판매가격: {crops_meta_data['grade_5_price']}, "
                f"등급1수익: {crops_meta_data['grade_1_revenue']}, "
                f"등급2수익: {crops_meta_data['grade_2_revenue']}, "
                f"등급3수익: {crops_meta_data['grade_3_revenue']}, "
                f"등급4수익: {crops_meta_data['grade_4_revenue']}, "
                f"등급5수익: {crops_meta_data['grade_5_revenue']}, "
                f"총수익: {crops_meta_data['total_revenue']}, "
                f"등급1비율: {crops_meta_data['grade_1_ratio']:.2%}, "
                f"생육시기타사항: {crops_meta_data['alert']}, "
                f"학습여부: {crops_meta_data['is_learned_flag']} "
            )

            doc_id = generate_doc_id(
                kind="crops",
                farm_id=crop.get("농장코드"),
                house_id=crop.get("재배사코드"),
                timestamp=crop.get("기록일시")
            )
            status = upsert_collection_data(
                calledby="process_crop_data",
                collection=source_collection(),
                doc_id=doc_id,
                document=crops_text_data,
                metadata=crops_meta_data
            )
            if status == "added" or status == "updated":
                success_count += 1
            else:
                logger.warning(f"생육 데이터 저장 실패: {doc_id}")
                failure_count += 1

        except Exception as e:
            import traceback
            logger.info(f"생육 데이터 처리 중 오류 발생: {e}")
            logger.info(traceback.format_exc())
            failure_count += 1

    return success_count, failure_count
