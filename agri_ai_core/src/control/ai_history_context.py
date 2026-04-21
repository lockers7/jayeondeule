# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 시계열 히스토리 컨텍스트 모듈 (M1)
# [2026-04-28 신규] LLM 의사결정 시 (a) 최근 2개월 운영 통계,
# (b) 1년 전 동일 시점 셋팅·생육 측정값을 텍스트로 요약하여 제공한다.
#
# 호출 룰 (사용자 강조 사항 — 절대 회손 금지):
#   • 본 모듈은 control_ai_environment(ai_control.py) 에서만 import 한다.
#   • 동급 control 모듈(manual_control / environment_logic) 은 import 하지 않는다.
#   • 본 모듈은 reader / queries / control_common 외 다른 control 모듈을
#     import 하지 않는다 (상호 호출 회피).
#   • DB 호출 실패는 상위에 전파하지 않고 빈 dict 반환 → 기존 LLM 흐름 보존.
# --->
# get_recent_2month_summary: 최근 60일 센서/릴레이/주야간 통계 텍스트
# get_year_ago_baseline:     1년 전 ±7일 셋팅값 + 생육 측정값 텍스트
# format_history_block:      두 컨텍스트를 user prompt 한 블록으로 합성
# clear_cache:               (테스트용) in-memory 캐시 초기화
# ══════════════════════════════════════════════════════════════════════════════
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
import agri_ai_core.src.postgresql.queries as dbQry

logger = setup_logger(__name__)


# 캐시 TTL (초). LLM 호출이 30초 주기 × 재배사 수 만큼 발생하므로 동일 재배사 1시간
# 안에는 SQL 재실행 회피. 운영 모니터링 부담 최소화.
_CACHE_TTL_SEC = 3600

# {(farm_id, house_id, kind): (expires_at, payload)}
_CACHE: Dict[tuple, tuple] = {}


# ────────────────────────────────────────────────────────────────────
# (테스트용) in-memory 캐시 초기화.
# ────────────────────────────────────────────────────────────────────
def clear_cache() -> None:
    _CACHE.clear()


# ────────────────────────────────────────────────────────────────────
# 캐시 조회 — TTL 만료 시 자동 제거.
# ────────────────────────────────────────────────────────────────────
def _cache_get(key: tuple) -> Optional[Any]:
    entry = _CACHE.get(key)
    if not entry:
        return None
    expires_at, payload = entry
    if time.time() >= expires_at:
        _CACHE.pop(key, None)
        return None
    return payload


# ────────────────────────────────────────────────────────────────────
# 캐시 저장 — TTL 만료 시각과 함께 페이로드 보관.
# ────────────────────────────────────────────────────────────────────
def _cache_put(key: tuple, payload: Any) -> None:
    _CACHE[key] = (time.time() + _CACHE_TTL_SEC, payload)


# ────────────────────────────────────────────────────────────────────
# fetch_one 안전 래퍼 — 예외 시 WARNING 로그 후 None.
# ────────────────────────────────────────────────────────────────────
def _safe_fetch_one(query: str, vals: tuple, error_msg: str) -> Optional[dict]:
    try:
        with db_session() as database:
            return database.fetch_one(query=query, vals=vals)
    except Exception as e:
        logger.warning(f"{error_msg}: {e}")
        return None


# ────────────────────────────────────────────────────────────────────
# fetch_all 안전 래퍼 — 예외 시 WARNING 로그 후 [].
# ────────────────────────────────────────────────────────────────────
def _safe_fetch_all(query: str, vals: tuple, error_msg: str) -> list:
    try:
        with db_session() as database:
            return database.fetch_all(query=query, vals=vals, as_dict=True) or []
    except Exception as e:
        logger.warning(f"{error_msg}: {e}")
        return []


# ────────────────────────────────────────────────────────────────────
# 숫자값 포맷팅 — value+unit (digits 자릿수). None 은 "-".
# ────────────────────────────────────────────────────────────────────
def _fmt(value, unit: str = "", digits: int = 1) -> str:
    if value is None:
        return "-"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{f:.{digits}f}{unit}"


# ────────────────────────────────────────────────────────────────────
# 비율(0~1) → 퍼센트 문자열. None 은 "-".
# ────────────────────────────────────────────────────────────────────
def _pct(value) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value)*100:.1f}%"
    except (TypeError, ValueError):
        return "-"


