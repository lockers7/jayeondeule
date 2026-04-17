# ═══════════════════════════════════════════════════════════════
# LLM 문서 요약 및 QA 쌍 생성: enriched 데이터를 VectorDB에 저장.
# --->
# _call_llm: call llm
# _generate_summary: generate summary
# _parse_qa_response: parse qa response
# _generate_qa_pairs: generate qa pairs
# _store_enriched_data: store enriched data
# enrich_document: enrich document
# ═══════════════════════════════════════════════════════════════
import os
import re
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import get_ollama_url, get_model_name

logger = setup_logger(__name__)

# Enrichment 설정
ENRICHMENT_TIMEOUT_SUMMARY = int(os.getenv("ENRICHMENT_TIMEOUT_SUMMARY", "180"))
ENRICHMENT_TIMEOUT_QA = int(os.getenv("ENRICHMENT_TIMEOUT_QA", "180"))
ENRICHMENT_MAX_INPUT_CHARS = int(os.getenv("ENRICHMENT_MAX_INPUT_CHARS", "5000"))
ENRICHMENT_MAX_QA_PAIRS = int(os.getenv("ENRICHMENT_MAX_QA_PAIRS", "5"))

from agri_ai_core.src.ai.rag.constants import DOC_TYPE_LABELS as _DOC_TYPE_LABELS
from agri_ai_core.src.utils.json_utils import safe_json_load


# ═════════════════════════════════════════════════════════════════════════
# Ollama /api/generate 호출 공통 함수. 응답 텍스트 반환, 실패 시 빈 문자열.
# ═════════════════════════════════════════════════════════════════════════
def _call_llm(prompt: str, num_predict: int, timeout: int) -> str:
    from agri_ai_core.src.ai.mcp_client import mcp_http_request

    ollama_url = get_ollama_url()
    model_name = get_model_name()

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": num_predict,
        },
    }

    try:
        status_code, data, error_text = mcp_http_request(
            method="POST",
            url=f"{ollama_url}/api/generate",
            json_body=payload,
            timeout=timeout,
        )

        if status_code != 200 or not data:
            logger.warning(
                f"[Enrichment] LLM 호출 실패: status={status_code}, "
                f"error={error_text[:200] if error_text else 'N/A'}"
            )
            return ""

        response_text = data.get("response", "") if isinstance(data, dict) else ""
        return response_text.strip()

    except Exception as e:
        logger.warning(f"[Enrichment] LLM 호출 예외: {e}")
        return ""


# ══════════════════════════════════════════════════════
# 문서 요약 생성 (LLM 호출 1회). 실패 시 빈 문자열 반환.
# ══════════════════════════════════════════════════════
def _generate_summary(
    text_for_llm: str,
    document_type: Optional[str] = None,
    crop_name: Optional[str] = None,
) -> str:
    doc_type_label = _DOC_TYPE_LABELS.get(document_type or "", "일반 문서")
    crop_line = f"관련 작물: {crop_name}\n" if crop_name else ""

    prompt = (
        f"/no_think\n"
        f"당신은 농업 전문 AI입니다. 아래 문서의 핵심 내용을 한국어로 요약하세요.\n\n"
        f"문서 유형: {doc_type_label}\n"
        f"{crop_line}\n"
        f"[요약 규칙]\n"
        f"1. 핵심 정보만 추출하여 300~500자로 요약\n"
        f"2. 작물 재배 조건, 병해충 정보, 관리 방법 등 실용적 정보 우선\n"
        f"3. 수치(온도, 습도, 기간 등) 구체적 데이터는 반드시 포함\n"
        f"4. 불필요한 서론/결론 생략\n\n"
        f"[문서 내용]\n{text_for_llm}\n\n"
        f"[요약]"
    )

    t_start = time.time()
    summary = _call_llm(prompt, num_predict=1024, timeout=ENRICHMENT_TIMEOUT_SUMMARY)
    elapsed = time.time() - t_start

    if summary:
        logger.info(f"[Enrichment] 요약 생성 완료 ({elapsed:.1f}s, {len(summary)}자)")
    else:
        logger.warning(f"[Enrichment] 요약 생성 실패 ({elapsed:.1f}s)")

    return summary


