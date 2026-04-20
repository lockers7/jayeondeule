# ══════════════════════════════════════════════════════════════════════════════════════════
# LLM 클라이언트 핵심 모듈 — Ollama API 통신 및 Tool Use 응답 생성.
# --->
# _build_tool_detail_message: 도구 호출 시 사용자에게 보여줄 상세 정보 메시지 생성
# _report_progress: Tool Use 루프 내부에서 진행 상태를 외부(스트리밍 핸들러)로 보고합니다
# _get_model_gpu_ratio: Ollama /api/ps 에서 모델의 실제 GPU 탑재 비율을 조회 후 1
# _get_free_vram_mib: nvidia-smi로 현재 여유 VRAM(MiB) 반환
# _get_model_ctx_options: num_ctx 고정(16384) — GPU 100% 유지, CPU 오프로딩/모델 언로드 방지
# _use_mcp_fetch: use mcp fetch
# _use_ollama_package: use ollama package
# _use_direct_ollama_http: use direct ollama http
# _is_direct_ollama_enabled: is direct ollama enabled
# _disable_direct_ollama_http: disable direct ollama http
# _is_connection_related_error: is connection related error
# _extract_model_names: extract model names
# _pkg_ollama_list_models: pkg ollama list models
# _build_chat_payload: Ollama chat API용 공통 payload 빌드
# _pkg_ollama_chat: pkg ollama chat
# _build_ollama_url: build ollama url
# _direct_ollama_json: direct ollama json
# _direct_ollama_list_models: direct ollama list models
# _direct_ollama_chat: direct ollama chat
# _mcp_ollama_list_models: mcp ollama list models
# _mcp_ollama_chat: mcp ollama chat
# _serialize_for_log: serialize for log
# _log_llm_request_json: log llm request json
# _log_llm_response_json: log llm response json
# _ollama_chat: ollama chat
# _extract_message_content: extract message content
# _normalize_assistant_message: normalize assistant message
# _extract_tool_calls: extract tool calls
# _extract_tool_name: extract tool name
# _extract_tool_arguments: extract tool arguments
# _coerce_numeric_id: LLM이 비정수 값을 ID로 넣는 경우 기본값(정수)으로 교정한다
# _normalize_tool_arguments: normalize tool arguments
# _get_available_models: get available models
# _get_model_name: get model name
# _perform_llm_warmup: perform llm warmup
# initialize_background_warmup: initialize background warmup
# _emit_question_log_once: emit question log once
# _determine_response_type: determine response type
# _build_structured_result: build structured result
# _filter_greeting_turns: filter greeting turns
# _is_conversational_query: 요구/지시가 아닌 순수 일반 대화인지 판단한다
# _build_farm_info_text: build farm info text
# _execute_and_merge_tools: 도구 호출 실행, 결과 정제, 메시지 병합을 처리
# _check_answer_retry: LLM 답변을 검증하고, 재시도가 필요하면 재시도 메시지를 반환
# _build_conversation_context: 하이브리드 대화 컨텍스트를 messages 리스트에 주입
# get_llm_response_with_tools: get llm response with tools
# _pick: pick
# _resolve_admin_farm_id: 시스템관리자(세션=0)일 때 LLM 판단값으로 farm_id 결정
# _warmup_runner: warmup runner
# ══════════════════════════════════════════════════════════════════════════════════════════
import os
import re
import time
import json
import threading
import traceback
from typing import Any, Dict, List, Optional
from queue import Queue as ThreadQueue
from urllib import error as urlerror
from urllib import request as urlrequest

try:
    import ollama
except Exception:
    ollama = None

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import NUM_PREDICT, NUM_CTX, NUM_PREDICT_TOOL_CALL, get_ollama_url, get_model_name
from agri_ai_core.src.utils.validators import is_true
from agri_ai_core.src.utils.json_utils import safe_json_load
from agri_ai_core.src.ai.utils import GREETING_RE as _GREETING_RE
from agri_ai_core.src.ai.llm_response import (
    clean_llm_response,
    _clean_page_content,
    _refine_search_web,
    _refine_fetch_url,
    _refine_realtime_data,
    _refine_tool_result,
    _strip_nav_noise,
    _refine_farm_knowledge,
    _finalize_user_facing_answer,
    _align_markdown_tables,
    _strip_hallucinated_urls,
    _display_width,
    _pad_to_width,
)

