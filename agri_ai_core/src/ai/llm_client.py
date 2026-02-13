# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 클라이언트 핵심 모듈
# OpenAI, Anthropic 등 다양한 LLM API와 통신하며,
# 프롬프트 전송, 응답 수신, 스트리밍 처리 등을 담당합니다.
# --->
# _get_available_models: Ollama에서 사용 가능한 모델 목록 가져오기
# _get_model_name: 환경 설정에서 모델명을 가져오거나 기본값을 반환
# _perform_llm_warmup: LLM 워밍업 수행
# initialize_background_warmup: 백그라운드 워밍업 초기화
# get_llm_response: LLM 응답 생성 (기존)
# get_llm_response_with_tools: Tool Use 지원 LLM 응답 생성 (신규)
# get_llm_streaming_response: LLM 스트리밍 응답 생성
# clean_streaming_chunk: 스트리밍 청크 정리
# filter_llm_response: LLM 응답 필터링
# clean_llm_response: LLM 응답 정리
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import re
import time
import json
import ollama
import threading
import traceback

from agri_ai_core.src.logs import setup_logger
from agri_ai_core.config import settings
from agri_ai_core.config import NUM_PREDICT

logger = setup_logger(__name__)

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 워밍업 관련 전역 변수
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
_warmup_lock = threading.Lock()
_warmup_started = False
_llm_warmed = False