# ═════════════════════════════════════
# LLM 응답에서 QA JSON 배열을 파싱한다.
# ═════════════════════════════════════
def _parse_qa_response(response_text: str) -> List[Dict[str, str]]:
    if not response_text:
        return []

    # JSON 배열 패턴 매칭
    array_match = re.search(r'\[.*\]', response_text, re.DOTALL)
    if array_match:
        qa_list = safe_json_load(array_match.group())
        if isinstance(qa_list, list):
            valid = []
            for item in qa_list:
                if (
                    isinstance(item, dict)
                    and "question" in item
                    and "answer" in item
                    and str(item["question"]).strip()
                    and str(item["answer"]).strip()
                ):
                    valid.append({
                        "question": str(item["question"]).strip(),
                        "answer": str(item["answer"]).strip(),
                    })
            return valid[:ENRICHMENT_MAX_QA_PAIRS]

    logger.warning(f"[Enrichment] QA 파싱 실패: 응답={response_text[:200]}")
    return []


# ═══════════════════════════════════════════════════════
# 핵심 QA 쌍 생성 (LLM 호출 1회). 실패 시 빈 리스트 반환.
# ═══════════════════════════════════════════════════════
def _generate_qa_pairs(
    text_for_llm: str,
    document_type: Optional[str] = None,
    crop_name: Optional[str] = None,
) -> List[Dict[str, str]]:
    doc_type_label = _DOC_TYPE_LABELS.get(document_type or "", "일반 문서")
    crop_line = f"관련 작물: {crop_name}\n" if crop_name else ""

    prompt = (
        f"/no_think\n"
        f"당신은 농업 전문 AI입니다. 아래 문서를 바탕으로 "
        f"농업인이 자주 물을 수 있는 질문과 답변 쌍을 3~5개 생성하세요.\n\n"
        f"문서 유형: {doc_type_label}\n"
        f"{crop_line}\n"
        f"[QA 생성 규칙]\n"
        f"1. 실제 농업인이 궁금해할 실용적 질문 위주\n"
        f"2. 답변에 구체적 수치/조건을 포함\n"
        f"3. 질문과 답변 모두 한국어로 작성\n"
        f"4. JSON 배열 형식으로만 출력\n\n"
        f"[문서 내용]\n{text_for_llm}\n\n"
        f'아래 JSON 형식으로만 출력하세요:\n'
        f'[{{"question": "질문1", "answer": "답변1"}}, '
        f'{{"question": "질문2", "answer": "답변2"}}]'
    )

    t_start = time.time()
    response = _call_llm(prompt, num_predict=2048, timeout=ENRICHMENT_TIMEOUT_QA)
    elapsed = time.time() - t_start

    qa_pairs = _parse_qa_response(response)

    if qa_pairs:
        logger.info(f"[Enrichment] QA 생성 완료 ({elapsed:.1f}s, {len(qa_pairs)}쌍)")
    else:
        logger.warning(f"[Enrichment] QA 생성 실패 ({elapsed:.1f}s)")

    return qa_pairs


