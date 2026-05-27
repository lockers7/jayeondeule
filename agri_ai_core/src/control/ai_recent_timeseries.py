# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 최근 raw 시계열 모듈 (M19)
#
# _detect_trend 의 분당 변화율 한 줄 요약과 별개로 LLM 이 raw 시계열을 직접
# 보도록, SENSOR_L_RECORDING 에서 N분 bucket 마다 가장 최근 1건씩 K개
# (기본 3분 주기 20개)를 추출해 LLM user prompt 에 직접 노출한다.
#
# 기본값 (환경변수로 외부화 — 하드코딩 금지):
#   AI_TS_INTERVAL_MIN  = 3   분 단위 bucket
#   AI_TS_SAMPLE_COUNT  = 20  최대 샘플 수 (LLM context 부담 고려)
#
# 호출 룰:
#   • control_ai_environment 에서만 import.
#   • 동급 control 모듈 import 금지.
#   • postgresql + logs 만 의존.
# --->
# get_recent_samples:   (farm_id, house_id) → list[dict] (raw 시계열)
# format_recent_block:  user prompt 한 블록 텍스트
# ══════════════════════════════════════════════════════════════════════════════
import os
from typing import Any, Dict, List

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
import agri_ai_core.src.postgresql.queries as dbQry

logger = setup_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# 환경변수 값을 int 로 안전 변환. 미설정/실패 시 default.
# ────────────────────────────────────────────────────────────────────
def _env_int(key: str, default: int) -> int:
    v = os.getenv(key)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


_INTERVAL_MIN = _env_int("AI_TS_INTERVAL_MIN", 3)
_SAMPLE_COUNT = _env_int("AI_TS_SAMPLE_COUNT", 20)


# ────────────────────────────────────────────────────────────────────
# 3분 간격 20건(=60분 분량) raw 시계열을 list[dict] 로 반환. 실패 시 [].
# ────────────────────────────────────────────────────────────────────
def get_recent_samples(farm_id, house_id) -> List[Dict[str, Any]]:
    if farm_id is None or house_id is None:
        return []

    bucket_sec = max(60, _INTERVAL_MIN * 60)            # 최소 60초
    lookback_min = max(1, _INTERVAL_MIN * _SAMPLE_COUNT)  # 분 단위
    logger.info(
        f"[AI시계열] 최근 raw 추출 시작 farm={farm_id} house={house_id} "
        f"interval={_INTERVAL_MIN}min count={_SAMPLE_COUNT} "
        f"(bucket_sec={bucket_sec}, lookback_min={lookback_min})"
    )
    try:
        with db_session() as database:
            rows = database.fetch_all(
                query=dbQry.GET_RECENT_TIMESERIES_SAMPLES,
                vals=(int(bucket_sec), int(farm_id), int(house_id),
                      int(lookback_min), int(_SAMPLE_COUNT)),
                as_dict=True,
            ) or []
    except Exception as e:
        logger.warning(
            f"[AI시계열] 조회 실패 farm={farm_id} house={house_id}: {e}"
        )
        return []

    out = [dict(r) for r in rows]
    logger.info(
        f"[AI시계열] 완료 farm={farm_id} house={house_id} → {len(out)}건"
    )
    return out


# ────────────────────────────────────────────────────────────────────
# 숫자값 포맷팅 — value+unit (digits 자릿수). None 은 "-".
# ────────────────────────────────────────────────────────────────────
def _fmt_num(v, unit: str = "", digits: int = 1):
    if v is None:
        return "-"
    try:
        return f"{float(v):.{digits}f}{unit}"
    except (TypeError, ValueError):
        return str(v)


# ────────────────────────────────────────────────────────────────────
# raw 시계열 list → user prompt 한 블록 텍스트. 비어있으면 "" 반환.
# ────────────────────────────────────────────────────────────────────
def format_recent_block(samples: List[Dict[str, Any]]) -> str:
    if not samples:
        return ""
    lines = [
        f"[최근 {_INTERVAL_MIN}분 간격 raw 시계열 — 최신→과거 순, {len(samples)}건]"
    ]
    for r in samples:
        t = (r.get('t') or '')[-8:]  # HH:MM:SS
        lines.append(
            f"  · {t}: 내부 {_fmt_num(r.get('indoor_temp'),'℃')}/"
            f"{_fmt_num(r.get('indoor_humidity'),'%')} · "
            f"CO2 {_fmt_num(r.get('co2'),'ppm',0)} · "
            f"수온 {_fmt_num(r.get('water_temp'),'℃')} · "
            f"외부 {_fmt_num(r.get('outdoor_temp'),'℃')}/"
            f"{_fmt_num(r.get('outdoor_humidity'),'%')}"
        )
    lines.append(
        "  → 분당 변화율·노이즈 직접 확인 가능. 추세 판단 시 단기 deque 변동에 "
        "휘둘리지 말고 raw 시계열의 일관된 방향성을 우선 사용."
    )
    return "\n".join(lines)