logger = setup_logger(__name__)

# 도구 한국어 표시명 매핑
_TOOL_DISPLAY_NAMES = {
    "get_farm_realtime_data": "센서/릴레이 데이터 조회",
    "search_farm_knowledge": "농장 지식 검색",
    "search_web": "웹 검색",
    "fetch_url_content": "웹페이지 내용 수집",
    "control_relay": "장치 제어",
    "search_gas_price": "유가 정보 조회",
}


def _build_tool_detail_message(tool_name: str, tool_args: dict) -> str:
    """도구 호출 시 사용자에게 보여줄 상세 정보 메시지 생성."""
    if tool_name == "get_farm_realtime_data":
        house_id = tool_args.get("house_id", "")
        data_type = tool_args.get("data_type", "all")
        type_label = {"sensor": "센서", "relay": "릴레이", "all": "센서/릴레이"}.get(data_type, data_type)
        return f"{house_id}호 재배사 {type_label} (PostgreSQL)"
    elif tool_name == "search_web":
        query = tool_args.get("query", "")[:30]
        return f"'{query}' 검색 (SearXNG)"
    elif tool_name == "search_farm_knowledge":
        query = tool_args.get("query", "")[:30]
        file_name = tool_args.get("file_name", "")
        if file_name:
            return f"'{file_name}' 문서 검색 (ChromaDB)"
        return f"'{query}' 지식 검색 (ChromaDB)"
    elif tool_name == "fetch_url_content":
        url = tool_args.get("url", "")[:40]
        return f"{url}"
    elif tool_name == "search_gas_price":
        qt = tool_args.get("query_type", "")
        sido = tool_args.get("sido", "")
        label = {"avg_national": "전국 평균", "avg_sido": "시도별", "avg_sigun": "시군구별", "low_price": "최저가"}.get(qt, qt)
        return f"{sido} {label} 유가 (Opinet)" if sido else f"{label} 유가 (Opinet)"
    elif tool_name == "control_relay":
        device = tool_args.get("device_flag", "")
        action = tool_args.get("action", "")
        return f"{device} {action}"
    return ""


def _report_progress(progress_queue: Optional[ThreadQueue], message: str, phase: str = "processing",
                     tool_name: str = None, iteration: int = None, max_iterations: int = None):
    """Tool Use 루프 내부에서 진행 상태를 외부(스트리밍 핸들러)로 보고합니다."""
    if progress_queue is None:
        return
    event = {"message": message, "phase": phase}
    if tool_name:
        event["tool_name"] = tool_name
        event["tool_display"] = _TOOL_DISPLAY_NAMES.get(tool_name, tool_name)
    if iteration is not None:
        event["iteration"] = iteration
    if max_iterations is not None:
        event["max_iterations"] = max_iterations
    try:
        progress_queue.put_nowait(event)
    except Exception:
        pass  # 큐 오류 시 무시 (진행 상태 누락은 치명적이지 않음)

# 워밍업은 llm_warmup.py로 분리됨
from agri_ai_core.src.ai.llm_warmup import _perform_llm_warmup, initialize_background_warmup

# 응답 후처리는 llm_response_processing.py로 분리됨
from agri_ai_core.src.ai.llm_response_processing import (
    _emit_question_log_once, _determine_response_type, _build_structured_result,
    _filter_greeting_turns, _is_conversational_query, _build_farm_info_text,
    _check_answer_retry, _build_conversation_context,
)


# ═════════════════════
# 워밍업 관련 전역 변수
# ═════════════════════

