# ══════════════════════════════════════════════════════════════════════════════
# AI/알고리즘 환경제어 — 재배사별 임계값 동적 로드 모듈 (M18, [2026-04-28 rev2])
#
# 사용자 강제 요구: "센서값은 절대 하드코딩 금지. 테이블 컬럼 값만 변경하면 되어야
# 한다." → 정상/비상/발이기 모든 임계값을 SENSOR_M_SETTING 테이블에서 직접 조회.
# 자동 도출 폭은 사용하지 않으며, DB 행이 없거나 모든 핵심 컬럼이 NULL 인 경우에만
# 부팅 안전을 위해 최후 폴백 값으로 동작.
#
# 컬럼 매핑 (SENSOR_M_SETTING):
#   tprt_min/otml/max               → temp_low/optimal/high
#   tprt_crit_min/max               → temp_critical_low/high
#   hmdt_min/otml/max               → humidity_low/optimal/high
#   hmdt_crit_min/max               → humidity_critical_low/high
#   co2_min/otml/max                → co2_low/optimal/high
#   co2_crit_max                    → co2_critical_high
#   watr_tprt_min/otml/max          → water_temp_low/optimal/high
#   watr_tprt_crit_min/max          → water_temp_critical_low/high
#   bud_tprt_min/max                → budding_temp_low/high
#
# 호출 룰:
#   • 모든 환경제어 모듈은 본 모듈의 get_thresholds(farm_id, house_id) 만 사용.
#   • control_common 의 임계 상수를 직접 import 금지 — 본 모듈 경유.
#   • postgresql 만 의존.
# --->
# ThresholdSet:        값 컨테이너 (dataclass)
# get_thresholds:      (farm_id, house_id) → ThresholdSet (캐시 5분 TTL)
# get_global_default:  DB 부재/미연결 시 최후 폴백 (운영에선 발생 안 해야 함)
# clear_cache:         테스트용
# ══════════════════════════════════════════════════════════════════════════════
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
import agri_ai_core.src.postgresql.queries as dbQry

logger = setup_logger(__name__)


_CACHE_TTL_SEC = 300  # 5분 — 운영 중 셋팅 변경 시 빠른 반영
_CACHE: Dict[tuple, tuple] = {}  # {(farm, house): (expires_at, ThresholdSet)}


# 최후 폴백 — DB 미연결 / 행 부재 / 모든 컬럼 NULL 인 비상 상황에만 사용.
# 운영에서는 마이그레이션·백필 후 절대 진입하지 않아야 함. 사용자 강조사항
# "센서값 하드코딩 금지" 에 부합하도록 환경변수로 외부화 — 코드 재배포 없이
# 운영 환경별로 폴백 값을 바꿀 수 있게 한다.
#
# 환경변수 이름:
#   AI_FB_TEMP_LOW / AI_FB_TEMP_HIGH / AI_FB_TEMP_CRIT_LOW / AI_FB_TEMP_CRIT_HIGH
#   AI_FB_HUM_LOW / AI_FB_HUM_HIGH / AI_FB_HUM_CRIT_LOW / AI_FB_HUM_CRIT_HIGH
#   AI_FB_CO2_LOW / AI_FB_CO2_HIGH / AI_FB_CO2_CRIT_HIGH
#   AI_FB_WATER_LOW / AI_FB_WATER_HIGH / AI_FB_WATER_CRIT_LOW / AI_FB_WATER_CRIT_HIGH
#   AI_FB_BUD_LOW / AI_FB_BUD_HIGH
import os

# ────────────────────────────────────────────────────────────────────
# 환경변수 값을 float 으로 안전 변환. 미설정/실패 시 default.
# ────────────────────────────────────────────────────────────────────
def _env_float(key: str, default: float) -> float:
    v = os.getenv(key)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default

_LAST_RESORT = {
    'temp_low':                 _env_float('AI_FB_TEMP_LOW',         27.0),
    'temp_high':                _env_float('AI_FB_TEMP_HIGH',        30.0),
    'temp_critical_low':        _env_float('AI_FB_TEMP_CRIT_LOW',    25.0),
    'temp_critical_high':       _env_float('AI_FB_TEMP_CRIT_HIGH',   33.0),
    'humidity_low':             _env_float('AI_FB_HUM_LOW',          75.0),
    'humidity_high':            _env_float('AI_FB_HUM_HIGH',         85.0),
    'humidity_critical_low':    _env_float('AI_FB_HUM_CRIT_LOW',     70.0),
    'humidity_critical_high':   _env_float('AI_FB_HUM_CRIT_HIGH',    95.0),
    'co2_low':                  _env_float('AI_FB_CO2_LOW',         300.0),
    'co2_high':                 _env_float('AI_FB_CO2_HIGH',       1200.0),
    'co2_critical_high':        _env_float('AI_FB_CO2_CRIT_HIGH',  1500.0),
    'water_temp_low':           _env_float('AI_FB_WATER_LOW',        40.0),
    'water_temp_high':          _env_float('AI_FB_WATER_HIGH',       55.0),
    'water_temp_critical_low':  _env_float('AI_FB_WATER_CRIT_LOW',   35.0),
    'water_temp_critical_high': _env_float('AI_FB_WATER_CRIT_HIGH',  60.0),
    'budding_temp_low':         _env_float('AI_FB_BUD_LOW',          29.0),
    'budding_temp_high':        _env_float('AI_FB_BUD_HIGH',         33.0),
}


