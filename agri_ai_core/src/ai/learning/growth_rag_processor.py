# ═══════════════════════════════════════════════════════════════════
# 생육 기반 인과 관계 RAG: 환경 통계와 생육 데이터를 VectorDB에 저장.
# ═══════════════════════════════════════════════════════════════════
import hashlib
import time
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
from agri_ai_core.src.postgresql import queries as dbQry
from agri_ai_core.src.utils.conversion import safe_float, safe_int

logger = setup_logger(__name__)


# ═════════════════════════════════════════════════════════
# 마지막 RAG 처리 시점 관리
# 마지막 생육 RAG 처리 시점을 조회한다. 없으면 7일 전 반환.
# ═════════════════════════════════════════════════════════
def _get_last_rag_datetime() -> str:
    try:
        with db_session() as database:
            row = database.fetch_one(dbQry.GET_LAST_GROWTH_RAG_DATETIME)
            if row and row.get("status_value"):
                return row["status_value"]
    except Exception as e:
        logger.warning(f"[생육RAG] 마지막 처리 시점 조회 실패: {e}")

    # 기본값: 7일 전
    return (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")


# ═══════════════════════════════════════════════════
# 현재 시간을 마지막 생육 RAG 처리 시점으로 저장한다.
# ═══════════════════════════════════════════════════
def _update_last_rag_datetime() -> None:
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with db_session() as database:
            database.execute_query(
                dbQry.UPSERT_AI_LEARNING_STATUS,
                ("last_growth_rag_datetime", now_str),
            )
        logger.info(f"[생육RAG] 처리 시점 갱신: {now_str}")
    except Exception as e:
        logger.error(f"[생육RAG] 처리 시점 갱신 실패: {e}")


# ═════════════════════════
# 데이터 조회 헬퍼
# 생육RAG DB 조회 공통 래퍼
# ═════════════════════════
def _db_fetch(query, vals=(), *, fetch="all", error_msg="DB 조회", default=None):
    try:
        with db_session() as database:
            if fetch == "one":
                return database.fetch_one(query, vals) or (default if default is not None else {})
            return database.fetch_all(query, vals, as_dict=True) or (default if default is not None else [])
    except Exception as e:
        logger.warning(f"[생육RAG] {error_msg}: {e}")
        return default if default is not None else []


# ═════════════════════════════════
# 활성 농장-재배사 목록을 조회한다.
# ═════════════════════════════════
def _get_active_farm_houses() -> List[Dict[str, Any]]:
    return _db_fetch(dbQry.GET_ACTIVE_FARM_HOUSES_WITH_CROP, error_msg="농장-재배사 목록 조회 실패", default=[])


# ═════════════════════════════════════════════════
# 마지막 RAG 시점 이후 새로운 생육 입력을 조회한다.
# ═════════════════════════════════════════════════
def _get_new_crop_entries(farm_id, house_id, after_dt: str) -> List[Dict[str, Any]]:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return _db_fetch(dbQry.GET_CROPS_IN_RANGE, (farm_id, house_id, after_dt, now_str),
                     error_msg=f"생육 데이터 조회 실패 farm={farm_id} house={house_id}", default=[])


# ═════════════════════════════════
# 시간 구간의 센서 통계를 조회한다.
# ═════════════════════════════════
def _get_sensor_stats(farm_id, house_id, start_dt: str, end_dt: str) -> Dict[str, Any]:
    return _db_fetch(dbQry.GET_SENSOR_STATS_IN_RANGE, (farm_id, house_id, start_dt, end_dt),
                     fetch="one", error_msg="센서 통계 조회 실패", default={})


# ════════════════════════════════════════
# 시간 구간의 릴레이 가동 비율을 조회한다.
# ════════════════════════════════════════
def _get_relay_stats(farm_id, house_id, start_dt: str, end_dt: str) -> Dict[str, Any]:
    return _db_fetch(dbQry.GET_RELAY_STATS_IN_RANGE, (farm_id, house_id, start_dt, end_dt),
                     fetch="one", error_msg="릴레이 통계 조회 실패", default={})


# ═════════════════════════════════
# 주야간 분리 센서 통계를 조회한다.
# ═════════════════════════════════
def _get_day_night_stats(farm_id, house_id, start_dt: str, end_dt: str) -> Dict[str, Dict]:
    result = {"day": {}, "night": {}}
    try:
        with db_session() as database:
            rows = database.fetch_all(
                dbQry.GET_SENSOR_STATS_DAY_NIGHT,
                (farm_id, house_id, start_dt, end_dt),
                as_dict=True,
            ) or []
        for row in rows:
            period = row.get("period", "")
            if period in result:
                result[period] = row
    except Exception as e:
        logger.warning(f"[생육RAG] 주야간 통계 조회 실패: {e}")
    return result


# ═════════════════════════════════════════════════
# 이동평균 시작/끝 샘플을 조회한다 (트렌드 파악용).
# ═════════════════════════════════════════════════
def _get_moving_averages(farm_id, house_id, start_dt: str, end_dt: str) -> List[Dict]:
    return _db_fetch(dbQry.GET_SENSOR_MOVING_AVG, (farm_id, house_id, start_dt, end_dt),
                     error_msg="이동평균 조회 실패", default=[])


# ═════════════════════════════════════
# 당일 생육 입력이 존재하는지 확인한다.
# ═════════════════════════════════════
def _check_today_crops(farm_id, house_id) -> bool:
    try:
        with db_session() as database:
            row = database.fetch_one(
                dbQry.CHECK_TODAY_CROPS_EXISTS,
                (farm_id, house_id),
            )
            return (row.get("cnt", 0) or 0) > 0 if row else False
    except Exception as e:
        logger.warning(f"[생육RAG] 당일 생육 확인 실패: {e}")
        return False


# ═════════════════════════════════
# 컨텍스트 / 문서 / 메타데이터 생성
# ═════════════════════════════════
_SEASON_MAP = {3: "봄", 4: "봄", 5: "봄", 6: "여름", 7: "여름", 8: "여름",
               9: "가을", 10: "가을", 11: "가을", 12: "겨울", 1: "겨울", 2: "겨울"}


def _get_season(month: int) -> str:
    return _SEASON_MAP.get(month, "겨울")


def _sv(value, unit: str = "") -> str:
    """safe_float 값을 문자열로 포맷한다. (센서 값 포맷 헬퍼)"""
    return f"{safe_float(value)}{unit}"


def _format_sensor_stat_block(
    label: str, unit: str, sensor_stats: Dict, day_night: Dict,
    avg_key: str, std_key: str = "", min_key: str = "", max_key: str = "",
    day_night_key: str = "",
) -> str:
    """센서 통계 한 줄을 포맷한다 (평균, 주야간, 표준편차, 범위)."""
    has_more = std_key or (min_key and max_key)
    parts = [f"- {label}: 평균 {_sv(sensor_stats.get(avg_key))}{unit}"]
    if day_night_key:
        day_val = _sv(day_night.get("day", {}).get(day_night_key))
        night_val = _sv(day_night.get("night", {}).get(day_night_key))
        suffix = "," if has_more else ""
        parts.append(f" (주간 {day_val}{unit} / 야간 {night_val}{unit}){suffix}")
    elif has_more:
        parts.append(",")
    if std_key:
        suffix = "," if (min_key and max_key) else ""
        parts.append(f" 표준편차 {_sv(sensor_stats.get(std_key))}{suffix}")
    if min_key and max_key:
        parts.append(f" 범위 {_sv(sensor_stats.get(min_key))}~{_sv(sensor_stats.get(max_key))}")
    return "".join(parts)


def _format_relay_pct(relay_stats: Dict, key: str) -> str:
    """릴레이 가동 비율을 퍼센트 문자열로 포맷한다."""
    return f"{safe_float(relay_stats.get(key)) * 100:.1f}%"


def _format_trend_line(label: str, first: Dict, last: Dict, key: str, unit: str, threshold: float) -> str:
    """이동평균 트렌드 한 줄을 포맷한다."""
    v1 = safe_float(first.get(key))
    v2 = safe_float(last.get(key))
    if abs(v2 - v1) > threshold:
        trend = "상승" if v2 > v1 else "하강"
    else:
        trend = "안정"
    return f"- {label}: {trend} {'추세 ' if label == '온도' else ''}({v1}→{v2}{unit})" if label == "온도" \
        else f"- {label}: {trend} ({v1}~{v2}{unit})"


# ═════════════════════════════════════════════════════
# 생육 컨텍스트를 구성한다 (계절, 시간대, 재배일수 등).
# ═════════════════════════════════════════════════════
def _build_growth_context(crop_entry: Dict, sensor_stats: Dict, day_night: Dict) -> Dict[str, Any]:
    record_dt_str = crop_entry.get("record_datetime", "")
    try:
        record_dt = datetime.strptime(record_dt_str[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        record_dt = datetime.now()

    month = record_dt.month
    season = _get_season(month)
    am_pm = "오전" if record_dt.hour < 12 else "오후"

    # 재배 일수 계산
    days_since_start = 0
    crop_start = crop_entry.get("crop_strt_date")
    if crop_start:
        try:
            if isinstance(crop_start, str):
                start_date = datetime.strptime(crop_start[:10], "%Y-%m-%d").date()
            else:
                start_date = crop_start
            days_since_start = max(0, (record_dt.date() - start_date).days)
        except (ValueError, TypeError):
            pass

    return {
        "season": season,
        "month": month,
        "am_pm": am_pm,
        "hour": record_dt.hour,
        "days_since_start": days_since_start,
        "record_datetime": record_dt_str,
        "crop_level": crop_entry.get("crop_lvel", ""),
        "growth_status": crop_entry.get("growth_status", ""),
        "crop_kind": crop_entry.get("crop_kind", ""),
        "ctrl_type": crop_entry.get("ctrl_type", ""),
        "pest_type": crop_entry.get("pest_type") or "없음",
        "pest_severity": crop_entry.get("pest_severity") or "없음",
    }


# ═══════════════════════════
# RAG 문서 텍스트를 생성한다.
# ═══════════════════════════
def _build_rag_document(
    crop_entry: Dict,
    sensor_stats: Dict,
    relay_stats: Dict,
    day_night: Dict,
    moving_avg: List[Dict],
    context: Dict,
    farm_name: str = "",
    house_name: str = "",
    start_dt: str = "",
    is_daily_guarantee: bool = False,
) -> str:
    lines = []
    record_dt = context.get("record_datetime", "")[:10]

    header = f"[생육 RAG] {record_dt} {farm_name} {house_name}"
    if is_daily_guarantee:
        header += " [일일 보장 RAG - 당일 생육 입력 없음, 정상 간주]"
    lines.append(header)

    lines.append(
        f"계절: {context['season']} | 생육단계: {context.get('crop_level', '-')} | "
        f"재배 {context['days_since_start']}일차 | {context['am_pm']} {context['hour']}시"
    )
    lines.append(
        f"생육상태: {context.get('growth_status', '-')} | "
        f"작물: {context.get('crop_kind', '-')} | 제어: {context.get('ctrl_type', '-')}"
    )

    # 환경 통계
    sample_count = safe_int(sensor_stats.get("sample_count"))
    if sample_count > 0:
        lines.append("")
        lines.append(f"[환경 통계 ({start_dt[:10]} ~ {record_dt}, 센서 {sample_count}건)]")

        lines.append(_format_sensor_stat_block(
            "실내온도", "°C", sensor_stats, day_night,
            "avg_indoor_temp", "std_indoor_temp", "min_indoor_temp", "max_indoor_temp",
            day_night_key="avg_indoor_temp"))
        lines.append(_format_sensor_stat_block(
            "실내습도", "%", sensor_stats, day_night,
            "avg_indoor_humidity", "std_indoor_humidity", "min_indoor_humidity", "max_indoor_humidity",
            day_night_key="avg_indoor_humidity"))
        lines.append(_format_sensor_stat_block(
            "CO2", "ppm", sensor_stats, day_night,
            "avg_co2", "std_co2", "min_co2", "max_co2"))
        lines.append(_format_sensor_stat_block(
            "수온", "°C", sensor_stats, day_night,
            "avg_water_temp", min_key="min_water_temp", max_key="max_water_temp"))
        lines.append(_format_sensor_stat_block(
            "광량", "", sensor_stats, day_night,
            "avg_light_level", day_night_key="avg_light_level"))

    # 릴레이 가동 비율
    relay_sample = safe_int(relay_stats.get("sample_count"))
    if relay_sample > 0:
        lines.append("")
        lines.append("[릴레이 가동 비율]")

        _rp = lambda k: _format_relay_pct(relay_stats, k)
        lines.append(
            f"- 물가열기: {_rp('heater_ratio')} | "
            f"분사펌프: {_rp('misting_ratio')} | "
            f"배기팬: {_rp('exhaust_fan_ratio')} | "
            f"조명: {_rp('lighting_ratio')} | "
            f"관수: {_rp('irrigation_ratio')}"
        )
        lines.append(
            f"- 열풍기: {_rp('indoor_heater_ratio')} | "
            f"순환댐퍼: {_rp('circulation_ratio')} | "
            f"흡기댐퍼: {_rp('intake_valve_ratio')} | "
            f"배기댐퍼: {_rp('exhaust_valve_ratio')}"
        )

    # 이동평균 트렌드
    if len(moving_avg) >= 2:
        lines.append("")
        lines.append("[이동평균 트렌드 (6시간 윈도우)]")
        first, last = moving_avg[0], moving_avg[-1]
        lines.append(_format_trend_line("온도", first, last, "ma_indoor_temp", "°C", 1.0))
        lines.append(_format_trend_line("습도", first, last, "ma_indoor_humidity", "%", 3.0))

    # 생육 결과
    if not is_daily_guarantee:
        lines.append("")
        lines.append("[생육 결과]")

        total_yield = safe_float(crop_entry.get("total_yield"))
        g1 = safe_float(crop_entry.get("grade_1_yield"))
        g2 = safe_float(crop_entry.get("grade_2_yield"))
        g3 = safe_float(crop_entry.get("grade_3_yield"))
        g1_ratio = (g1 / total_yield * 100) if total_yield > 0 else 0

        if total_yield > 0:
            lines.append(
                f"- 총 수확량: {total_yield}kg | 1등급: {g1}kg({g1_ratio:.1f}%)"
                f" | 2등급: {g2}kg | 3등급: {g3}kg"
            )

        # 생육 세분화 정보
        obs_parts = []
        if crop_entry.get("leaf_color"):
            obs_parts.append(f"잎 색상 {crop_entry['leaf_color']}")
        if crop_entry.get("leaf_count"):
            obs_parts.append(f"잎 {crop_entry['leaf_count']}개")
        if crop_entry.get("stem_height"):
            obs_parts.append(f"줄기 높이 {crop_entry['stem_height']}cm")
        if crop_entry.get("fruit_count"):
            obs_parts.append(f"열매 {crop_entry['fruit_count']}개")
        pest = crop_entry.get("pest_type") or "없음"
        obs_parts.append(f"병해충 {pest}")
        if obs_parts:
            lines.append(f"- 관찰: {', '.join(obs_parts)}")

        alert = crop_entry.get("alert", "")
        growth_memo = crop_entry.get("growth_memo", "")
        memo = growth_memo or alert
        if memo:
            lines.append(f"- 비고: {memo}")

    return "\n".join(lines)


# ═══════════════════════════════
# VectorDB 메타데이터를 구성한다.
# ═══════════════════════════════
def _build_rag_metadata(
    farm_id,
    house_id,
    crop_entry: Dict,
    context: Dict,
    sensor_stats: Dict,
    is_daily_guarantee: bool = False,
) -> Dict[str, Any]:
    total_yield = safe_float(crop_entry.get("total_yield"))
    g1 = safe_float(crop_entry.get("grade_1_yield"))
    g1_ratio = (g1 / total_yield) if total_yield > 0 else 0.0

    # 이상 상태 판정
    anomaly_flag = "normal"
    pest = context.get("pest_type", "없음")
    if pest and pest != "없음":
        anomaly_flag = "pest_detected"

    # 재배 성과 라벨
    quality_label = ""
    if crop_entry.get("crop_end_date"):
        if g1_ratio > 0.6:
            quality_label = "우수"
        elif g1_ratio > 0.3:
            quality_label = "보통"
        else:
            quality_label = "개선필요"

    return {
        "farm_id": str(farm_id),
        "house_id": str(house_id),
        "data_type": "growth_rag",
        "record_datetime": context.get("record_datetime", ""),
        "season": context.get("season", ""),
        "month": context.get("month", 0),
        "crop_level": context.get("crop_level", ""),
        "ctrl_type": context.get("ctrl_type", ""),
        "days_since_start": context.get("days_since_start", 0),
        "crop_kind": context.get("crop_kind", ""),
        "growth_status": context.get("growth_status", ""),
        "pest_type": pest,
        "anomaly_flag": anomaly_flag,
        "quality_label": quality_label,
        "sensor_sample_count": safe_int(sensor_stats.get("sample_count")),
        "avg_indoor_temp": safe_float(sensor_stats.get("avg_indoor_temp")),
        "avg_indoor_humidity": safe_float(sensor_stats.get("avg_indoor_humidity")),
        "avg_co2": safe_float(sensor_stats.get("avg_co2")),
        "grade_1_ratio": round(g1_ratio, 3),
        "total_yield": total_yield,
        "is_daily_guarantee": is_daily_guarantee,
    }


# ════════════════════════════════════════════
# VectorDB 저장
# RAG 문서를 farm_knowledge 컬렉션에 저장한다.
# ════════════════════════════════════════════
def _store_growth_rag(document: str, metadata: Dict[str, Any]) -> bool:
    try:
        from agri_ai_core.src.ai.rag.embedder import embed_text
        from agri_ai_core.src.chroma.collections import farm_knowledge_collection
        from agri_ai_core.src.chroma.operations import upsert_documents_with_embedding

        collection_name = farm_knowledge_collection()
        if not collection_name:
            logger.warning("[생육RAG] farm_knowledge 컬렉션이 설정되지 않았습니다.")
            return False

        embedding = embed_text(document)
        if not embedding:
            logger.warning("[생육RAG] 임베딩 생성 실패")
            return False

        # 고유 ID 생성
        id_source = (
            f"growth_rag_{metadata.get('farm_id')}_{metadata.get('house_id')}"
            f"_{metadata.get('record_datetime', '')}"
        )
        doc_id = f"grag_{hashlib.md5(id_source.encode()).hexdigest()[:16]}"

        upsert_documents_with_embedding(
            collection_name=collection_name,
            docs=[{
                "doc_id": doc_id,
                "text": document,
                "metadata": metadata,
                "embedding": embedding,
            }],
        )
        logger.info(
            f"[생육RAG] VectorDB 저장 완료: {doc_id} "
            f"farm={metadata.get('farm_id')} season={metadata.get('season')} "
            f"crop_level={metadata.get('crop_level')}"
        )
        return True

    except Exception as e:
        logger.error(f"[생육RAG] VectorDB 저장 실패: {e}")
        logger.error(traceback.format_exc())
        return False


# ══════════════════════════════════════════════════
# 00:00 일일 보장 RAG
# 당일 생육 입력이 없을 때 정상 간주 RAG를 생성한다.
# ══════════════════════════════════════════════════
def _ensure_daily_rag(farm_id, house_id, last_rag_dt: str, farm_name: str = "", house_name: str = "") -> bool:
    if _check_today_crops(farm_id, house_id):
        return False  # 당일 입력이 있으면 불필요

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # 최근 24시간 센서/릴레이 통계
    start_dt = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    sensor_stats = _get_sensor_stats(farm_id, house_id, start_dt, now_str)
    relay_stats = _get_relay_stats(farm_id, house_id, start_dt, now_str)
    day_night = _get_day_night_stats(farm_id, house_id, start_dt, now_str)
    moving_avg = _get_moving_averages(farm_id, house_id, start_dt, now_str)

    if not sensor_stats or safe_int(sensor_stats.get("sample_count")) == 0:
        logger.debug(f"[생육RAG] 센서 데이터 없음, 일일 보장 RAG 스킵 farm={farm_id} house={house_id}")
        return False

    # 가상 생육 entry (양호 간주)
    dummy_crop = {
        "record_datetime": now_str,
        "crop_strt_date": None,
        "crop_lvel": "",
        "growth_status": "양호(추정)",
        "crop_kind": "",
        "ctrl_type": "",
        "pest_type": "없음",
        "pest_severity": "없음",
        "total_yield": 0,
        "grade_1_yield": 0,
        "grade_2_yield": 0,
        "grade_3_yield": 0,
    }

    context = _build_growth_context(dummy_crop, sensor_stats, day_night)
    document = _build_rag_document(
        dummy_crop, sensor_stats, relay_stats, day_night, moving_avg, context,
        farm_name=farm_name, house_name=house_name,
        start_dt=start_dt, is_daily_guarantee=True,
    )
    metadata = _build_rag_metadata(
        farm_id, house_id, dummy_crop, context, sensor_stats,
        is_daily_guarantee=True,
    )

    return _store_growth_rag(document, metadata)


# ═══════════════════════════════════
# 메인 진입점
# 생육 기반 인과 관계 RAG를 실행한다.
# ═══════════════════════════════════
def run_growth_rag(is_midnight: bool = False) -> Dict[str, Any]:
    t_start = time.time()
    logger.info("=" * 80)
    logger.info(f"[생육RAG] 시작 (is_midnight={is_midnight})")

    result = {
        "success": True,
        "rag_count": 0,
        "daily_guarantee_count": 0,
        "farm_houses_processed": 0,
        "errors": [],
    }

    try:
        last_rag_dt = _get_last_rag_datetime()
        logger.info(f"[생육RAG] 마지막 처리 시점: {last_rag_dt}")

        farm_houses = _get_active_farm_houses()
        if not farm_houses:
            logger.info("[생육RAG] 활성 농장-재배사가 없습니다.")
            return result

        logger.info(f"[생육RAG] 대상 농장-재배사: {len(farm_houses)}개")

        for fh in farm_houses:
            farm_id = fh.get("farm_id")
            house_id = fh.get("hous_id")
            farm_name = fh.get("farm_name", "")
            house_name = fh.get("hous_name", "")

            try:
                new_crops = _get_new_crop_entries(farm_id, house_id, last_rag_dt)

                if new_crops:
                    logger.info(
                        f"[생육RAG] farm={farm_id} house={house_id}: "
                        f"새 생육 {len(new_crops)}건 발견"
                    )

                    # 이전 시점 추적 (순차적 구간 설정)
                    prev_dt = last_rag_dt

                    for crop_entry in new_crops:
                        curr_dt = crop_entry.get("record_datetime", "")
                        if not curr_dt:
                            continue

                        _t_crop = time.time()

                        # 센서/릴레이 통계 조회 (이전 시점 ~ 현재 생육 입력 시점)
                        _t_stat = time.time()
                        sensor_stats = _get_sensor_stats(farm_id, house_id, prev_dt, curr_dt)
                        relay_stats = _get_relay_stats(farm_id, house_id, prev_dt, curr_dt)
                        day_night = _get_day_night_stats(farm_id, house_id, prev_dt, curr_dt)
                        moving_avg = _get_moving_averages(farm_id, house_id, prev_dt, curr_dt)
                        _stat_ms = (time.time() - _t_stat) * 1000

                        _t_build = time.time()
                        context = _build_growth_context(crop_entry, sensor_stats, day_night)
                        document = _build_rag_document(
                            crop_entry, sensor_stats, relay_stats, day_night, moving_avg, context,
                            farm_name=farm_name, house_name=house_name, start_dt=prev_dt,
                        )
                        metadata = _build_rag_metadata(
                            farm_id, house_id, crop_entry, context, sensor_stats,
                        )
                        _build_ms = (time.time() - _t_build) * 1000

                        _t_store = time.time()
                        if _store_growth_rag(document, metadata):
                            result["rag_count"] += 1
                        _store_ms = (time.time() - _t_store) * 1000

                        _crop_ms = (time.time() - _t_crop) * 1000
                        logger.debug(
                            f"[PERF:농장학습] 생육RAG-항목처리={_crop_ms:.0f}ms "
                            f"(통계조회={_stat_ms:.0f}ms, 문서생성={_build_ms:.0f}ms, "
                            f"저장={_store_ms:.0f}ms) farm={farm_id} house={house_id}"
                        )

                        prev_dt = curr_dt

                elif is_midnight:
                    # 00:00 실행이고 당일 생육 미입력 → 일일 보장 RAG
                    if _ensure_daily_rag(farm_id, house_id, last_rag_dt, farm_name, house_name):
                        result["daily_guarantee_count"] += 1

                result["farm_houses_processed"] += 1

            except Exception as e:
                err_msg = f"farm={farm_id} house={house_id}: {e}"
                logger.error(f"[생육RAG] 처리 오류 {err_msg}")
                logger.error(traceback.format_exc())
                result["errors"].append(err_msg)

        # 처리 시점 갱신
        _update_last_rag_datetime()

    except Exception as e:
        result["success"] = False
        result["errors"].append(str(e))
        logger.error(f"[생육RAG] 최상위 오류: {e}")
        logger.error(traceback.format_exc())

    elapsed = time.time() - t_start
    logger.info(
        f"[생육RAG] 완료 ({elapsed:.1f}s) "
        f"RAG={result['rag_count']}건 "
        f"일일보장={result['daily_guarantee_count']}건 "
        f"처리={result['farm_houses_processed']}개 "
        f"오류={len(result['errors'])}건"
    )
    logger.debug(
        f"[PERF:농장학습] 생육RAG-전체={elapsed:.1f}s, "
        f"농장재배사={result['farm_houses_processed']}개, RAG={result['rag_count']}건"
    )
    logger.info("=" * 80)

    return result