# 전송 계층은 llm_transport.py로 분리됨 (하위 호환 alias)
from agri_ai_core.src.ai.llm_transport import (
    _get_model_gpu_ratio, _get_free_vram_mib, _get_model_ctx_options,
    _use_mcp_fetch, _use_ollama_package, _use_direct_ollama_http,
    _is_direct_ollama_enabled, _disable_direct_ollama_http,
    _is_connection_related_error, _extract_model_names,
    _pkg_ollama_list_models, _build_chat_payload, _pkg_ollama_chat,
    _build_ollama_url, _direct_ollama_json, _direct_ollama_list_models,
    _direct_ollama_chat, _mcp_ollama_list_models, _mcp_ollama_chat,
    _get_available_models, _get_model_name,
    _ollama_chat, _log_llm_request_json, _log_llm_response_json,
)


# ════════════════════════════════════════
# (아래부터 llm_client 고유 함수 시작)
# transport 계층 함수들은 llm_transport.py에 정의.
# message 유틸 함수들은 llm_message_utils.py에 정의.
# ════════════════════════════════════════



# 순수 메시지 유틸은 llm_message_utils.py로 분리됨 (하위 호환 alias 유지)
from agri_ai_core.src.ai.llm_message_utils import (
    serialize_for_log as _serialize_for_log,
    extract_message_content as _extract_message_content,
    normalize_assistant_message as _normalize_assistant_message,
    extract_tool_name as _extract_tool_name,
    extract_tool_arguments as _extract_tool_arguments,
    extract_tool_calls as _extract_tool_calls,
    coerce_numeric_id as _coerce_numeric_id,
)



# _extract_tool_name, _extract_tool_arguments, _coerce_numeric_id은 llm_message_utils로 이동됨
# (상단 import에서 alias로 재노출)



