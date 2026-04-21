# ════════════════════════════════════════════════════════════════════
# AI 결정 피드백 API (M15 동반) — 사용자가 LLM 결정에 대해 좋아요/싫어요
# 라벨을 제출. 라벨은 ai_decision_log.feedback 컬럼에 기록되어 다음 LLM
# 호출 시 prompt 에 포함됨 → soft RLHF.
# 호출 룰: 본 라우터는 control.ai_feedback 만 호출 (단방향). 다른 control
#          모듈 직접 import 금지.
# --->
# post_feedback : POST /api/v1/ai/feedback         — 피드백 라벨 제출
# get_stats     : GET  /api/v1/ai/feedback/stats   — 최근 N일 통계 조회
# ════════════════════════════════════════════════════════════════════
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.control.ai_feedback import submit_feedback, get_feedback_stats

logger = setup_logger(__name__)

ai_feedback_router = APIRouter(prefix="/api/v1/ai", tags=["ai-feedback"])


class FeedbackRequest(BaseModel):
    decision_id: int = Field(..., description="ai_decision_log.id")
    label: str = Field(..., description="'good' 또는 'bad'")


# ────────────────────────────────────────────────────────────────────
# 피드백 제출 — decision_id + 'good'/'bad' 라벨을 ai_decision_log 에 기록.
# 검증/저장은 control.ai_feedback.submit_feedback 에 위임.
# ────────────────────────────────────────────────────────────────────
@ai_feedback_router.post("/feedback")
def post_feedback(req: FeedbackRequest):
    logger.info(f"[AI피드백·API] 요청 id={req.decision_id} label={req.label}")
    result = submit_feedback(req.decision_id, req.label)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "failed"))
    return result


# ────────────────────────────────────────────────────────────────────
# 피드백 통계 — 최근 lookback_days(1~365) 일간 good/bad 카운트 조회.
# control.ai_feedback.get_feedback_stats 결과를 그대로 반환.
# ────────────────────────────────────────────────────────────────────
@ai_feedback_router.get("/feedback/stats")
def get_stats(lookback_days: int = Query(30, ge=1, le=365)):
    logger.info(f"[AI피드백·API] 통계 요청 lookback={lookback_days}d")
    result = get_feedback_stats(lookback_days)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("message", "failed"))
    return result
