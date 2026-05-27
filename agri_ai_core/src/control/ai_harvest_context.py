# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 수확 임박 컨텍스트 모듈 (M8)
# FARMHOUSE_L_CROPS 의 가장 최근 crop_strt_date / crop_end_date
# 를 조회해 수확 D-N 일자를 LLM 에 제공.
#   · D ≤ 3 : "환경 변화 최소화 — 보수적 결정 권장"
#   · D ≤ 7 : "수확 임박 — 신중 모드"
#   · D > 7 : 일반
#
# 호출 룰:
#   • control_ai_environment 에서만 import.
#   • 동급 control 모듈 import 금지.
# --->
# get_harvest_context:  현재 작기 시작/종료 + 잔여일
# format_harvest_block: user prompt 한 줄 텍스트
# ══════════════════════════════════════════════════════════════════════════════
from datetime import datetime, date
from typing import Any, Dict, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session

logger = setup_logger(__name__)


_HARVEST_QUERY = """
SELECT TO_CHAR(crop_strt_date, 'YYYY-MM-DD') AS crop_strt,
       TO_CHAR(crop_end_date,  'YYYY-MM-DD') AS crop_end,
       crop_lvel,
       crop_kind
  FROM FARMHOUSE_L_CROPS
 WHERE farm_id = %s AND hous_id = %s
   AND (crop_strt_date IS NOT NULL OR crop_end_date IS NOT NULL)
 ORDER BY recd_dttm DESC
 LIMIT 1;
"""


# ────────────────────────────────────────────────────────────────────
# "YYYY-MM-DD" 문자열 → date 객체. 실패 시 None.
# ────────────────────────────────────────────────────────────────────
def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


# ────────────────────────────────────────────────────────────────────
# 현재 작기의 수확 임박 정보(시작/종료/잔여일/생육단계)를 dict 로 반환.
# ────────────────────────────────────────────────────────────────────
def get_harvest_context(farm_id, house_id) -> Dict[str, Any]:
    try:
        with db_session() as database:
            row = database.fetch_one(query=_HARVEST_QUERY,
                                     vals=(int(farm_id), int(house_id)))
    except Exception as e:
        logger.warning(f"[AI수확임박] 조회 실패 farm={farm_id} house={house_id}: {e}")
        return {}

    if not row:
        logger.info(f"[AI수확임박] 작기 정보 없음 farm={farm_id} house={house_id}")
        return {}

    today = date.today()
    crop_strt = _parse_date(row.get('crop_strt'))
    crop_end = _parse_date(row.get('crop_end'))

    days_remaining = (crop_end - today).days if crop_end else None
    days_since_start = (today - crop_strt).days if crop_strt else None

    payload = {
        'crop_strt':        row.get('crop_strt'),
        'crop_end':         row.get('crop_end'),
        'days_remaining':   days_remaining,
        'days_since_start': days_since_start,
        'crop_lvel':        row.get('crop_lvel'),
        'crop_kind':        row.get('crop_kind'),
    }
    logger.info(
        f"[AI수확임박] farm={farm_id} house={house_id} "
        f"D-{days_remaining if days_remaining is not None else '?'} "
        f"(시작 {row.get('crop_strt')} · 종료 {row.get('crop_end')})"
    )
    return payload


# ────────────────────────────────────────────────────────────────────
# 수확 컨텍스트 dict → user prompt 한 줄 텍스트 (D-N 일 + 권고).
# ────────────────────────────────────────────────────────────────────
def format_harvest_block(ctx: Dict[str, Any]) -> str:
    if not ctx:
        return ""
    dr = ctx.get('days_remaining')
    ds = ctx.get('days_since_start')

    if dr is None and ds is None:
        return ""

    bits = []
    if ctx.get('crop_strt'):
        bits.append(f"작기시작 {ctx['crop_strt']}")
    if ctx.get('crop_end'):
        bits.append(f"종료예정 {ctx['crop_end']}")
    if ds is not None:
        bits.append(f"경과 {ds}일")
    if dr is not None:
        bits.append(f"잔여 {dr}일(D-{dr})")

    advice = ""
    if dr is not None:
        if dr <= 3:
            advice = " ⚠ 수확 D-3 이내 — 환경 변화 최소화·보수적 결정 권장"
        elif dr <= 7:
            advice = " ⚠ 수확 임박 — 신중 모드"

    return f"[수확 컨텍스트] {' / '.join(bits)}{advice}"