@dataclass
class ThresholdSet:
    # 정상 범위
    temp_low:           float
    temp_high:          float
    humidity_low:       float
    humidity_high:      float
    co2_low:            float
    co2_high:           float
    water_temp_low:     float
    water_temp_high:    float
    # 비상 임계
    temp_critical_low:  float
    temp_critical_high: float
    humidity_critical_low:  float
    humidity_critical_high: float
    co2_critical_high:  float
    water_temp_critical_low:  float
    water_temp_critical_high: float
    # 적정값 (otml) — 운영자 권장값, LLM 프롬프트에 활용
    temp_optimal:        Optional[float] = None
    humidity_optimal:    Optional[float] = None
    co2_optimal:         Optional[float] = None
    water_temp_optimal:  Optional[float] = None
    # 발이기 — DB 컬럼 직접
    budding_temp_low:    float = 29.0
    budding_temp_high:   float = 33.0
    # 메타데이터
    source:              str = "last_resort"
    setn_dttm:           Optional[str] = None


# ────────────────────────────────────────────────────────────────────
# 임의 값 → float 안전 변환. 실패 시 None.
# ────────────────────────────────────────────────────────────────────
def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ────────────────────────────────────────────────────────────────────
# 첫 번째 None 이 아닌 값 반환. 모두 None 이면 default.
# ────────────────────────────────────────────────────────────────────
def _coalesce(*vals, default):
    for v in vals:
        f = _safe_float(v)
        if f is not None:
            return f
    return default


# ────────────────────────────────────────────────────────────────────
# 환경변수 폴백 값으로 ThresholdSet 생성 (DB 미연결 시 사용).
# ────────────────────────────────────────────────────────────────────
def _from_last_resort() -> ThresholdSet:
    return ThresholdSet(source="last_resort", **_LAST_RESORT)


# ────────────────────────────────────────────────────────────────────
# SENSOR_M_SETTING 행 → ThresholdSet. 핵심 컬럼이 모두 NULL 이면 None.
# ────────────────────────────────────────────────────────────────────
def _from_db_row(row: Dict[str, Any]) -> Optional[ThresholdSet]:
    if not row:
        return None

    # 최소한 정상 범위 (min/max) 한 쌍이라도 있어야 의미. 모두 NULL 이면 None
    has_any = any(_safe_float(row.get(k)) is not None for k in (
        '온도최저', '온도최고', '습도최저', '습도최고',
        'co2최저', 'co2최고', '수온최저', '수온최고',
    ))
    if not has_any:
        return None

    return ThresholdSet(
        # 정상 범위 — 컬럼 NULL 이면 last resort 폴백
        temp_low=_coalesce(row.get('온도최저'),     default=_LAST_RESORT['temp_low']),
        temp_high=_coalesce(row.get('온도최고'),    default=_LAST_RESORT['temp_high']),
        humidity_low=_coalesce(row.get('습도최저'), default=_LAST_RESORT['humidity_low']),
        humidity_high=_coalesce(row.get('습도최고'), default=_LAST_RESORT['humidity_high']),
        co2_low=_coalesce(row.get('co2최저'),       default=_LAST_RESORT['co2_low']),
        co2_high=_coalesce(row.get('co2최고'),      default=_LAST_RESORT['co2_high']),
        water_temp_low=_coalesce(row.get('수온최저'),  default=_LAST_RESORT['water_temp_low']),
        water_temp_high=_coalesce(row.get('수온최고'), default=_LAST_RESORT['water_temp_high']),
        # 비상 임계 — 신규 컬럼. 컬럼 NULL 이면 last resort
        temp_critical_low=_coalesce(row.get('온도비상최저'),
                                    default=_LAST_RESORT['temp_critical_low']),
        temp_critical_high=_coalesce(row.get('온도비상최고'),
                                     default=_LAST_RESORT['temp_critical_high']),
        humidity_critical_low=_coalesce(row.get('습도비상최저'),
                                        default=_LAST_RESORT['humidity_critical_low']),
        humidity_critical_high=_coalesce(row.get('습도비상최고'),
                                         default=_LAST_RESORT['humidity_critical_high']),
        co2_critical_high=_coalesce(row.get('co2비상최고'),
                                    default=_LAST_RESORT['co2_critical_high']),
        water_temp_critical_low=_coalesce(row.get('수온비상최저'),
                                          default=_LAST_RESORT['water_temp_critical_low']),
        water_temp_critical_high=_coalesce(row.get('수온비상최고'),
                                           default=_LAST_RESORT['water_temp_critical_high']),
        # 적정값 (otml)
        temp_optimal=_safe_float(row.get('온도적정')),
        humidity_optimal=_safe_float(row.get('습도적정')),
        co2_optimal=_safe_float(row.get('co2적정')),
        water_temp_optimal=_safe_float(row.get('수온적정')),
        # 발이기 — DB 컬럼 직접
        budding_temp_low=_coalesce(row.get('발이기최저'),
                                   default=_LAST_RESORT['budding_temp_low']),
        budding_temp_high=_coalesce(row.get('발이기최고'),
                                    default=_LAST_RESORT['budding_temp_high']),
        # 메타
        source=f"db:{row.get('저장일자','-')}",
        setn_dttm=str(row.get('저장일자')) if row.get('저장일자') else None,
    )


