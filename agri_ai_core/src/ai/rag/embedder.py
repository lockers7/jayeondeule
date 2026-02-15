# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 텍스트 임베딩 생성 모듈
# 텍스트를 벡터로 변환하는 임베딩 모델을 관리하고,
# 배치 처리를 통해 효율적인 벡터화를 수행합니다.
# --->
# check_ollama_health: Ollama 서버 상태 확인
# get_dynamic_timeout: 텍스트 길이에 따른 동적 타임아웃 계산
# generate_dummy_embedding: 일관성 있는 더미 임베딩 생성
# embed_text: 텍스트를 임베딩 벡터로 변환
# reset_embedding_service: 임베딩 서비스 상태 초기화
# clear_embedding_cache: 임베딩 캐시 클리어
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import time
import hashlib
import logging
import numpy as np
from collections import OrderedDict
from typing import Any, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.mcp_client import mcp_http_request
from agri_ai_core.config import settings
from agri_ai_core.config import EMBEDDING_MODEL_NAME

logger = setup_logger(__name__)

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 임베딩 캐시 설정
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
_embedding_cache = OrderedDict()
_EMBEDDING_CACHE_MAX = 256
_EMBEDDING_SERVICE_DISABLED = False
_EMBEDDING_FAILURE_REASON = None


def _mcp_get_status(url: str, timeout: int = 5) -> Optional[int]:
    status_code, _, _ = mcp_http_request(
        method="GET",
        url=url,
        timeout=max(3, min(int(timeout), 10)),
    )
    return status_code if status_code > 0 else None