# ══════════════════════════════════════════════════════════════════════════════
# (a) 최근 2개월 운영 통계
# ══════════════════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 최근 60일 센서/릴레이/주야 통계 dict 반환. 캐시 1시간.
# 실패 시 {} (빈 dict) — 호출 측은 falsy 체크로 섹션 생략.
# ────────────────────────────────────────────────────────────────────
def get_recent_2month_summary(farm_id, house_id) -> Dict[str, Any]:
    cache_key = (int(farm_id), int(house_id), 'recent2m')
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info(f"[AI히스토리] 2개월 통계 캐시 hit farm={farm_id} house={house_id}")
        return cached

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=60)
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    logger.info(
        f"[AI히스토리] 2개월 통계 SQL 조회 시작 farm={farm_id} house={house_id} "
        f"window={start_str[:10]}~{end_str[:10]}"
    )

    sensor = _safe_fetch_one(
        dbQry.GET_SENSOR_STATS_IN_RANGE,
        (int(farm_id), int(house_id), start_str, end_str),
        f"[AI히스토리] 2개월 센서통계 조회 실패 farm={farm_id} house={house_id}",
    ) or {}
    relay = _safe_fetch_one(
        dbQry.GET_RELAY_STATS_IN_RANGE,
        (int(farm_id), int(house_id), start_str, end_str),
        f"[AI히스토리] 2개월 릴레이통계 조회 실패 farm={farm_id} house={house_id}",
    ) or {}
    daynight = _safe_fetch_all(
        dbQry.GET_SENSOR_STATS_DAY_NIGHT,
        (int(farm_id), int(house_id), start_str, end_str),
        f"[AI히스토리] 2개월 주야통계 조회 실패 farm={farm_id} house={house_id}",
    )

    payload = {
        'window_start': start_str,
        'window_end':   end_str,
        'sensor':       dict(sensor) if sensor else {},
        'relay':        dict(relay) if relay else {},
        'daynight':     {row.get('period'): dict(row) for row in daynight if row.get('period')},
    }
    _cache_put(cache_key, payload)
    sample = (sensor or {}).get('sample_count') or 0
    logger.info(
        f"[AI히스토리] 2개월 통계 조회 완료 farm={farm_id} house={house_id} "
        f"센서표본={sample} 릴레이={'Y' if relay else 'N'} 주야={len(payload['daynight'])}건"
    )
    return payload


# ────────────────────────────────────────────────────────────────────
# 최근 2개월 통계 dict → user prompt 한 블록 텍스트.
# ────────────────────────────────────────────────────────────────────
def format_recent_2month(summary: Dict[str, Any]) -> str:
    if not summary or not summary.get('sensor'):
        return ""
    s = summary['sensor']
    r = summary.get('relay') or {}
    dn = summary.get('daynight') or {}
    n = s.get('sample_count') or 0
    if not n:
        return ""

    lines = [
        f"[최근 2개월 운영 통계 — 표본 {n}건, {summary['window_start'][:10]}~{summary['window_end'][:10]}]",
        f"내부온도 평균 {_fmt(s.get('avg_indoor_temp'),'℃')} "
        f"(min {_fmt(s.get('min_indoor_temp'),'℃')} / max {_fmt(s.get('max_indoor_temp'),'℃')} / "
        f"std {_fmt(s.get('std_indoor_temp'),'℃')}), "
        f"내부습도 평균 {_fmt(s.get('avg_indoor_humidity'),'%')} "
        f"(min {_fmt(s.get('min_indoor_humidity'),'%')} / max {_fmt(s.get('max_indoor_humidity'),'%')}), "
        f"CO2 평균 {_fmt(s.get('avg_co2'),'ppm',0)} "
        f"(min {_fmt(s.get('min_co2'),'ppm',0)} / max {_fmt(s.get('max_co2'),'ppm',0)}), "
        f"수온 평균 {_fmt(s.get('avg_water_temp'),'℃')}",
    ]

    day = dn.get('day') or {}
    night = dn.get('night') or {}
    if day or night:
        lines.append(
            f"주야 분리: 주간 {_fmt(day.get('avg_indoor_temp'),'℃')}/"
            f"{_fmt(day.get('avg_indoor_humidity'),'%')}/{_fmt(day.get('avg_co2'),'ppm',0)} · "
            f"야간 {_fmt(night.get('avg_indoor_temp'),'℃')}/"
            f"{_fmt(night.get('avg_indoor_humidity'),'%')}/{_fmt(night.get('avg_co2'),'ppm',0)}"
        )

    if r:
        lines.append(
            f"릴레이 가동률: 수온히터 {_pct(r.get('heater_ratio'))} · "
            f"포그생성 {_pct(r.get('misting_ratio'))} · "
            f"흡입팬 {_pct(r.get('intake_fan_ratio'))} · "
            f"배출팬 {_pct(r.get('exhaust_fan_ratio'))} · "
            f"순환밸브 {_pct(r.get('circulation_ratio'))}"
        )
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# (b) 1년 전 ±7일 기준점 — 셋팅 + 생육 측정
# ══════════════════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 1년 전 ±7일 범위의 최적조건 셋팅값 + 생육 측정값을 dict 반환. 캐시 1시간.
# 데이터 부재 시 빈 dict — 호출 측이 섹션 생략.
# ────────────────────────────────────────────────────────────────────
def get_year_ago_baseline(farm_id, house_id) -> Dict[str, Any]:
    cache_key = (int(farm_id), int(house_id), 'year_ago')
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info(f"[AI히스토리] 1년전 기준점 캐시 hit farm={farm_id} house={house_id}")
        return cached

    target_dt = datetime.now() - timedelta(days=365)
    target_str = target_dt.strftime("%Y-%m-%d %H:%M:%S")
    logger.info(
        f"[AI히스토리] 1년전 기준점 SQL 조회 시작 farm={farm_id} house={house_id} "
        f"target_date={target_str[:10]} window=±7d"
    )

    optimal = _safe_fetch_one(
        dbQry.GET_OPTIMAL_AT_DATE,
        (int(farm_id), int(house_id), target_str, target_str, target_str),
        f"[AI히스토리] 1년전 셋팅 조회 실패 farm={farm_id} house={house_id}",
    ) or {}
    growth = _safe_fetch_one(
        dbQry.GET_GROWTH_INPUT_AT_DATE,
        (int(farm_id), int(house_id), target_str, target_str, target_str),
        f"[AI히스토리] 1년전 생육 조회 실패 farm={farm_id} house={house_id}",
    ) or {}

    payload = {
        'target_date': target_str,
        'optimal':     dict(optimal) if optimal else {},
        'growth':      dict(growth) if growth else {},
    }
    _cache_put(cache_key, payload)
    logger.info(
        f"[AI히스토리] 1년전 기준점 조회 완료 farm={farm_id} house={house_id} "
        f"셋팅={'Y' if optimal else 'N'} 생육={'Y' if growth else 'N'}"
    )
    return payload


