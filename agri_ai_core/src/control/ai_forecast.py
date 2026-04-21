# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 단순 시계열 예측 모듈 (M14)
# [2026-04-28 신규] 최근 60분 ~ 6시간 센서 데이터로 5분 / 1시간 후 값을 예측해
# LLM 에 제공. 외부 라이브러리 없이 (a) 선형회귀 기울기 (b) 최근 윈도우 평균
# 두 가지를 결합한 단순 추정 — 정확도보다 LLM 시야 확장이 목적.
#
# 호출 룰:
#   • control_ai_environment 에서만 import.
#   • 동급 control 모듈 import 금지.
#   • postgresql + logs 만 의존.
# --->
# get_forecast: 5분 / 1시간 후 예측 dict
# format_forecast_block: user prompt 한 블록
# ══════════════════════════════════════════════════════════════════════════════
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session

logger = setup_logger(__name__)


_QUERY_RECENT_60MIN = """
SELECT EXTRACT(EPOCH FROM recd_dttm) AS ts_epoch,
       indr_tprt_valu AS indoor_temp,
       indr_hmdt_valu AS indoor_humidity,
       co2_valu       AS co2,
       watr_tprt_valu AS water_temp
  FROM SENSOR_L_RECORDING
 WHERE farm_id = %s AND hous_id = %s
   AND recd_dttm >= NOW() - INTERVAL '60 minutes'
 ORDER BY recd_dttm ASC;
"""


# ────────────────────────────────────────────────────────────────────
# 단순 최소제곱 선형회귀로 horizon_sec 후 값 예측. None safe.
# ────────────────────────────────────────────────────────────────────
def _linear_predict(points: List[Tuple[float, float]], horizon_sec: float) -> Optional[float]:
    if len(points) < 5:
        return None
    n = len(points)
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    mean_x = sx / n
    mean_y = sy / n
    num = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points)
    den = sum((p[0] - mean_x) ** 2 for p in points)
    if den == 0:
        return mean_y
    slope = num / den
    intercept = mean_y - slope * mean_x
    last_t = points[-1][0]
    return slope * (last_t + horizon_sec) + intercept


# ────────────────────────────────────────────────────────────────────
# 최근 60분 시계열로 5분/1시간 후 예측 dict 반환. 데이터 부족 시 {}.
# ────────────────────────────────────────────────────────────────────
def get_forecast(farm_id, house_id) -> Dict[str, Any]:
    logger.info(f"[AI예측] 시계열 예측 시작 farm={farm_id} house={house_id}")
    try:
        with db_session() as database:
            rows = database.fetch_all(
                query=_QUERY_RECENT_60MIN,
                vals=(int(farm_id), int(house_id)),
                as_dict=True,
            ) or []
    except Exception as e:
        logger.warning(f"[AI예측] 데이터 조회 실패 farm={farm_id} house={house_id}: {e}")
        return {}

    if len(rows) < 10:
        logger.info(f"[AI예측] 표본 부족 ({len(rows)}건) — 예측 스킵")
        return {}

    metrics = ['indoor_temp', 'indoor_humidity', 'co2', 'water_temp']
    series = {m: [] for m in metrics}
    for r in rows:
        try:
            ts = float(r.get('ts_epoch') or 0)
        except (TypeError, ValueError):
            continue
        for m in metrics:
            v = r.get(m)
            if v is None:
                continue
            try:
                series[m].append((ts, float(v)))
            except (TypeError, ValueError):
                continue

    out: Dict[str, Any] = {'sample_count': len(rows), 'metrics': {}}
    for m, pts in series.items():
        if len(pts) < 5:
            continue
        cur = pts[-1][1]
        p5 = _linear_predict(pts, 5 * 60)
        p60 = _linear_predict(pts, 60 * 60)
        out['metrics'][m] = {
            'current':     round(cur, 2),
            'pred_5min':   round(p5, 2) if p5 is not None else None,
            'pred_60min':  round(p60, 2) if p60 is not None else None,
        }
    logger.info(
        f"[AI예측] 완료 farm={farm_id} house={house_id} "
        f"표본={len(rows)} 지표={len(out['metrics'])}"
    )
    return out


_LABELS = {
    'indoor_temp':     ('내부온도', '℃'),
    'indoor_humidity': ('내부습도', '%'),
    'co2':             ('CO2',     'ppm'),
    'water_temp':      ('수온',    '℃'),
}


# ────────────────────────────────────────────────────────────────────
# 예측 payload → user prompt 한 블록 텍스트.
# ────────────────────────────────────────────────────────────────────
def format_forecast_block(payload: Dict[str, Any]) -> str:
    metrics = (payload or {}).get('metrics') or {}
    if not metrics:
        return ""
    lines = [f"[단기 예측 (선형회귀 · 표본 {(payload or {}).get('sample_count','-')})]"]
    for key, (label, unit) in _LABELS.items():
        m = metrics.get(key)
        if not m:
            continue
        lines.append(
            f"  · {label}: 현재 {m.get('current')}{unit} → "
            f"5분 후 {m.get('pred_5min')}{unit} · 1시간 후 {m.get('pred_60min')}{unit}"
        )
    lines.append("  → 5분/1시간 후 예측이 비상 임계 근접이면 사전 조치 권장.")
    return "\n".join(lines)