def _extract_embedding_from_payload(data: Any):
    if not isinstance(data, dict):
        return None

    embedding = data.get("embedding")

    if (not embedding) and isinstance(data.get("embeddings"), list) and data["embeddings"]:
        first = data["embeddings"][0]
        if isinstance(first, list):
            embedding = first

    if (not embedding) and isinstance(data.get("data"), list) and data["data"]:
        first = data["data"][0]
        if isinstance(first, dict) and isinstance(first.get("embedding"), list):
            embedding = first["embedding"]

    return embedding


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 환경설정 혹은 환경변수에서 Ollama URL을 반환
# --->
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _get_ollama_url() -> str:
    return (
        getattr(settings.model, "ollama_url", None)
        or os.getenv("OLLAMA_URL")
        or "http://localhost:11434"
    )


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 설정된 임베딩 차원(없으면 기본 768)을 반환
# --->
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _get_expected_dim() -> int:
    return getattr(settings, "embedding_dim", None) or 768


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Ollama 서버 상태 확인
# --->
# Ollama 서버 상태 확인
# Returns:
# bool: 서버 상태 정상 여부
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def check_ollama_health():
    ollama_url = _get_ollama_url()
    version_status = _mcp_get_status(ollama_url + "/api/version", timeout=5)
    if version_status != 200:
        return False
    tags_status = _mcp_get_status(ollama_url + "/api/tags", timeout=5)
    return tags_status == 200


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 텍스트 길이에 따른 동적 타임아웃 계산
# --->
# 텍스트 길이에 따른 동적 타임아웃 계산
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_dynamic_timeout(text_length, base_timeout=60):
    return min(180, max(base_timeout, 30 + (text_length // 100)))


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 일관성 있는 더미 임베딩 생성
# --->
# 일관성 있는 더미 임베딩 생성
# Args:
# text: 입력 텍스트
# Returns:
# list: 더미 임베딩 벡터
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def generate_dummy_embedding(text):
    try:
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        seed = int(text_hash[:8], 16)

        np.random.seed(seed)
        expected_dim = _get_expected_dim()
        dummy_embedding = np.random.normal(0, 0.1, expected_dim).tolist()

        logger.debug(f"[embed_text] 더미 임베딩 생성 완료 - 시드: {seed}, 차원: {expected_dim}")
        return dummy_embedding

    except Exception as fallback_error:
        logger.error(f"[embed_text] 더미 임베딩 생성도 실패: {fallback_error}")
        expected_dim = _get_expected_dim()
        return [0.0] * expected_dim


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 텍스트 임베딩 처리
# --->
# 텍스트를 임베딩 벡터로 변환
# Args:
# text: 입력 텍스트
# timeout: 요청 타임아웃 (초)
# max_retries: 최대 재시도 횟수
# Returns:
# list: 임베딩 벡터 또는 None
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def embed_text(text, timeout=60, max_retries=5):
    global _EMBEDDING_SERVICE_DISABLED, _EMBEDDING_FAILURE_REASON

    use_dummy = getattr(settings.model, 'use_dummy_embedding', False)
    if use_dummy:
        _EMBEDDING_SERVICE_DISABLED = True
        _EMBEDDING_FAILURE_REASON = "config_force_dummy"
        return generate_dummy_embedding(text)

    if not text or not isinstance(text, str):
        logger.warning("[embed_text] 빈 텍스트 또는 잘못된 입력")
        return None

    if _EMBEDDING_SERVICE_DISABLED:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"[embed_text] 임베딩 서비스 비활성화 상태 → 더미 임베딩 사용 (사유: {_EMBEDDING_FAILURE_REASON})")
        return generate_dummy_embedding(text)

    original_length = len(text)
    if len(text) > 4000:
        text = text[:4000] + "..."
        logger.debug(f"[embed_text] 텍스트 길이 제한 적용: {original_length} -> {len(text)} 문자")

    cache_key = text
    cached = _embedding_cache.get(cache_key)
    if cached is not None:
        logger.debug("[embed_text] 캐시된 임베딩 사용")
        _embedding_cache.move_to_end(cache_key)
        return cached

    if not check_ollama_health():
        logger.debug("[embed_text] Ollama 서버 상태 불량 - 더미 임베딩 생성")
        _EMBEDDING_SERVICE_DISABLED = True
        _EMBEDDING_FAILURE_REASON = "ollama_health_check_failed"
        return generate_dummy_embedding(text)

    dynamic_timeout = get_dynamic_timeout(len(text), timeout)
    logger.debug(f"[embed_text] 동적 타임아웃 설정: {dynamic_timeout}초 (텍스트 길이: {len(text)})")

    ollama_url = _get_ollama_url()
    embedding_model = (
        getattr(settings.model, "embedding_model", None)
        or os.getenv("EMBEDDING_MODEL_NAME")
        or EMBEDDING_MODEL_NAME
    )
    expected_dim = _get_expected_dim()

    logger.debug(f"embedding_model = {embedding_model}")

    payload = {
        "model": embedding_model,
        "input": text,
        "stream": False
    }

    last_error = None

    for attempt in range(max_retries):
        try:
            start_time = time.time()
            status_code, data, error_text = mcp_http_request(
                method="POST",
                url=ollama_url + "/api/embeddings",
                json_body=payload,
                timeout=int(dynamic_timeout),
            )
            elapsed_time = time.time() - start_time
            logger.debug(f"[embed_text] MCP 요청 완료 (시도 {attempt + 1}/{max_retries}): {elapsed_time:.2f}초")

            if status_code in (400, 404, 422):
                if not _EMBEDDING_SERVICE_DISABLED:
                    logger.debug(f"[embed_text] 임베딩 엔드포인트 {status_code} 응답 → 더미 임베딩 전환")
                _EMBEDDING_SERVICE_DISABLED = True
                _EMBEDDING_FAILURE_REASON = f"http_status_{status_code}"
                return generate_dummy_embedding(text)

            if status_code >= 500 or status_code == 0:
                last_error = f"HTTP 오류: {status_code} {error_text}"
                if attempt < max_retries - 1:
                    wait_time = min(30, 5 + (attempt * 3))
                    logger.debug(f"[embed_text] {wait_time}초 대기 후 재시도... (서버 오류)")
                    time.sleep(wait_time)
                    continue
                break

            embedding = _extract_embedding_from_payload(data)

            if embedding and isinstance(embedding, list) and len(embedding) > 0:
                if len(embedding) == expected_dim:
                    logger.debug(f"[embed_text] 임베딩 성공 - 크기: {len(embedding)}, 소요시간: {elapsed_time:.2f}초")
                    # 간단한 LRU 캐시 유지
                    _embedding_cache[cache_key] = embedding
                    _embedding_cache.move_to_end(cache_key)
                    if len(_embedding_cache) > _EMBEDDING_CACHE_MAX:
                        _embedding_cache.popitem(last=False)
                    return embedding
                else:
                    logger.warning(f"[embed_text] 임베딩 차원 불일치: {len(embedding)} != {expected_dim}")
                    last_error = f"차원 불일치: {len(embedding)} != {expected_dim}"
                    continue
            else:
                logger.debug(f"[embed_text] 임베딩 응답이 비어있음/스키마 불일치: {str(data)[:160]} → 더미 폴백")
                return generate_dummy_embedding(text)

        except Exception as e:
            logger.warning(f"[embed_text] 예외 발생 (시도 {attempt + 1}/{max_retries}): {e}")
            last_error = f"예외: {e}"

            if attempt < max_retries - 1:
                wait_time = min(15, 2 + attempt)
                logger.debug(f"[embed_text] {wait_time}초 대기 후 재시도... (일반 예외)")
                time.sleep(wait_time)
                continue

    _EMBEDDING_SERVICE_DISABLED = True
    _EMBEDDING_FAILURE_REASON = last_error
    logger.debug(f"[embed_text] 모든 재시도 실패 ({max_retries}회) → 더미 임베딩 반환")
    logger.debug(f"[embed_text] 마지막 오류: {last_error}")

    return generate_dummy_embedding(text)


