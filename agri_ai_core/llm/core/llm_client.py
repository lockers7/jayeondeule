# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 클라이언트 핵심 모듈
# OpenAI, Anthropic 등 다양한 LLM API와 통신하며,
# 프롬프트 전송, 응답 수신, 스트리밍 처리 등을 담당합니다.
# --->
# _get_available_models: Ollama에서 사용 가능한 모델 목록 가져오기
# _get_model_name: 환경 설정에서 모델명을 가져오거나 기본값을 반환
# _perform_llm_warmup: LLM 워밍업 수행
# initialize_background_warmup: 백그라운드 워밍업 초기화
# get_llm_response: LLM 응답 생성
# get_llm_streaming_response: LLM 스트리밍 응답 생성
# clean_streaming_chunk: 스트리밍 청크 정리
# filter_llm_response: LLM 응답 필터링
# clean_llm_response: LLM 응답 정리
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import re
import time
import ollama
import threading
import traceback

from agri_ai_core.log_utils.log_handlers import setup_logger
from agri_ai_core.shared_modules.config.settings import settings
from agri_ai_core.shared_modules.common.constants import NUM_PREDICT

logger = setup_logger(__name__)

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 워밍업 관련 전역 변수
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
_warmup_lock = threading.Lock()
_warmup_started = False
_llm_warmed = False