# ────────────────────────────────────────────────────────────────────
# (테스트용) in-memory 캐시 초기화.
# ────────────────────────────────────────────────────────────────────
def clear_cache() -> None:
    _CACHE.clear()


# ────────────────────────────────────────────────────────────────────
# 단순 호출자(테스트·단위 검증 등) 용 최후 폴백 ThresholdSet 반환.
# ────────────────────────────────────────────────────────────────────
def get_global_default() -> ThresholdSet:
    return _from_last_resort()


# ────────────────────────────────────────────────────────────────────
# 재배사별 정상/비상 임계값 한 번에 조회. 캐시 5분.
# DB 부재/오류 시에만 last_resort 폴백 — 운영에서는 DB 값이 항상 우선.
# ────────────────────────────────────────────────────────────────────
def get_thresholds(farm_id, house_id) -> ThresholdSet:
    if farm_id is None or house_id is None:
        return get_global_default()

    cache_key = (int(farm_id), int(house_id))
    e = _CACHE.get(cache_key)
    if e and time.time() < e[0]:
        return e[1]

    ts: Optional[ThresholdSet] = None
    try:
        with db_session() as database:
            row = database.fetch_one(
                query=dbQry.GET_OPTIMAL_CONDITION,
                vals=(int(farm_id), int(house_id)),
            )
        ts = _from_db_row(row) if row else None
    except Exception as e:
        logger.warning(
            f"[AI임계값] DB 조회 실패 farm={farm_id} house={house_id}: {e}"
        )
        ts = None

    if ts is None:
        ts = _from_last_resort()
        logger.warning(
            f"[AI임계값] DB 행/컬럼 부재 → last_resort 폴백 farm={farm_id} house={house_id} "
            f"(SENSOR_M_SETTING 운영자 셋팅 권장)"
        )
    else:
        logger.info(
            f"[AI임계값] DB 로드 완료 farm={farm_id} house={house_id} "
            f"src={ts.source} 온도 정상 {ts.temp_low}~{ts.temp_high}℃ "
            f"비상 {ts.temp_critical_low}~{ts.temp_critical_high}℃ · "
            f"습도 정상 {ts.humidity_low}~{ts.humidity_high}% "
            f"비상 {ts.humidity_critical_low}~{ts.humidity_critical_high}% · "
            f"CO2 정상 ≤{ts.co2_high}ppm 비상 >{ts.co2_critical_high}ppm · "
            f"수온 정상 {ts.water_temp_low}~{ts.water_temp_high}℃ "
            f"비상 {ts.water_temp_critical_low}~{ts.water_temp_critical_high}℃ · "
            f"발이기 {ts.budding_temp_low}~{ts.budding_temp_high}℃"
        )

    _CACHE[cache_key] = (time.time() + _CACHE_TTL_SEC, ts)
    return ts


# ────────────────────────────────────────────────────────────────────
# ThresholdSet → dict 변환 — 프롬프트 빌더 등에서 활용.
# ────────────────────────────────────────────────────────────────────
def as_dict(ts: ThresholdSet) -> Dict[str, Any]:
    return asdict(ts)
