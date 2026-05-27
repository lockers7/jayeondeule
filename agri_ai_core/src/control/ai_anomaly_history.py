# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 이상사건 직전 환경 패턴 모듈 (M9)
# 동일 재배사에서 최근 60일 안에 발생한 병해(pest_type) 이벤트
# 를 찾아 그 직전 24h 의 센서 평균을 LLM 에 제공 → "유사 환경 진입 시 회피"
# 패턴으로 활용.
#
# 호출 룰:
#   • control_ai_environment 에서만 import.
#   • 동급 control 모듈 import 금지.
#   • postgresql + logs 만 의존.
# --->
# get_anomaly_patterns:  최근 N일 안의 병해 이벤트 + 직전 24h 평균
# format_anomaly_block:  user prompt 한 블록
# ══════════════════════════════════════════════════════════════════════════════
from typing import Any, Dict, List

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
import agri_ai_core.src.postgresql.queries as dbQry

logger = setup_logger(__name__)

_LOOKBACK_DAYS = 60
_MAX_EVENTS = 5


# ────────────────────────────────────────────────────────────────────
# 최근 N일 병해 이벤트 + 직전 24h 센서 평균 list.
# ────────────────────────────────────────────────────────────────────
def get_anomaly_patterns(farm_id, house_id, lookback_days: int = _LOOKBACK_DAYS) -> List[Dict[str, Any]]:
    logger.info(
        f"[AI이상사건] 패턴 조회 시작 farm={farm_id} house={house_id} "
        f"lookback={lookback_days}d"
    )
    events: List[Dict[str, Any]] = []
    try:
        with db_session() as database:
            rows = database.fetch_all(
                query=dbQry.GET_RECENT_ANOMALY_EVENTS,
                vals=(int(farm_id), int(house_id), f'{int(lookback_days)} days'),
                as_dict=True,
            ) or []
    except Exception as e:
        logger.warning(f"[AI이상사건] 이벤트 조회 실패 farm={farm_id} house={house_id}: {e}")
        return []

    if not rows:
        logger.info(f"[AI이상사건] 최근 {lookback_days}일 병해 이벤트 없음 — 패턴 없음")
        return []

    for row in rows[:_MAX_EVENTS]:
        ev_time = row.get('event_time')
        if not ev_time:
            continue
        try:
            with db_session() as database:
                avg = database.fetch_one(
                    query=dbQry.GET_SENSOR_AVG_BEFORE,
                    vals=(int(farm_id), int(house_id), ev_time, ev_time),
                )
        except Exception as e:
            logger.warning(f"[AI이상사건] 직전 24h 평균 조회 실패 ev={ev_time}: {e}")
            avg = None
        events.append({
            'event_time':  ev_time,
            'pest_type':   row.get('pest_type') or '',
            'pest_severity': row.get('pest_severity') or '',
            'memo':        (row.get('growth_memo') or '')[:80],
            'crop_lvel':   row.get('crop_lvel') or '',
            'avg_24h':     dict(avg) if avg else {},
        })

    logger.info(
        f"[AI이상사건] 패턴 조회 완료 farm={farm_id} house={house_id} → "
        f"이벤트 {len(events)}건"
    )
    return events


# ────────────────────────────────────────────────────────────────────
# 이상사건 패턴 list 를 user prompt 한 블록 텍스트로 변환.
# ────────────────────────────────────────────────────────────────────
def format_anomaly_block(events: List[Dict[str, Any]]) -> str:
    if not events:
        return ""
    lines = [f"[이상사건 직전 환경 패턴 — 최근 60일 {len(events)}건]"]
    for ev in events:
        a = ev.get('avg_24h') or {}
        lines.append(
            f"  · {ev['event_time'][:10]} {ev['pest_type']}({ev['pest_severity']}) "
            f"단계={ev['crop_lvel']} | 직전24h 평균: "
            f"{a.get('avg_indoor_temp')}℃/{a.get('avg_indoor_humidity')}%/"
            f"CO2 {a.get('avg_co2')}ppm/수온 {a.get('avg_water_temp')}℃"
        )
    lines.append("  ⚠ 위 평균과 유사한 환경으로 진입 시 보수적 운용 권장.")
    return "\n".join(lines)