# 환경 변수 설정
os.environ['OLLAMA_MAX_LOADED_MODELS'] = '1'
os.environ['OLLAMA_NUM_PARALLEL'] = '2'
os.environ['OLLAMA_KEEP_ALIVE'] = '1h'


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Ollama에서 사용 가능한 모델 목록 가져오기
# --->
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _get_available_models():
    try:
        models = ollama.list()
        return [model['name'] for model in models.get('models', [])]
    except Exception as e:
        logger.warning(f"Ollama 모델 목록 조회 실패: {e}")
        return []


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 환경 설정에서 모델명을 가져오거나 기본값을 반환
# 설정된 모델이 없으면 자동으로 폴백
# --->
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _get_model_name() -> str:
    preferred_model = getattr(settings.model, "name", None) or "qwen3:14b"
    fallback_model = "qwen3:latest"

    # 사용 가능한 모델 목록 조회
    available_models = _get_available_models()

    # 선호 모델이 있는지 확인
    if preferred_model in available_models:
        logger.debug(f"사용 중인 모델: {preferred_model}")
        return preferred_model

    # 선호 모델이 없으면 폴백 모델 확인
    if fallback_model in available_models:
        logger.warning(f"선호 모델 '{preferred_model}'을 찾을 수 없어 '{fallback_model}' 사용")
        return fallback_model

    # 둘 다 없으면 선호 모델 반환 (Ollama가 자동 다운로드 시도)
    logger.info(f"모델 '{preferred_model}'을 사용합니다 (필요시 자동 다운로드)")
    return preferred_model


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 워밍업
# LLM 워밍업 수행
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _perform_llm_warmup():
    global _llm_warmed
    if _llm_warmed:
        return

    try:
        model_name = _get_model_name()
        ollama.chat(
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
        logger.info("LLM warm-up completed.")
    except Exception as warm_err:
        logger.warning(f"LLM warm-up failed: {warm_err}")


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 백그라운드 워밍업 초기화
# 백그라운드 워밍업 초기화
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def initialize_background_warmup(farm_id=None, house_id=None, farm_name=None, house_name=None):
    global _warmup_started
    with _warmup_lock:
        if _warmup_started:
            return
        _warmup_started = True

    def _warmup_runner():
        _perform_llm_warmup()

    threading.Thread(target=_warmup_runner, daemon=True).start()


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 응답 생성
# LLM 응답 생성
#
# Args:
#     system_prompt: 시스템 프롬프트
#     user_prompt: 사용자 프롬프트
#     temperature: 창의성 정도 (0=결정적, 1=창의적)
#     top_p: 누적 확률 기반 샘플링
#     top_k: 상위 K개 단어 중 선택
#     num_predict: 최대 출력 토큰 수
#     query_type: 질의 유형
#     llm_options: LLM 옵션 딕셔너리
#
# Returns:
#     str: LLM 응답 텍스트
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_llm_response(system_prompt=None, user_prompt=None, temperature=0.7,
                     top_p=0.9, top_k=40, num_predict=NUM_PREDICT,
                     query_type=None, llm_options=None):
    try:
        max_retries = 2
        retry_count = 0
        model_name = _get_model_name()

        while retry_count <= max_retries:
            try:
                message_payload = []
                if system_prompt:
                    message_payload.append({"role": "system", "content": system_prompt})
                message_payload.append({"role": "user", "content": user_prompt})

                options_payload = llm_options or {
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "num_predict": num_predict
                }

                response = ollama.chat(
                    model=model_name,
                    messages=message_payload,
                    options=options_payload
                )
                break
            except Exception as retry_err:
                retry_count += 1
                if retry_count > max_retries:
                    raise retry_err
                logger.error(f"LLM 응답 생성 중 오류, 재시도 {retry_count}/{max_retries}: {retry_err}")
                time.sleep(1)

        if hasattr(response, 'message') and hasattr(response.message, 'content'):
            response_text = response.message.content
        elif isinstance(response, dict) and "response" in response:
            response_text = response["response"]
        else:
            response_text = "응답을 생성할 수 없습니다."

        if not response_text or len(response_text.strip()) == 0:
            logger.error("빈 응답 텍스트")
            response_text = "LLM이 빈 응답을 반환했습니다."

        # 응답 필터링
        if query_type == "relay_llm_control":
            filtered_response = filter_llm_response(response_text, filter_type="relay_control")
        else:
            filtered_response = filter_llm_response(response_text, filter_type="general")

        return filtered_response

    except Exception as e:
        logger.error(f"LLM 응답 생성 중 오류: {e}")
        logger.error(traceback.format_exc())
        return "죄송합니다. 현재 응답을 생성할 수 없습니다."


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 스트리밍 응답 생성
# LLM 스트리밍 응답 생성
#
# Args:
#     prompt: 사용자 프롬프트
#     temperature: 창의성 정도
#     top_p: 누적 확률 기반 샘플링
#     top_k: 상위 K개 단어 중 선택
#     num_predict: 최대 출력 토큰 수
#
# Yields:
#     str: 응답 청크
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def get_llm_streaming_response(prompt, temperature=0.7, top_p=0.9,
                                      top_k=40, num_predict=NUM_PREDICT):
    try:
        buffer = ""
        inside_think_tag = False
        model_name = _get_model_name()

        for response_chunk in ollama.generate(
            model=model_name,
            prompt=prompt,
            stream=True,
            options={
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "num_predict": num_predict
            }
        ):
            chunk_text = response_chunk.get("response", "")
            if not chunk_text:
                continue

            buffer += chunk_text
            output_parts = []
            pos = 0

            while pos < len(buffer):
                lowered = buffer.lower()

                if inside_think_tag:
                    end_idx = lowered.find("</think>", pos)
                    if end_idx == -1:
                        buffer = buffer[pos:]
                        pos = len(buffer)
                        break

                    pos = end_idx + len("</think>")
                    inside_think_tag = False
                    continue

                start_idx = lowered.find("<think", pos)
                if start_idx == -1:
                    emit_candidate = buffer[pos:]
                    buffer = ""
                    if emit_candidate:
                        tail_candidate = emit_candidate[-6:]
                        tail_lower = tail_candidate.lower()
                        if tail_lower.startswith("<thi") or tail_lower.startswith("</thi"):
                            buffer = tail_candidate
                            emit_candidate = emit_candidate[:-len(tail_candidate)]
                    if emit_candidate:
                        output_parts.append(emit_candidate)
                    pos = len(buffer)
                    break

                output_parts.append(buffer[pos:start_idx])
                tag_close_idx = buffer.find(">", start_idx)
                if tag_close_idx == -1:
                    buffer = buffer[start_idx:]
                    pos = len(buffer)
                    inside_think_tag = True
                    break

                pos = tag_close_idx + 1
                inside_think_tag = True
                if pos >= len(buffer):
                    buffer = ""
                    break

            if output_parts:
                emit_text = ''.join(output_parts)
                filtered_chunk = clean_streaming_chunk(emit_text)
                if filtered_chunk:
                    yield filtered_chunk

        if buffer and not inside_think_tag:
            filtered_chunk = clean_streaming_chunk(buffer)
            if filtered_chunk:
                yield filtered_chunk

    except Exception as e:
        logger.error(f"LLM 스트리밍 응답 생성 중 오류: {e}")
        logger.error(traceback.format_exc())
        yield "죄송합니다. 현재 응답을 생성할 수 없습니다."


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 스트리밍 청크 정리
# 스트리밍 청크에서 불필요한 내용 제거
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def clean_streaming_chunk(chunk):
    if not chunk:
        return chunk

    if '<think>' in chunk.lower() or '</think>' in chunk.lower():
        return ''

    if (chunk.strip().lower().startswith(('okay', 'well', 'so', 'now')) and
        any(word in chunk.lower() for word in ['user said', 'need to', 'should', 'i need', 'i should']) and
        not any(char in chunk for char in '가나다라마바사아자차카타파하')):
        return ''

    chunk = re.sub(r"^(### )?(Final Answer|Response|Answer):?\s*", "", chunk, flags=re.IGNORECASE)

    return chunk


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 응답 필터링
# LLM 응답 필터링
#
# Args:
#     text: 응답 텍스트
#     filter_type: 필터 유형 ("general" 또는 "relay_control")
#     query_type: 질의 유형
#
# Returns:
#     str: 필터링된 텍스트
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def filter_llm_response(text, filter_type="general", query_type=None):
    if not text or len(text.strip()) == 0:
        return text

    original_length = len(text)
    filtered_text = text

    # 1. Think 태그 제거 (공통)
    try:
        filtered_text = re.sub(r"<think>.*?</think>\s*", "", filtered_text, flags=re.DOTALL | re.IGNORECASE)
        filtered_text = re.sub(r"<thinking>.*?</thinking>\s*", "", filtered_text, flags=re.DOTALL | re.IGNORECASE)
        filtered_text = re.sub(r"<think>.*", "", filtered_text, flags=re.DOTALL | re.IGNORECASE)
        filtered_text = re.sub(r"<thinking>.*", "", filtered_text, flags=re.DOTALL | re.IGNORECASE)
    except Exception as e:
        logger.warning(f"think 태그 제거 중 오류: {e}")

    # 2. 일반 필터링 (기본 타입에만 적용)
    if filter_type == "general":
        # 마크다운 헤더 제거
        markdown_headers_to_remove = [
            r"^(### )?Final Answer:?\s*",
            r"^(### )?Final Output:?\s*",
            r"^(### )?Response:?\s*",
            r"^(### )?Answer:?\s*",
            r"^(### )?결론:?\s*"
        ]
        for pattern in markdown_headers_to_remove:
            try:
                filtered_text = re.sub(pattern, "", filtered_text, flags=re.MULTILINE | re.IGNORECASE)
            except Exception as e:
                logger.warning(f"헤더 제거 중 오류: {e}")

        # 코드 블록 마커 제거
        try:
            filtered_text = re.sub(r"^```[a-zA-Z]*\s*$", "", filtered_text, flags=re.MULTILINE)
            filtered_text = re.sub(r"^```\s*$", "", filtered_text, flags=re.MULTILINE)
        except Exception as e:
            logger.warning(f"코드 블럭 마커 제거 중 오류: {e}")

    # 3. 기본 정리 (공통)
    filtered_text = filtered_text.strip()
    final_length = len(filtered_text)

    # 4. 일반 필터링 후 과도한 제거 검사
    if filter_type == "general" and original_length > 0:
        removal_ratio = (original_length - final_length) / original_length
        if removal_ratio > 0.9:
            logger.warning(f"필터링으로 인해 응답의 {removal_ratio*100:.1f}%가 제거됨")
            if final_length < 10:
                fallback_text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL | re.IGNORECASE)
                if len(fallback_text.strip()) > final_length:
                    filtered_text = fallback_text.strip()

    return filtered_text


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 응답 정리
# LLM 응답에서 불필요한 내용 제거
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def clean_llm_response(response_text):
    if not response_text:
        return response_text

    response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL | re.IGNORECASE)
    response_text = re.sub(r'</?think[^>]*>', '', response_text, flags=re.IGNORECASE)
    response_text = re.sub(r'<meta[^>]*>', '', response_text, flags=re.IGNORECASE)

    lines = response_text.split('\n')
    cleaned_lines = []

    for line in lines:
        if re.match(r'^(Okay|Well|So|Now),?\s+.*?(user said|need to|should|I need|I should)', line.strip(), re.IGNORECASE):
            continue

        if (line.strip().lower().startswith(('okay', 'well', 'so', 'now')) and
            any(phrase in line.lower() for phrase in ['user said', 'need to respond', 'should respond', 'i need to', 'i should']) and
            not any(char in line for char in '가나다라마바사아자차카타파하')):
            continue

        cleaned_lines.append(line)

    response_text = '\n'.join(cleaned_lines)
    response_text = re.sub(r'\n\s*\n\s*\n', '\n\n', response_text)
    response_text = re.sub(r'[ \t]+', ' ', response_text)
    response_text = response_text.strip()

    return response_text