def _normalize_tool_arguments(
    tool_name: str,
    tool_args: Dict[str, Any],
    default_tool_args: Optional[Dict[str, Dict[str, Any]]] = None,
    user_query: str = "",
) -> Dict[str, Any]:
    args = tool_args or {}
    default_args = (default_tool_args or {}).get(tool_name, {}) or {}

    def _pick(key: str, fallback: Any = None) -> Any:
        value = args.get(key)
        if value is None or value == "":
            value = default_args.get(key)
        if value is None or value == "":
            value = fallback
        return value

    if tool_name == "search_web":
        return {
            "query": _pick("query"),
            "n_results": _pick("n_results"),
            "auto_fetch_max": _pick("auto_fetch_max"),
        }
    # 시스템관리자 farm_id 결정: LLM 대화에서 구체적 농장 지정 → 해당 농장, 미지정 → 세션 선택 농장
    def _resolve_admin_farm_id(session_fid, llm_fid_raw):
        """시스템관리자(세션=0)일 때 LLM 판단값으로 farm_id 결정.
        숫자 → 그대로, 농장명 → DB 역조회, 무효 → 세션값 유지."""
        if str(session_fid) != "0":
            return session_fid  # 농장사용자는 세션값 강제
        _llm_fid = str(llm_fid_raw or "").strip()
        if not _llm_fid or _llm_fid == "0":
            return session_fid
        if _llm_fid.isdigit():
            return _llm_fid  # LLM이 숫자 farm_id 전달 (정상)
        # 농장명(문자열) → farm_id 역조회
        try:
            from agri_ai_core.src.ai.farm_cache import get_all_farm_names
            for fid, fname in get_all_farm_names().items():
                if fname == _llm_fid or _llm_fid in fname:
                    logger.info(f"[farm_id해석] 농장명 '{_llm_fid}' → farm_id={fid}")
                    return fid
        except Exception as e:
            logger.warning(f"[farm_id해석] 농장명 역조회 실패: {e}")
        return session_fid  # 매칭 실패 → 세션값 유지

    if tool_name == "search_farm_knowledge":
        _tool_query = _pick("query") or ""
        _meta_kws = ("파일", "학습", "목록", "리스트", "자료", "문서", "업로드", "RAG", "데이터")
        _user_has_meta = any(kw in (user_query or "") for kw in _meta_kws)
        _query_has_meta = any(kw in _tool_query for kw in _meta_kws)
        _session_fid = default_args.get("farm_id")
        _farm_id = _resolve_admin_farm_id(_session_fid, args.get("farm_id"))
        result = {
            "query": _tool_query,
            "n_results": _pick("n_results", 5),
            "file_name": _pick("file_name"),
            "farm_id": _farm_id,
            "house_id": _pick("house_id"),
            "auth_farm_id": default_args.get("auth_farm_id"),
        }
        if _user_has_meta and not _query_has_meta:
            result["_meta_hint"] = True
        return result
    if tool_name == "delete_farm_knowledge":
        _session_fid = default_args.get("farm_id")
        _farm_id = _resolve_admin_farm_id(_session_fid, args.get("farm_id"))
        return {
            "file_name": _pick("file_name"),
            "farm_id": _farm_id,
            "auth_farm_id": default_args.get("auth_farm_id"),
        }
    if tool_name == "get_farm_realtime_data":
        default_farm_id = default_args.get("farm_id")
        default_house_id = default_args.get("house_id")

        # farm_id 결정: _resolve_admin_farm_id 공용 로직 사용
        # 시스템관리자(세션=0) → LLM 판단값 허용, 농장사용자 → 세션값 강제
        farm_id = _resolve_admin_farm_id(default_farm_id, args.get("farm_id"))

        # house_id: LLM이 선택 가능 (특정 재배사 조회 허용), 미지정 시 세션값 사용
        # house_id=0은 생육정보 전용 공통재배사이므로 센서/릴레이 데이터 없음 → 세션값으로 보정
        house_id = _coerce_numeric_id(_pick("house_id"), default_house_id)
        if str(house_id or "").strip() == "0":
            logger.info(
                f"[farm_id] house_id=0(공통재배사) → 세션값={default_house_id} 보정"
            )
            house_id = default_house_id

        # data_type: 'relay'/'sensor' 단독 요청 시 AI분석·알고리즘 추천값 없어 모델이 hallucination
        # → 항상 'all'로 강제하여 완전한 데이터(센서+릴레이+AI권장) 반환
        data_type = "all"

        return {
            "house_id": house_id,
            "farm_id": farm_id,
            "data_type": data_type,
        }
    if tool_name == "search_gas_price":
        return {
            "query_type": _pick("query_type", "avg_national"),
            "sido": _pick("sido"),
            "sigun": _pick("sigun"),
            "prodcd": _pick("prodcd", "B027"),
            "fuel_name": _pick("fuel_name"),
        }
    return args


# ═════════════════════════════════════════
# Ollama에서 사용 가능한 모델 목록 가져오기