# ────────────────────────────────────────────────────────────────────
# 1년 전 기준점 dict → user prompt 한 블록 텍스트.
# ────────────────────────────────────────────────────────────────────
def format_year_ago(baseline: Dict[str, Any]) -> str:
    if not baseline:
        return ""
    optimal = baseline.get('optimal') or {}
    growth = baseline.get('growth') or {}
    if not optimal and not growth:
        return ""

    target = baseline.get('target_date', '')[:10]
    parts = [f"[1년 전 동일 시점({target}) 운영 기준점]"]

    if optimal:
        parts.append(
            f"당시 셋팅: 온도 {_fmt(optimal.get('온도최저'),'℃')}~{_fmt(optimal.get('온도최고'),'℃')} "
            f"(적정 {_fmt(optimal.get('온도적정'),'℃')}), "
            f"습도 {_fmt(optimal.get('습도최저'),'%')}~{_fmt(optimal.get('습도최고'),'%')} "
            f"(적정 {_fmt(optimal.get('습도적정'),'%')}), "
            f"CO2 {_fmt(optimal.get('co2최저'),'ppm',0)}~{_fmt(optimal.get('co2최고'),'ppm',0)}, "
            f"수온 {_fmt(optimal.get('수온최저'),'℃')}~{_fmt(optimal.get('수온최고'),'℃')}"
        )

    if growth:
        rec = growth.get('record_datetime', '')[:10]
        bits = [f"기록일 {rec}"]
        if growth.get('crop_lvel'):
            bits.append(f"생육단계 {growth.get('crop_lvel')}")
        if growth.get('growth_status'):
            bits.append(f"상태 {growth.get('growth_status')}")
        if growth.get('total_yield') is not None:
            bits.append(f"총수확 {growth.get('total_yield')}")
        if growth.get('grade_1_yield') is not None:
            bits.append(f"1등급 {growth.get('grade_1_yield')}")
        if growth.get('stem_height') is not None:
            bits.append(f"줄기높이 {growth.get('stem_height')}")
        if growth.get('fruit_count') is not None:
            bits.append(f"자실체수 {growth.get('fruit_count')}")
        if growth.get('pest_type') and growth.get('pest_type') != "없음":
            bits.append(f"병해 {growth.get('pest_type')}")
        if growth.get('growth_memo'):
            bits.append(f"메모 \"{str(growth.get('growth_memo'))[:60]}\"")
        parts.append("당시 생육 입력값: " + " / ".join(bits))

    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# 호출자(ai_control._build_user_prompt)에 합성 텍스트 한 블록으로 제공
# ══════════════════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# ai_control 단일 진입점 — 최근 2개월 + 1년 전 두 섹션을 빈 줄로 합성.
# 완전 비어 있으면 "" 반환 — user prompt 에 빈 섹션 들어가지 않도록.
# ────────────────────────────────────────────────────────────────────
def format_history_block(farm_id, house_id) -> str:
    try:
        recent = get_recent_2month_summary(farm_id, house_id)
        baseline = get_year_ago_baseline(farm_id, house_id)
    except Exception as e:
        logger.warning(f"[AI히스토리] 컨텍스트 합성 실패 farm={farm_id} house={house_id}: {e}")
        return ""

    blocks = [b for b in (format_recent_2month(recent), format_year_ago(baseline)) if b]
    return "\n\n".join(blocks)