# ═════════════════════════════════════════════════════════
# 요약 및 QA 데이터를 임베딩하여 farm_knowledge에 저장한다.
# ═════════════════════════════════════════════════════════
def _store_enriched_data(
    summary: str,
    qa_pairs: List[Dict[str, str]],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    from agri_ai_core.src.ai.embedder import embed_text
    from agri_ai_core.src.chroma.collections import farm_knowledge_collection
    from agri_ai_core.src.chroma.operations import upsert_documents_with_embedding

    result = {"summary_stored": False, "qa_stored_count": 0}
    file_name = metadata.get("file_name", "unknown")
    file_name_base = file_name.replace(".", "_")

    batch_docs = []

    # 요약 저장 준비
    if summary:
        summary_embedding = embed_text(summary)
        if summary_embedding:
            enriched_meta = metadata.copy()
            enriched_meta.update({
                "data_type": "document_summary",
                "data_kind": "document_summary",
                "is_llm_enriched": True,
                "enrichment_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            batch_docs.append({
                "doc_id": f"summary_{file_name_base}",
                "text": summary,
                "metadata": enriched_meta,
                "embedding": summary_embedding,
            })

    # QA 쌍 저장 준비
    for i, qa in enumerate(qa_pairs):
        qa_text = f"질문: {qa['question']}\n답변: {qa['answer']}"
        qa_embedding = embed_text(qa_text)
        if qa_embedding:
            qa_meta = metadata.copy()
            qa_meta.update({
                "data_type": "document_qa",
                "data_kind": "document_qa",
                "is_llm_enriched": True,
                "qa_index": i,
                "enrichment_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            batch_docs.append({
                "doc_id": f"qa_{file_name_base}_{i}",
                "text": qa_text,
                "metadata": qa_meta,
                "embedding": qa_embedding,
            })

    if not batch_docs:
        logger.warning("[Enrichment] 저장할 enriched 데이터 없음")
        return result

    # 배치 저장
    try:
        collection_name = farm_knowledge_collection()
        store_result = upsert_documents_with_embedding(collection_name, batch_docs)

        if isinstance(store_result, dict) and store_result.get("success"):
            stored_count = store_result.get("count", len(batch_docs))
            result["summary_stored"] = bool(summary)
            result["qa_stored_count"] = len(qa_pairs)
            logger.info(
                f"[Enrichment] 저장 완료: {stored_count}건 "
                f"(요약={'O' if summary else 'X'}, QA={len(qa_pairs)}쌍)"
            )
        else:
            error = store_result.get("error", "알 수 없는 오류") if isinstance(store_result, dict) else str(store_result)
            logger.warning(f"[Enrichment] 저장 실패: {error}")

    except Exception as e:
        logger.warning(f"[Enrichment] 저장 예외: {e}")

    return result


# ══════════════════════════════════════════════════════════════
# 문서를 LLM이 이해/요약하여 enriched 데이터를 생성 및 저장한다.
# - 전체 요약 1건 생성 (LLM 호출 1회)
# ══════════════════════════════════════════════════════════════
def enrich_document(
    document_content: str,
    metadata: Dict[str, Any],
    document_type: Optional[str] = None,
    crop_name: Optional[str] = None,
) -> Dict[str, Any]:
    result = {
        "success": False,
        "summary_stored": False,
        "qa_pairs_generated": 0,
        "error": None,
    }

    if not document_content or not document_content.strip():
        result["error"] = "문서 내용이 비어있음"
        return result

    t_start = time.time()
    file_name = metadata.get("file_name", "unknown")

    # 입력 텍스트 길이 제한
    text_for_llm = document_content[:ENRICHMENT_MAX_INPUT_CHARS]
    if len(document_content) > ENRICHMENT_MAX_INPUT_CHARS:
        logger.info(
            f"[Enrichment] 입력 길이 제한: {len(document_content)} → {ENRICHMENT_MAX_INPUT_CHARS}자 ({file_name})"
        )

    # 1. 요약 생성
    summary = _generate_summary(text_for_llm, document_type, crop_name)

    # 2. QA 쌍 생성 (요약 실패와 독립적으로 실행)
    qa_pairs = _generate_qa_pairs(text_for_llm, document_type, crop_name)

    # 3. 저장
    if summary or qa_pairs:
        store_result = _store_enriched_data(summary, qa_pairs, metadata)
        result["summary_stored"] = store_result.get("summary_stored", False)
        result["qa_pairs_generated"] = store_result.get("qa_stored_count", 0)
        result["success"] = result["summary_stored"] or result["qa_pairs_generated"] > 0
    else:
        result["error"] = "요약 및 QA 생성 모두 실패"

    elapsed = time.time() - t_start
    logger.info(
        f"[Enrichment] 전체 완료 ({elapsed:.1f}s, {file_name}) "
        f"요약={'O' if result['summary_stored'] else 'X'}, "
        f"QA={result['qa_pairs_generated']}쌍, "
        f"성공={result['success']}"
    )

    return result
