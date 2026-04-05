# ════════════════════════════════════════════════════════════
# LLM 기반 Reranker: 벡터 검색 후보를 관련성 점수로 재정렬.
# ════════════════════════════════════════════════════════════
import os
import re
import json
import time
from typing import Any, Dict, List

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import get_ollama_url, get_model_name

logger = setup_logger(__name__)

# Reranker 설정
RERANK_TIMEOUT = int(os.getenv("RERANK_TIMEOUT", "30"))
RERANK_MAX_CANDIDATES = int(os.getenv("RERANK_MAX_CANDIDATES", "10"))
RERANK_MIN_SCORE = int(os.getenv("RERANK_MIN_SCORE", "4"))
RERANK_MAX_RETRIES = int(os.getenv("RERANK_MAX_RETRIES", "1"))


# ════════════════════════════════════════════════════════════
# Reranking 프롬프트 생성 — 각 문서에 관련성 점수(1-10) 요청
# ════════════════════════════════════════════════════════════
def _build_rerank_prompt(query: str, documents: List[Dict[str, Any]]) -> str:
    doc_texts = []
    for i, doc in enumerate(documents):
        content = doc.get("content", "")[:400]
        collection = doc.get("collection", "unknown")
        doc_texts.append(f"[문서{i}] (출처: {collection}) {content}")

    docs_block = "\n".join(doc_texts)

    return (
        f"/no_think\n"
        f"사용자 질문: {query}\n\n"
        f"아래 문서들이 사용자 질문에 얼마나 관련되는지 1-10 점수로 평가하세요.\n\n"
        f"채점 기준:\n"
        f"- 10: 질문에 대한 직접적인 답변이 포함된 문서\n"
        f"- 7-9: 질문과 같은 주제이며 유용한 정보 포함\n"
        f"- 4-6: 부분적으로 관련 있지만 직접적 답변은 아님\n"
        f"- 1-3: 질문과 무관하거나 다른 주제의 문서\n\n"
        f"중요: 단어가 겹치더라도 주제가 다르면 낮은 점수를 부여하세요.\n\n"
        f"{docs_block}\n\n"
        f"JSON 배열만 출력하세요. 예: [8,3,7,5]\n"
        f"문서 순서대로 점수를 나열하세요."
    )


# ════════════════════════════════════════════════════════════
# LLM 응답에서 점수 배열 파싱
# ════════════════════════════════════════════════════════════
def _parse_scores(response_text: str, expected_count: int) -> List[int]:
    if not response_text:
        return []

    # <think>...</think> 태그 제거 (qwen3 모델이 /no_think 무시하는 경우 대응)
    from agri_ai_core.src.ai.utils import strip_think_tags
    cleaned = strip_think_tags(response_text)
    if cleaned:
        response_text = cleaned

    # JSON 배열 패턴 매칭
    array_match = re.search(r'\[[\d\s,]+\]', response_text)
    if array_match:
        try:
            scores = json.loads(array_match.group())
            if isinstance(scores, list) and len(scores) == expected_count:
                return [max(1, min(10, int(s))) for s in scores]
        except (json.JSONDecodeError, ValueError):
            pass

    # 쉼표/공백 구분 숫자 파싱
    numbers = re.findall(r'\b(\d{1,2})\b', response_text)
    if len(numbers) >= expected_count:
        scores = [max(1, min(10, int(n))) for n in numbers[:expected_count]]
        return scores

    return []


# ════════════════════════════════════════════════════════════
# LLM 기반 Reranker 메인 함수
# ════════════════════════════════════════════════════════════
def rerank_results(
    query: str,
    results: List[Dict[str, Any]],
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    if not results:
        return []

    if len(results) <= 1:
        return results[:top_k]

    candidates = results[:RERANK_MAX_CANDIDATES]
    t_start = time.time()
    scores = []
    last_error = ""

    for attempt in range(1 + RERANK_MAX_RETRIES):
        try:
            from agri_ai_core.src.ai.mcp_client import mcp_http_request

            ollama_url = get_ollama_url()
            model_name = get_model_name()
            prompt = _build_rerank_prompt(query, candidates)

            payload = {
                "model": model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0,
                    "num_predict": 60,
                    "think": False,
                },
            }

            status_code, data, error_text = mcp_http_request(
                method="POST",
                url=f"{ollama_url}/api/generate",
                json_body=payload,
                timeout=RERANK_TIMEOUT,
            )

            elapsed = time.time() - t_start

            if status_code != 200 or not data:
                last_error = f"status={status_code}, elapsed={elapsed:.1f}s"
                logger.warning(
                    f"[Reranker] LLM 호출 실패 (시도 {attempt + 1}/{1 + RERANK_MAX_RETRIES}, {last_error})"
                )
                continue

            response_text = data.get("response", "") if isinstance(data, dict) else ""
            scores = _parse_scores(response_text, len(candidates))

            if not scores or len(scores) != len(candidates):
                last_error = f"파싱실패, 응답=\"{response_text[:100]}\""
                logger.warning(
                    f"[Reranker] 점수 파싱 실패 (시도 {attempt + 1}/{1 + RERANK_MAX_RETRIES}, "
                    f"{elapsed:.1f}s, {last_error})"
                )
                scores = []
                if attempt < RERANK_MAX_RETRIES:
                    payload["options"]["temperature"] = 0.3
                continue

            break  # 성공

        except Exception as e:
            elapsed = time.time() - t_start
            last_error = str(e)
            logger.warning(
                f"[Reranker] 예외 (시도 {attempt + 1}/{1 + RERANK_MAX_RETRIES}, {elapsed:.1f}s): {e}"
            )
            scores = []
            continue

    elapsed = time.time() - t_start

    # 모든 시도 실패 → 거리 기반 상위 결과를 폴백으로 반환
    if not scores:
        fallback = candidates[:top_k]
        logger.warning(
            f"[Reranker] 모든 시도 실패 ({elapsed:.1f}s, 마지막: {last_error}) "
            f"→ 거리 기반 상위 {len(fallback)}건 폴백 반환"
        )
        return fallback

    # 점수 기반 재정렬 (높은 점수 우선)
    scored_results = list(zip(scores, candidates))
    scored_results.sort(key=lambda x: x[0], reverse=True)

    # 최소 점수 임계값 필터링
    filtered = [(score, item) for score, item in scored_results if score >= RERANK_MIN_SCORE]

    max_score = max(scores) if scores else 0
    min_score = min(scores) if scores else 0
    removed_count = len(scored_results) - len(filtered)
    score_log = ", ".join(f"문서{i}={s}점" for i, s in enumerate(scores))

    logger.info(
        f"[Reranker] 재정렬 완료 ({elapsed:.1f}s) "
        f"후보={len(scored_results)}건 → 임계값({RERANK_MIN_SCORE}점)필터 → {len(filtered)}건 "
        f"(제외={removed_count}건, 최고={max_score}점, 최저={min_score}점) "
        f"점수=[{score_log}]"
    )

    if not filtered:
        logger.info(
            f"[Reranker] 모든 결과가 임계값({RERANK_MIN_SCORE}점) 미달 → 빈 결과 반환"
        )
        return []

    reranked = [item for _, item in filtered[:top_k]]
    return reranked