def _execute_and_merge_tools(
    tool_calls: list, messages: list, default_tool_args: dict,
    user_query: str, tools_used: list, collected_sources: list,
    execute_tool, iteration: int, max_tool_iterations: int,
    progress_queue=None,
):
    """도구 호출 실행, 결과 정제, 메시지 병합을 처리.
    - 동일 반복 내 중복 호출 제거 (같은 함수+인자 캐시)
    - 결과를 1개 tool 메시지로 병합 (컨텍스트 절약)
    - search_web 출처 수집
    """
    logger.info(f"[Tool Use] 도구호출 {len(tool_calls)}건 감지 (반복{iteration + 1})")
    _results = []
    _dedup_cache = {}

    for tc_idx, tool_call in enumerate(tool_calls, start=1):
        tool_name = _extract_tool_name(tool_call)
        tool_args = _extract_tool_arguments(tool_call)
        if not tool_name:
            logger.warning(f"[Tool Use] 도구 이름 파싱 실패: {tool_call}")
            continue

        tool_args = _normalize_tool_arguments(
            tool_name, tool_args, default_tool_args=default_tool_args, user_query=user_query,
        )

        # 중복 호출 캐시
        _key = (tool_name, json.dumps(tool_args, sort_keys=True, ensure_ascii=False))
        if _key in _dedup_cache:
            logger.info(f"[도구호출] [{tc_idx}/{len(tool_calls)}] {tool_name} → 중복 생략")
            continue

        logger.info(f"[도구호출] [{tc_idx}/{len(tool_calls)}] {tool_name}({tool_args})")

        # 진행 상태
        display = _TOOL_DISPLAY_NAMES.get(tool_name, tool_name)
        detail = _build_tool_detail_message(tool_name, tool_args)
        _report_progress(
            progress_queue,
            f"{display} 중... ({tc_idx}/{len(tool_calls)})" + (f" — {detail}" if detail else ""),
            "tool_calling", tool_name=tool_name,
            iteration=iteration + 1, max_iterations=max_tool_iterations,
        )

        if tool_name not in tools_used:
            tools_used.append(tool_name)

        # 실행
        t0 = time.time()
        result = execute_tool(tool_name, tool_args)
        elapsed = time.time() - t0
        logger.info(f"[도구결과] [{tc_idx}/{len(tool_calls)}] {tool_name} ({elapsed:.1f}s) 결과길이={len(result or '')}자")

        _report_progress(
            progress_queue, f"{display} 완료 ({elapsed:.1f}초, {len(result or '')}자 수신)",
            "tool_done", tool_name=tool_name,
            iteration=iteration + 1, max_iterations=max_tool_iterations,
        )
        logger.info(f"[도구결과데이터] {tool_name}:\n{result}")

        # search_web 출처 수집
        if result and tool_name == "search_web":
            try:
                _, sources = _refine_search_web(result, user_query)
                collected_sources.extend(sources)
            except (json.JSONDecodeError, TypeError):
                pass

        # 정제
        refined = _refine_tool_result(tool_name, result, user_query)
        logger.info(f"[도구정제] {tool_name} 원본={len(result or '')}자 → 정제={len(refined)}자")
        _results.append(refined)
        _dedup_cache[_key] = True

    # 결과 병합 (적정범위 중복 제거 포함)
    if _results:
        _seen = set()
        deduped = []
        for r in _results:
            parts = r.split(" | ")
            filtered = []
            for part in parts:
                if part.startswith("적정범위(공통):"):
                    if "적정범위(공통)" not in _seen:
                        _seen.add("적정범위(공통)")
                        filtered.append(part)
                else:
                    filtered.append(part)
            deduped.append(" | ".join(filtered))
        merged = "\n".join(deduped)
        messages.append({"role": "tool", "content": merged})
        logger.info(f"[도구결과병합] {len(_results)}건 → 1메시지 ({len(merged)}자)")



