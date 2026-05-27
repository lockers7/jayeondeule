# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 다년치 계절성 모듈 (M16)
# 같은 월(현재 월) 연도별 환경 평균을 비교해 LLM 에 제공.
# 운영 데이터 1년 이상 누적된 경우만 의미 — 데이터 부족 시 빈 결과.
#
# 호출 룰:
#   • control_ai_environment 에서만 import.
#   • 동급 control 모듈 import 금지.
# --->
# get_monthly_seasonality: 현재 월의 연도별 평균 list
# format_seasonality_block: user prompt 한 블록
# ══════════════════════════════════════════════════════════════════════════════
from datetime import datetime
from typing import Any, Dict, List

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
import agri_ai_core.src.postgresql.queries as dbQry

logger = setup_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# 현재 월의 연도별 평균 list 반환. 실패 시 [].
# ────────────────────────────────────────────────────────────────────
def get_monthly_seasonality(farm_id, house_id) -> List[Dict[str, Any]]:
    month = datetime.now().month
    logger.info(
        f"[AI계절성] 동월 평균 조회 farm={farm_id} house={house_id} month={month}"
    )
    try:
        with db_session() as database:
            rows = database.fetch_all(
                query=dbQry.GET_MONTHLY_SEASONALITY,
                vals=(int(farm_id), int(house_id), int(month)),
                as_dict=True,
            ) or []
    except Exception as e:
        logger.warning(f"[AI계절성] 조회 실패 farm={farm_id} house={house_id}: {e}")
        return []
    out = [dict(r) for r in rows]
    logger.info(f"[AI계절성] 결과 {len(out)}년치")
    return out


# ────────────────────────────────────────────────────────────────────
# 연도별 동월 평균 list → user prompt 한 블록 텍스트.
# ────────────────────────────────────────────────────────────────────
def format_seasonality_block(rows: List[Dict[str, Any]]) -> str:
    if not rows or len(rows) < 2:
        return ""
    month = datetime.now().month
    lines = [f"[다년치 동월({month}월) 평균 — {len(rows)}년"]
    for r in rows:
        lines.append(
            f"  · {r.get('yr')}년: "
            f"내부 {r.get('avg_indoor_temp')}℃/{r.get('avg_indoor_humidity')}% · "
            f"CO2 {r.get('avg_co2')}ppm · 수온 {r.get('avg_water_temp')}℃ "
            f"(표본 {r.get('sample_count')})"
        )
    lines.append("  → 다년 평균과 큰 편차가 있는 부분이 있으면 사유 필요.")
    return "\n".join(lines)
