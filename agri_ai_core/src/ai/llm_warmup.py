# ════════════════════════════════════════════════════════════
# LLM 워밍업 — 백그라운드에서 첫 LLM 호출로 모델 VRAM 적재 + 추론 준비.
# startup.py에서 1회 호출. llm_client.py에서 분리.
# --->
# _perform_llm_warmup: LLM에 ping 요청으로 모델 사전 로드
# initialize_background_warmup: 백그라운드 스레드로 워밍업 시작
# ════════════════════════════════════════════════════════════
import threading

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_warmup_lock = threading.Lock()
_warmup_started = False
_llm_warmed = False


def _perform_llm_warmup():
    """LLM에 간단한 ping 요청으로 모델을 VRAM에 적재. 프로세스당 1회."""
    global _llm_warmed
    if _llm_warmed:
        return
    try:
        from agri_ai_core.src.ai.llm_transport import _get_model_name
        from agri_ai_core.src.ai.llm_transport import _ollama_chat

        model_name = _get_model_name()
        _ollama_chat(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a concise assistant. Respond with one word."},
                {"role": "user", "content": "ping"}
            ],
            options={
                "temperature": 0.0,
                "top_p": 0.1,
                "top_k": 1,
                "num_predict": 4
            }
        )
        _llm_warmed = True
        logger.debug("LLM warm-up completed.")
    except Exception as warm_err:
        logger.warning(f"LLM warm-up failed: {warm_err}")


def initialize_background_warmup(farm_id=None, house_id=None, farm_name=None, house_name=None):
    """백그라운드 스레드로 워밍업 시작. 중복 호출 방지."""
    global _warmup_started
    with _warmup_lock:
        if _warmup_started:
            return
        _warmup_started = True
    threading.Thread(target=_perform_llm_warmup, daemon=True).start()
