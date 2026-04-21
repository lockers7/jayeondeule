# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 사용자 피드백 모듈 (M15)
# [2026-04-28 신규] LLM 결정에 대해 사용자가 좋아요/싫어요 라벨을 붙일 수 있게
# 한다. 라벨은 ai_decision_log.feedback 컬럼에 기록되고, 다음 LLM 호출 시
# get_recent 결과에 포함되어 prompt 에 노출 → soft RLHF.
#
# FastAPI 라우터는 별도 위치 (web/api/router_ai_feedback.py)에 구현 권장.
# 본 모듈은 핵심 비즈니스 로직과 검증만 담당.
#
# 호출 룰:
#   • FastAPI 라우터 / CLI 도구에서 import.
#   • 동급 control 모듈 import 금지(ai_decision_log 만 데이터레이어로 사용).
#     → 단방향: ai_feedback → ai_decision_log → postgresql.
# --->
# submit_feedback: decision_id + label 검증 후 update
# get_feedback_stats: 최근 N일 좋아요/싫어요 비율 (운영 모니터링)
# ══════════════════════════════════════════════════════════════════════════════
from typing import Any, Dict

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
from agri_ai_core.src.control.ai_decision_log import update_feedback as _update_feedback

logger = setup_logger(__name__)


VALID_LABELS = ('good', 'bad')


# ────────────────────────────────────────────────────────────────────
# 단일 결정에 대한 피드백 라벨 갱신 — 검증 + DB 업데이트 + 결과 dict 반환.
# ────────────────────────────────────────────────────────────────────
def submit_feedback(decision_id: int, label: str) -> Dict[str, Any]:
    if label not in VALID_LABELS:
        logger.warning(f"[AI피드백] 잘못된 라벨 id={decision_id} label={label}")
        return {"success": False, "message": f"label must be one of {VALID_LABELS}"}
    try:
        decision_id_int = int(decision_id)
    except (TypeError, ValueError):
        return {"success": False, "message": "decision_id must be integer"}

    ok = _update_feedback(decision_id_int, label)
    if ok:
        logger.info(f"[AI피드백] 접수 id={decision_id_int} label={label}")
        return {"success": True, "message": "feedback recorded",
                "decision_id": decision_id_int, "label": label}
    return {"success": False, "message": "update failed"}


_STATS_QUERY = """
SELECT feedback,
       COUNT(*) AS cnt
  FROM ai_decision_log
 WHERE decided_at >= NOW() - %s::interval
   AND feedback IS NOT NULL
 GROUP BY feedback;
"""


# ────────────────────────────────────────────────────────────────────
# 최근 N일 피드백 라벨별 카운트 + 좋아요 비율 dict 반환 (운영 모니터링).
# ────────────────────────────────────────────────────────────────────
def get_feedback_stats(lookback_days: int = 30) -> Dict[str, Any]:
    try:
        with db_session() as database:
            rows = database.fetch_all(
                query=_STATS_QUERY,
                vals=(f"{int(lookback_days)} days",),
                as_dict=True,
            ) or []
    except Exception as e:
        logger.warning(f"[AI피드백] 통계 조회 실패: {e}")
        return {"success": False, "message": str(e)}

    counts = {label: 0 for label in VALID_LABELS}
    for r in rows:
        lab = r.get('feedback')
        if lab in counts:
            counts[lab] = int(r.get('cnt') or 0)
    total = sum(counts.values())
    out = {
        "success":      True,
        "lookback_days": int(lookback_days),
        "counts":       counts,
        "total":        total,
        "good_ratio":   round(counts['good'] / total, 3) if total else 0.0,
    }
    logger.info(
        f"[AI피드백] 통계 lookback={lookback_days}d good={counts['good']} "
        f"bad={counts['bad']} good_ratio={out['good_ratio']}"
    )
    return out