def get_llm_response_with_tools(
    user_query: str,
    farm_name: str = None,
    temperature: float = 0.5,
    max_tool_iterations: int = 8,
    default_tool_args: Optional[Dict[str, Dict[str, Any]]] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    speech_style: str = None,
    progress_queue: Optional[ThreadQueue] = None,

# (get_llm_response_with_tools 파라미터 블록 계속)
) -> Dict[str, Any]:
    # [DEPRECATED 경고 · D1] 이 Tool Use 반복 루프는 3단계 파이프라인(pipeline/runner.py)의
    # fallback 용으로만 유지된다. 신규 기능은 3단계 파이프라인에 추가하고, 이 경로는 향후
    # 단일화(제거)될 예정이다. 호출 시 경로를 로깅해 의존성 파악 및 조기 경보를 돕는다.
    logger.warning(
        "[DEPRECATED] get_llm_response_with_tools(Tool Use 반복 루프)가 호출됨 — "
        "3단계 파이프라인 fallback 경로. 장기적으로 제거 예정, 새 기능은 pipeline/runner.py 에 추가 요망."
    )
    try:
        from agri_ai_core.src.ai.tools_definition import get_available_tools, get_system_prompt_with_tools
        from agri_ai_core.src.ai.tools_executor import execute_tool

        model_name = _get_model_name()
        tools = get_available_tools()

        # 농장명이 있으면 농장 시스템 프롬프트, 없으면 일반 프롬프트
        if farm_name:
            farm_info = _build_farm_info_text()
            system_prompt = get_system_prompt_with_tools(farm_name, farm_info, speech_style=speech_style or "male")
        else:
            system_prompt = (
                "당신은 다양한 분야의 지식을 갖춘 AI 어시스턴트입니다.\n\n"
                "**말투 (절대 규칙):**\n"
                "- 모든 문장을 반드시 존댓말 어미(~합니다/~입니다/~해요/~세요/~습니다)로 끝내세요.\n"
                "- 설명·나열·요약도 존댓말 문장으로 마무리하세요.\n"
                "- 반말 어미(~한다/~된다/~이다/~했다) 사용 절대 금지합니다.\n"
                "- 불릿/번호 항목도 문장으로 끝날 때는 존댓말로 마무리하세요.\n"
                "- 친절하고 따뜻하게 응대합니다.\n\n"
                "**대화 원칙:**\n"
                "- 질문에는 구체적이고 실용적인 정보를 포함하여 충분히 답변합니다.\n"
                "- 정보가 부족하면 솔직하게 안내하되, 관련된 유용한 내용을 추가로 제공합니다.\n"
                "- 사용자의 의도를 파악하여 맥락에 맞는 풍부한 답변을 제공합니다.\n\n"
                "**출력 형식:**\n"
                "- 내부 추론/독백/분석 과정을 절대 출력하지 않습니다.\n"
                "- <think> 태그 사용 절대 금지합니다. 순수 답변 본문만 출력합니다.\n"
                "/no_think"
            )

        _emit_question_log_once(
            user_query=user_query,
            farm_name=farm_name,
            max_tool_iterations=max_tool_iterations,
            tools_count=len(tools or []),
        )

        # 메시지 히스토리
        messages = [{"role": "system", "content": system_prompt}]

        # 하이브리드 대화 컨텍스트 주입
        if conversation_history:
            _build_conversation_context(messages, conversation_history, user_query)

        messages.append({"role": "user", "content": user_query})

        # 웹 검색 출처 URL 수집용
        _collected_sources = []
        # 사용된 도구 추적
        _tools_used: List[str] = []

        logger.info(
            f"[Tool Use] 시작 model={model_name} tools={len(tools)}개 "
            f"messages={len(messages)}개 max_iterations={max_tool_iterations}"
        )

        # [PERF:대화] 전체 Tool Use 루프 시작
        _t_tooluse_start = time.time()

        # 도구 호출 반복 (최대 max_tool_iterations회)
        _prev_had_tool_calls = True  # 첫 반복은 항상 도구 제공
        _empty_response_count = 0  # 빈 응답 연속 횟수
        _retry_state = {}  # 방어 로직 중복 방지 플래그 (각 유형별 1회만 발동)
        for iteration in range(max_tool_iterations):
            logger.info(f"[Tool Use] --- 반복 {iteration + 1}/{max_tool_iterations} ---")

            # 진행 상태 보고: LLM 호출 시작
            if iteration == 0:
                _report_progress(progress_queue,
                                 f"질문을 분석하고 필요한 도구/데이터를 파악하고 있습니다... (1/{max_tool_iterations}단계)",
                                 "llm_analyzing",
                                 iteration=iteration + 1, max_iterations=max_tool_iterations)
            elif iteration == max_tool_iterations - 1:
                _report_progress(progress_queue,
                                 f"수집된 정보를 종합하여 최종 답변을 작성하고 있습니다... ({iteration + 1}/{max_tool_iterations}단계)",
                                 "llm_generating",
                                 iteration=iteration + 1, max_iterations=max_tool_iterations)
            else:
                _report_progress(progress_queue,
                                 f"추가 데이터를 조회하고 답변을 구성하고 있습니다... ({iteration + 1}/{max_tool_iterations}단계)",
                                 "llm_generating",
                                 iteration=iteration + 1, max_iterations=max_tool_iterations)

            # LLM 호출
            # 이전 반복에서 도구 호출이 있었으면 → 다음에도 도구 제공 (다단계 호출 지원)
            # 이전 반복에서 도구 호출이 없었으면 → 도구 제거 (최종 답변 생성)
            # GPU 탑재 비율 기반 컨텍스트 옵션 (모델·VRAM 변경 시 자동 적용)
            _ctx_opts = _get_model_ctx_options(model_name, NUM_PREDICT)
            if _prev_had_tool_calls:
                # 도구 호출 모드: 첫 반복은 도구 JSON만 생성하면 되므로 출력 제한
                # → 도구 호출 속도 향상 + LLM이 도구 대신 장문 답변 생성하는 환각 방지
                iter_num_predict = NUM_PREDICT_TOOL_CALL if iteration == 0 else _ctx_opts["num_predict"]
                iter_tools = tools
            else:
                iter_num_predict = _ctx_opts["num_predict"]
                iter_tools = None
            t_iter = time.time()
            response = _ollama_chat(
                model=model_name,
                messages=messages,
                tools=iter_tools,
                options={
                    "temperature": temperature,
                    "top_p": 0.9,
                    "top_k": 40,
                    "num_predict": iter_num_predict,
                    "num_ctx": _ctx_opts["num_ctx"],
                    "think": False,   # 항상 적용: 모든 모델 thinking 비활성화
                },
                keep_alive='1h'
            )

            # 응답에서 메시지 추출
            if hasattr(response, 'message'):
                assistant_message_raw = response.message
            elif isinstance(response, dict) and 'message' in response:
                assistant_message_raw = response['message']
            else:
                logger.error("LLM 응답 형식 오류")
                return _build_structured_result("죄송합니다. 응답을 생성할 수 없습니다.", [], [])

            assistant_message = _normalize_assistant_message(assistant_message_raw)

            # done_reason 추출 (length면 토큰 한도 도달, stop이면 정상 종료)
            _done_reason = None
            if hasattr(response, 'done_reason'):
                _done_reason = response.done_reason
            elif isinstance(response, dict):
                _done_reason = response.get('done_reason')

            # 메시지 히스토리에 추가
            messages.append(assistant_message)

            # 도구 호출 추출 및 상태 추적
            tool_calls = _extract_tool_calls(assistant_message)
            iter_elapsed = time.time() - t_iter
            _prev_had_tool_calls = bool(tool_calls)

            if not tool_calls:
                final_answer = assistant_message.get("content", "")
                _tooluse_total_s = time.time() - _t_tooluse_start
                logger.info(
                    f"[Tool Use] 도구호출 없음 → 최종답변 반환 (반복{iteration + 1}, {iter_elapsed:.1f}s) "
                    f"답변길이={len(final_answer)}자 done_reason={_done_reason}"
                )
                logger.debug(
                    f"[PERF:대화] ToolUse루프-LLM호출={iter_elapsed:.1f}s, "
                    f"ToolUse루프-전체={_tooluse_total_s:.1f}s (반복{iteration + 1})"
                )

                # 방어 로직: LLM 답변 검증 및 필요시 강제 재시도
                _retry = _check_answer_retry(
                    final_answer=final_answer, user_query=user_query,
                    tools_used=_tools_used, iteration=iteration,
                    max_iterations=max_tool_iterations, done_reason=_done_reason,
                    had_tools=iter_tools is not None, retry_state=_retry_state,
                )
                if _retry:
                    messages.pop()
                    messages.append({"role": "user", "content": _retry})
                    _prev_had_tool_calls = True
                    continue

                # 빈 응답 감지 (qwen3 thinking 모드에서 content="" 반환하는 경우)
                if not final_answer.strip():
                    _empty_response_count += 1
                    if _empty_response_count <= 1 and iteration < max_tool_iterations - 1:
                        logger.warning(
                            f"[Tool Use] 빈 응답 감지 (반복{iteration + 1}) → 도구 호출 재시도 "
                            f"(빈응답횟수={_empty_response_count})"
                        )
                        # 빈 응답 메시지 제거 후 도구 호출 유도 (원본 질문 포함)
                        messages.pop()  # 빈 assistant 메시지 제거
                        messages.append({
                            "role": "user",
                            "content": (
                                f"사용자의 원래 요청: \"{user_query}\"\n"
                                f"도구를 호출하여 위 요청을 처리하세요. "
                                f"반드시 적절한 도구를 선택하고 호출해야 합니다."
                            ),
                        })
                        _prev_had_tool_calls = True
                        continue
                    elif _empty_response_count > 1:
                        logger.warning(
                            f"[Tool Use] 빈 응답 {_empty_response_count}회 연속 → 루프 종료"
                        )
                        final_answer = "죄송합니다. 요청을 처리하지 못했습니다. 다시 시도해 주세요."
                        return _build_structured_result(final_answer, _collected_sources, _tools_used)
                else:
                    _empty_response_count = 0  # 유효한 응답이면 카운터 리셋

                _report_progress(progress_queue, "답변을 정리하고 있습니다...", "finalizing")
                _t_final = time.time()
                finalized = _finalize_user_facing_answer(
                    model_name=model_name,
                    user_query=user_query,
                    farm_name=farm_name,
                    raw_answer=final_answer,
                )
                _final_s = time.time() - _t_final
                logger.debug(f"[PERF:대화] 후처리(_finalize)={_final_s:.1f}s")

                _verified_urls = {s.get("url", "") for s in _collected_sources if s.get("url")}
                finalized = _strip_hallucinated_urls(finalized, _verified_urls)
                return _build_structured_result(finalized, _collected_sources, _tools_used)

            # 도구 호출 실행 + 결과 병합
            _execute_and_merge_tools(
                tool_calls=tool_calls, messages=messages,
                default_tool_args=default_tool_args, user_query=user_query,
                tools_used=_tools_used, collected_sources=_collected_sources,
                execute_tool=execute_tool, iteration=iteration,
                max_tool_iterations=max_tool_iterations,
                progress_queue=progress_queue,
            )

        # 최대 반복 횟수 도달
        logger.warning(f"[Tool Use] 최대 반복 횟수({max_tool_iterations}) 도달")

        # 마지막 메시지가 assistant 메시지면 그것을 반환
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                finalized = _finalize_user_facing_answer(
                    model_name=model_name,
                    user_query=user_query,
                    farm_name=farm_name,
                    raw_answer=msg.get("content", "죄송합니다. 응답을 완료할 수 없습니다."),
                )
                _verified_urls = {s.get("url", "") for s in _collected_sources if s.get("url")}
                finalized = _strip_hallucinated_urls(finalized, _verified_urls)
                return _build_structured_result(finalized, _collected_sources, _tools_used)
            elif hasattr(msg, 'content') and hasattr(msg, 'role'):
                if msg.role == "assistant":
                    finalized = _finalize_user_facing_answer(
                        model_name=model_name,
                        user_query=user_query,
                        farm_name=farm_name,
                        raw_answer=msg.content,
                    )
                    _verified_urls = {s.get("url", "") for s in _collected_sources if s.get("url")}
                    finalized = _strip_hallucinated_urls(finalized, _verified_urls)
                    return _build_structured_result(finalized, _collected_sources, _tools_used)

        return _build_structured_result("죄송합니다. 응답을 생성할 수 없습니다.", [], [])

    except Exception as e:
        if _is_connection_related_error(e):
            logger.warning(f"Tool Use LLM 응답 생성 실패(연결/환경): {e}")
            return _build_structured_result(
                "죄송합니다. 현재 LLM 서버 연결이 불안정합니다. 잠시 후 다시 시도해 주세요.", [], [])
        else:
            logger.error(f"Tool Use LLM 응답 생성 중 오류: {e}")
            logger.error(traceback.format_exc())
        return _build_structured_result(f"죄송합니다. 응답 생성 중 오류가 발생했습니다: {str(e)}", [], [])
