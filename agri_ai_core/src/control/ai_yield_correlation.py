# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 수확 결과 상관 모듈 (M13)
# 동일 재배사에서 1등급률 ≥ 0.6 였던 과거 시기 N건의
# 환경 평균을 추출해 "성공 패턴"으로 LLM 에 제공.
#
# 호출 룰:
#   • control_ai_environment 에서만 import.
#   • 동급 control 모듈 import 금지.
#   • postgresql + logs 만 의존.
# --->
# get_high_quality_periods:  1등급률 높은 과거 시기 + 그 시기 환경 평균
# format_yield_block:        user prompt 한 블록
# ══════════════════════════════════════════════════════════════════════════════
from typing import Any, Dict, List

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
import agri_ai_core.src.postgresql.queries as dbQry

logger = setup_logger(__name__)

_MAX_PERIODS = 3


# ────────────────────────────────────────────────────────────────────
# 1등급률 ≥ 0.6 인 과거 시기 + 해당 일자 직전 24h 환경 평균 list 반환.
# ────────────────────────────────────────────────────────────────────
def get_high_quality_periods(farm_id, house_id) -> List[Dict[str, Any]]:
    logger.info(f"[AI수확상관] 고품질 시기 조회 시작 farm={farm_id} house={house_id}")
    try:
        with db_session() as database:
            rows = database.fetch_all(
                query=dbQry.GET_HIGH_QUALITY_PERIODS,
                vals=(int(farm_id), int(house_id)),
                as_dict=True,
            ) or []
    except Exception as e:
        logger.warning(f"[AI수확상관] 고품질 시기 조회 실패 farm={farm_id} house={house_id}: {e}")
        return []
    if not rows:
        logger.info(f"[AI수확상관] 1등급률 ≥0.6 시기 없음 farm={farm_id} house={house_id}")
        return []

    out: List[Dict[str, Any]] = []
    for row in rows[:_MAX_PERIODS]:
        period = row.get('period_date')
        if not period:
            continue
        # 그 시기 직전 24h 환경 평균 조회
        try:
            with db_session() as database:
                avg = database.fetch_one(
                    query=dbQry.GET_SENSOR_AVG_BEFORE,
                    vals=(int(farm_id), int(house_id),
                          f"{period} 12:00:00", f"{period} 12:00:00"),
                )
        except Exception as e:
            logger.warning(f"[AI수확상관] 환경 평균 조회 실패 period={period}: {e}")
            avg = None
        out.append({
            'period_date':     period,
            'crop_lvel':       row.get('crop_lvel'),
            'grade_1_ratio':   row.get('grade_1_ratio'),
            'total_yield':     row.get('total_yield'),
            'grade_1_yield':   row.get('grade_1_yield'),
            'avg_24h':         dict(avg) if avg else {},
        })
    logger.info(f"[AI수확상관] 고품질 시기 조회 완료 → {len(out)}건")
    return out


# ────────────────────────────────────────────────────────────────────
# 고품질 시기 list → user prompt 한 블록 텍스트.
# ────────────────────────────────────────────────────────────────────
def format_yield_block(periods: List[Dict[str, Any]]) -> str:
    if not periods:
        return ""
    lines = [f"[수확 성공 패턴 — 1등급률 ≥0.6 시기 {len(periods)}건]"]
    for p in periods:
        a = p.get('avg_24h') or {}
        lines.append(
            f"  · {p['period_date']} 단계={p.get('crop_lvel')} "
            f"1등급률={p.get('grade_1_ratio')} 총수확={p.get('total_yield')} | "
            f"직전24h 평균: {a.get('avg_indoor_temp')}℃/"
            f"{a.get('avg_indoor_humidity')}%/CO2 {a.get('avg_co2')}ppm"
        )
    lines.append("  → 위 평균 환경에 가까울수록 수확 품질이 양호했음 — 가능하면 유지 지향.")
    return "\n".join(lines)