# 모델 캐싱
_cached_model_name = None
_model_cache_lock = threading.Lock()

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
        result = ollama.list()
        # ollama 패키지 v0.4+ : ListResponse 객체 (result.models[].model)
        # ollama 패키지 v0.3- : dict (result['models'][].name)
        if hasattr(result, 'models'):
            return [m.model for m in result.models]
        elif isinstance(result, dict):
            return [m['name'] for m in result.get('models', [])]
        return []
    except Exception as e:
        logger.warning(f"Ollama 모델 목록 조회 실패: {e}")
        return []


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 환경 설정에서 모델명을 가져오거나 기본값을 반환
# 설정된 모델이 없으면 자동으로 폴백
# 캐싱을 통해 매번 모델 목록 조회를 방지
# --->
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _get_model_name() -> str:
    global _cached_model_name

    # 캐시된 모델 이름이 있으면 바로 반환
    with _model_cache_lock:
        if _cached_model_name:
            return _cached_model_name

    preferred_model = getattr(settings.model, "name", None) or "qwen3:14b"
    fallback_model = "qwen3:latest"

    # 사용 가능한 모델 목록 조회
    available_models = _get_available_models()

    # 선호 모델이 있는지 확인
    if preferred_model in available_models:
        logger.debug(f"사용 중인 모델: {preferred_model}")
        with _model_cache_lock:
            _cached_model_name = preferred_model
        return preferred_model

    # 선호 모델이 없으면 폴백 모델 확인
    if fallback_model in available_models:
        logger.warning(f"선호 모델 '{preferred_model}'을 찾을 수 없어 '{fallback_model}' 사용")
        with _model_cache_lock:
            _cached_model_name = fallback_model
        return fallback_model

    # 둘 다 없으면 선호 모델 반환 (Ollama가 자동 다운로드 시도)
    logger.info(f"모델 '{preferred_model}'을 사용합니다 (필요시 자동 다운로드)")
    with _model_cache_lock:
        _cached_model_name = preferred_model
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
                    options=options_payload,
                    keep_alive='1h'  # 모델을 1시간 동안 메모리에 유지
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
            keep_alive='1h',  # 모델을 1시간 동안 메모리에 유지
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
# 생각 과정 패턴 감지 (공통 헬퍼 함수)
# 텍스트가 LLM의 생각 과정인지 판단
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _is_thinking_text(text):
    """
    텍스트가 LLM의 생각 과정인지 판단하는 공통 헬퍼 함수

    Args:
        text: 검사할 텍스트

    Returns:
        bool: 생각 과정이면 True
    """
    if not text or not text.strip():
        return False

    # 한글이 포함되어 있으면 생각 과정이 아님
    has_korean = any(char in text for char in '가나다라마바사아자차카타파하')
    if has_korean:
        return False

    text_lower = text.strip().lower()

    # 생각 과정 시작 패턴
    thinking_starts = [
        'okay,', 'well,', 'so,', 'now,',
        'let me', 'let\'s', 'first,', 'hmm,', 'wait,',
        'i need to', 'i should', 'i\'ll', 'i will'
    ]

    # 생각 과정 키워드
    thinking_keywords = [
        'user said', 'user is asking', 'user provided', 'user wants',
        'user mentioned', 'user asked', 'user needs', 'user has',
        'the user', 'need to', 'should', 'looking at', 'based on',
        'let me think', 'let\'s see', 'figure out', 'understand'
    ]

    # 시작 패턴 체크
    starts_with_thinking = any(text_lower.startswith(pattern) for pattern in thinking_starts)

    # 키워드 체크
    has_thinking_keyword = any(keyword in text_lower for keyword in thinking_keywords)

    return starts_with_thinking and has_thinking_keyword


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 생각 과정 정규식 패턴 (공통)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
_THINKING_PATTERNS = [
    r'^(Okay|Well|So|Now),?\s+.*?(user said|need to|should|I need|I should)',
    r'^(Okay|Well|So|Now),?\s+(let\'s see|let me)',
    r'^Let (me|\'s)\s+(think|see|check|figure|understand)',
    r'^(First|Hmm|Wait),?\s+(I|let|the)',
    r'^I (need to|should|will|\'ll)\s+',
    r'^The user (is|provided|asked|wants|mentioned|has|said)',
    r'^Looking at (this|the|what)',
    r'^Based on (this|the|what)',
    # 데이터 검증/확인 패턴 (사용자 요청 추가)
    r'^Double-check\s+',
    r'^Checking\s+(if|the|that)',
    r'^Verify\s+(if|the|that)',
    r'^\w+\s+\d+(\.\d+)?\s*(°C|°F|%|ppm)\s+(is|are)\s+(okay|good|fine|normal|comfortable|acceptable)',
    r'^(Temperature|Humidity|CO2|Pressure|Level)\s+\d+',
    r'^Relays?:\s+',
    r'^So\s+(the|this|it)\s+(system|environment|condition)',
    r'^No\s+(immediate\s+)?action\s+(needed|required)',
]


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 스트리밍 청크 정리
# 스트리밍 청크에서 불필요한 내용 제거
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def clean_streaming_chunk(chunk):
    if not chunk:
        return chunk

    # Think 태그 제거
    if '<think>' in chunk.lower() or '</think>' in chunk.lower():
        logger.debug(f"[필터] Think 태그 청크 제거: {chunk[:100]}...")
        return ''

    # 생각 과정 패턴 감지 (공통 헬퍼 사용)
    if _is_thinking_text(chunk):
        logger.debug(f"[필터] 생각 과정 청크 제거: {chunk[:100]}...")
        return ''

    # 마크다운 헤더 제거
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
        # 생각 과정 라인 제거 (공통 패턴 사용)
        lines = filtered_text.split('\n')
        cleaned_lines = []
        removed_count = 0

        for line in lines:
            line_stripped = line.strip()
            has_korean = any(char in line for char in '가나다라마바사아자차카타파하')

            # 한글이 포함되어 있으면 생각 과정이 아님
            if has_korean:
                cleaned_lines.append(line)
                continue

            # 생각 과정 패턴 체크 (정규식 사용)
            is_thinking = False
            for pattern in _THINKING_PATTERNS:
                if re.match(pattern, line_stripped, re.IGNORECASE):
                    is_thinking = True
                    removed_count += 1
                    if removed_count <= 3:  # 처음 3개만 로깅
                        logger.debug(f"[필터] 생각 과정 제거: {line_stripped[:80]}...")
                    break

            if not is_thinking:
                cleaned_lines.append(line)

        if removed_count > 0:
            logger.info(f"[필터] 생각 과정 라인 {removed_count}개 제거")

        filtered_text = '\n'.join(cleaned_lines)

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
    filtered_text = re.sub(r'\n\s*\n\s*\n', '\n\n', filtered_text)
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
        elif removal_ratio > 0.1:
            removed_chars = original_length - final_length
            logger.info(f"[필터] 응답 필터링: {removed_chars}자 제거 ({original_length} → {final_length})")

    return filtered_text


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 응답 정리
# LLM 응답에서 불필요한 내용 제거
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def clean_llm_response(response_text):
    if not response_text:
        return response_text

    original_text = response_text
    removed_lines = []
    has_korean_any = any(char in response_text for char in '가나다라마바사아자차카타파하')

    # Think 태그 제거
    response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL | re.IGNORECASE)
    response_text = re.sub(r'</?think[^>]*>', '', response_text, flags=re.IGNORECASE)
    response_text = re.sub(r'<meta[^>]*>', '', response_text, flags=re.IGNORECASE)

    lines = response_text.split('\n')
    cleaned_lines = []

    meta_reasoning_keywords = [
        "user", "tools", "tool", "respond", "response", "answer", "final answer",
        "language", "markdown", "check if", "make sure", "keep it", "need to",
        "i need to", "i should", "let me", "let's", "reasoning", "analysis",
        "the user said", "might be asking", "direct query", "call any tools",
        "tools are for", "statement, not a question", "as the ai",
    ]
    meta_reasoning_starts = [
        "check if", "make sure", "keep it", "need to", "i need to", "i should",
        "let me", "let's", "respond", "answer", "use the", "given", "since",
        "okay,", "wait,", "well,", "so,", "now,",
    ]

    for line in lines:
        line_stripped = line.strip()
        has_korean = any(char in line for char in '가나다라마바사아자차카타파하')

        # 생각 과정 패턴 체크 (공통 패턴 사용)
        is_thinking = False
        if not has_korean:
            for pattern in _THINKING_PATTERNS:
                if re.match(pattern, line_stripped, re.IGNORECASE):
                    is_thinking = True
                    removed_lines.append(line_stripped[:100])
                    break

        # 한글이 섞여 있어도 영문 메타 추론(독백) 문장 제거
        if not is_thinking and has_korean_any and line_stripped:
            lower_line = line_stripped.lower()
            has_meta_keyword = any(keyword in lower_line for keyword in meta_reasoning_keywords)
            starts_as_meta = any(lower_line.startswith(prefix) for prefix in meta_reasoning_starts)
            ascii_alpha_count = sum(1 for c in line_stripped if c.isascii() and c.isalpha())
            non_space_count = sum(1 for c in line_stripped if not c.isspace())
            ascii_ratio = (ascii_alpha_count / non_space_count) if non_space_count else 0.0

            # 영문 비중이 높고(독백 패턴) 메타 키워드/시작 패턴에 해당하면 제거
            if has_meta_keyword and (starts_as_meta or ascii_ratio >= 0.20):
                is_thinking = True
                removed_lines.append(line_stripped[:100])

        if not is_thinking:
            cleaned_lines.append(line)

    # 제거된 라인 로깅
    if removed_lines:
        logger.debug(f"[필터] 생각 과정 라인 {len(removed_lines)}개 제거:")
        for removed in removed_lines[:5]:  # 최대 5개만 로깅
            logger.debug(f"  - {removed}...")
        if len(removed_lines) > 5:
            logger.debug(f"  ... 외 {len(removed_lines) - 5}개")

    response_text = '\n'.join(cleaned_lines)
    response_text = re.sub(r'\n\s*\n\s*\n', '\n\n', response_text)
    response_text = re.sub(r'[ \t]+', ' ', response_text)
    response_text = response_text.strip()

    # 추가 필터링: 마침표로 구분된 짧은 영문 검증/판단 문장 제거
    # (사용자 요청: "Double-check the numbers. Temperature 25.3°C is comfortable..." 같은 패턴)
    if has_korean_any:
        # 한글이 포함된 응답에서 영문 검증 문장만 제거
        sentence_removed_count = 0
        for line in response_text.split('\n'):
            if any(char in line for char in '가나다라마바사아자차카타파하'):
                continue  # 한글이 있는 줄은 건너뜀

            # 마침표로 분리된 문장들 검사
            sentences = [s.strip() for s in line.split('.') if s.strip()]
            filtered_sentences = []

            for sentence in sentences:
                # 짧은 영문 검증/판단 문장인지 확인
                is_verification = False
                if len(sentence) < 200 and not any(char in sentence for char in '가나다라마바사아자차카타파하'):
                    for pattern in _THINKING_PATTERNS:
                        if re.match(pattern, sentence.strip(), re.IGNORECASE):
                            is_verification = True
                            sentence_removed_count += 1
                            break

                if not is_verification:
                    filtered_sentences.append(sentence)

            # 문장들을 다시 조립
            if filtered_sentences:
                new_line = '. '.join(filtered_sentences)
                if new_line and not new_line.endswith('.'):
                    new_line += '.'
                response_text = response_text.replace(line, new_line)
            else:
                response_text = response_text.replace(line, '')

        if sentence_removed_count > 0:
            logger.debug(f"[필터] 검증/판단 문장 {sentence_removed_count}개 추가 제거")

    response_text = re.sub(r'\n\s*\n\s*\n', '\n\n', response_text)
    response_text = response_text.strip()

    # 필터링 결과 요약 로깅
    if len(original_text) > len(response_text):
        removed_chars = len(original_text) - len(response_text)
        logger.info(f"[필터] LLM 응답 정리: {removed_chars}자 제거 ({len(original_text)} → {len(response_text)})")

    return response_text


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Tool Use 지원 LLM 응답 생성
# Ollama Function Calling을 사용하여 도구를 자동으로 선택하고 실행
#
# Args:
#     user_query: 사용자 질문
#     farm_name: 농장명
#     temperature: 창의성 정도
#     max_tool_iterations: 최대 도구 호출 반복 횟수
#
# Returns:
#     str: 최종 응답 텍스트
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_llm_response_with_tools(user_query: str, farm_name: str = None,
                                 temperature: float = 0.7, max_tool_iterations: int = 5) -> str:
    """
    Tool Use를 지원하는 LLM 응답 생성
    LLM이 필요한 도구를 자동으로 선택하고 호출하여 최종 답변 생성

    Args:
        user_query: 사용자 질문
        farm_name: 농장명
        temperature: 창의성 정도
        max_tool_iterations: 최대 도구 호출 반복 횟수

    Returns:
        str: 최종 응답
    """
    try:
        from agri_ai_core.src.ai.tools_definition import get_available_tools, get_system_prompt_with_tools
        from agri_ai_core.src.ai.tools_executor import execute_tool

        model_name = _get_model_name()
        tools = get_available_tools()
        system_prompt = get_system_prompt_with_tools(farm_name)

        # 메시지 히스토리
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query}
        ]

        logger.info(f"[Tool Use] 질문: {user_query[:100]}...")

        # 도구 호출 반복 (최대 max_tool_iterations회)
        for iteration in range(max_tool_iterations):
            logger.info(f"[Tool Use] Iteration {iteration + 1}/{max_tool_iterations}")

            # LLM 호출 (도구 포함)
            response = ollama.chat(
                model=model_name,
                messages=messages,
                tools=tools,
                options={
                    "temperature": temperature,
                    "top_p": 0.9,
                    "top_k": 40,
                    "num_predict": NUM_PREDICT
                },
                keep_alive='1h'
            )

            # 응답에서 메시지 추출
            if hasattr(response, 'message'):
                assistant_message = response.message
            elif isinstance(response, dict) and 'message' in response:
                assistant_message = response['message']
            else:
                logger.error("LLM 응답 형식 오류")
                return "죄송합니다. 응답을 생성할 수 없습니다."

            # 메시지 히스토리에 추가
            messages.append(assistant_message)

            # 도구 호출이 없으면 최종 답변 반환
            if not hasattr(assistant_message, 'tool_calls') or not assistant_message.tool_calls:
                final_answer = assistant_message.content if hasattr(assistant_message, 'content') else str(assistant_message)
                logger.info(f"[Tool Use] 최종 답변 생성 완료 ({iteration + 1}회 반복)")

                # 응답 필터링
                filtered_answer = filter_llm_response(final_answer, filter_type="general")
                return filtered_answer

            # 도구 호출 처리
            logger.info(f"[Tool Use] {len(assistant_message.tool_calls)}개 도구 호출")

            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = tool_call.function.arguments

                logger.info(f"[Tool Use] 실행: {tool_name}({tool_args})")

                # 도구 실행
                tool_result = execute_tool(tool_name, tool_args)

                # 도구 결과를 메시지에 추가
                messages.append({
                    "role": "tool",
                    "content": tool_result
                })

                logger.info(f"[Tool Use] {tool_name} 실행 완료")

        # 최대 반복 횟수 도달
        logger.warning(f"[Tool Use] 최대 반복 횟수({max_tool_iterations}) 도달")

        # 마지막 메시지가 assistant 메시지면 그것을 반환
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                return msg.get("content", "죄송합니다. 응답을 완료할 수 없습니다.")
            elif hasattr(msg, 'content') and hasattr(msg, 'role'):
                if msg.role == "assistant":
                    return msg.content

        return "죄송합니다. 응답을 생성할 수 없습니다."

    except Exception as e:
        logger.error(f"Tool Use LLM 응답 생성 중 오류: {e}")
        logger.error(traceback.format_exc())
        return f"죄송합니다. 응답 생성 중 오류가 발생했습니다: {str(e)}"
