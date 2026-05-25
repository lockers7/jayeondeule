# ════════════════════════════════════════════════════════════════════════════
# LLM 쿼리 핸들러 — Tool Use 방식으로 사용자 질문 처리 및 SSE 스트리밍.
# 대화 컨텍스트는 conversation_context.py, 3단계 파이프라인은 pipeline/runner.py에 분리됨.
# --->
# _build_default_tool_args: 도구별 기본 인자 생성 (파일명 감지 포함)
# _call_llm_with_timeout: LLM 호출 + 타임아웃 처리
# _unpack_llm_result: LLM 결과를 튜플로 언패킹
# query_llm_simple: 비동기 LLM 질의 공개 API
# query_llm_simple_stream: SSE 스트리밍 질의 공개 API
# ════════════════════════════════════════════════════════════════════════════
import json
import os
import re
import asyncio
import time
import traceback
from datetime import datetime

from agri_ai_core.logs import setup_logger, setup_web_logger
from agri_ai_core.src.ai.llm_client import get_llm_response_with_tools
from agri_ai_core.src.ai.file_processor import process_uploaded_files
from agri_ai_core.src.ai.conversation_context import (
    load_hybrid_context,
    save_conversation_turn_hybrid,
)

logger = setup_logger(__name__)
web_logger = setup_web_logger("chat")

_LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SECONDS", "600"))
_STREAM_HEARTBEAT_SECONDS = max(1, int(os.getenv("STREAM_HEARTBEAT_SECONDS", "3")))

# 3단계 파이프라인 모드 설정
_USE_3STAGE_PIPELINE = os.getenv("USE_3STAGE_PIPELINE", "false").lower() == "true"


# _dedupe_list는 query_utils.py로 이동됨 (하위 호환 alias)
from agri_ai_core.src.ai.query_utils import dedupe_list as _dedupe_list

# _split_for_streaming은 query_utils.py로 이동됨 (하위 호환 alias)
from agri_ai_core.src.ai.query_utils import split_for_streaming as _split_for_streaming


# ═════════════════════
# 도구별 기본 인자 생성
# ═════════════════════
# 파일명 패턴: UUID prefix + 파일명.확장자 또는 단순 파일명.확장자
# 확장자는 알파벳만 허용 (소수점 숫자 오탐 방지: 2528.92000 등)
# 단순 파일명은 최소 1개 문자(한글/영문) 포함 필수
_FILE_NAME_RE = re.compile(
    r'[\'"]?'
    r'('
    r'[a-f0-9]{6,}_[\w\-가-힣.]+\.[a-zA-Z]{2,5}'
    r'|'
    r'(?=.*[a-zA-Z가-힣])[\w\-가-힣.]+\.[a-zA-Z]{2,5}'
    r')'
    r'[\'"]?'
)


# ────────────────────────────────────────────────────────────────────
# 세션 컨텍스트(farm_id/house_id/auth_farm_id + 질문에서 감지한 file_name)
# 를 도구별 default 인자로 변환.
# 
# 실제 변환 규칙은 tools_utils.TOOL_DEFAULT_CONTEXT 선언형 테이블에서 관리한다.
# 새 도구가 farm_id/house_id/auth_farm_id 를 받아야 하면 해당 테이블에 한 줄만
# 추가하면 된다.
# ────────────────────────────────────────────────────────────────────
def _build_default_tool_args(user_query, farm_id, house_id, auth_farm_id=None):
    from agri_ai_core.src.ai.tools_utils import build_default_tool_args as _build

    # 질문에서 파일명 패턴 감지 (RAG 전용)
    detected_file_name = None
    match = _FILE_NAME_RE.search(user_query or "")
    if match:
        detected_file_name = match.group(1)
        # UUID 접두사(8자리hex_) 제거하여 원본 파일명으로 정규화
        _uuid_match = re.match(r'^[a-f0-9]{8}_(.+)$', detected_file_name)
        if _uuid_match:
            detected_file_name = _uuid_match.group(1)
        logger.info(f"[기본인자] 파일명 감지: '{detected_file_name}'")

    return _build(
        farm_id=farm_id,
        house_id=house_id,
        auth_farm_id=auth_farm_id,
        file_name=detected_file_name,
    )


async def _call_llm_with_timeout(full_query, farm_name, default_tool_args, conversation_history,
                                  speech_style=None, progress_queue=None):
    return await asyncio.wait_for(
        asyncio.to_thread(
            get_llm_response_with_tools,
            user_query=full_query,
            farm_name=farm_name,
            default_tool_args=default_tool_args,
            conversation_history=conversation_history,
            speech_style=speech_style,
            progress_queue=progress_queue,
        ),
        timeout=_LLM_TIMEOUT,
    )


# ════════════════════════════════════════════════════════════════════════════
# LLM 결과를 (response, sources, tools_used, response_type, tool_calls_detail)
# 튜플로 언패킹. tool_calls_detail 은 Wave 4 E1 도구 호출 감사 로그 (선택적).
# ════════════════════════════════════════════════════════════════════════════
def _unpack_llm_result(result):
    if isinstance(result, dict):
        return (
            result.get("response", ""),
            result.get("sources", []),
            result.get("tools_used", []),
            result.get("response_type", "general"),
            result.get("tool_calls_detail") or None,
        )
    return (str(result), [], [], "general", None)


# ═════════════════════════
# 질의 처리 (Tool Use 방식)
# ═════════════════════════
async def query_llm_simple(user_query, file_paths=None, farm_id=None, house_id=None,
                           farm_name=None, house_name=None, session_id=None, speech_style=None,
                           auth_farm_id=None):
    start_time = datetime.now()

    try:
        # [1/3] 사용자 질문
        logger.info(f"[사용자질문] \"{(user_query or '')[:120]}\" (len={len(user_query or '')}, farm={farm_name or '-'})")

        # 웹 로그: 요청 JSON 기록
        request_json = {
            "type": "chat_request",
            "timestamp": start_time.isoformat(),
            "query": user_query,
            "farm_id": farm_id,
            "house_id": house_id,
            "farm_name": farm_name,
            "house_name": house_name,
            "files": [f.get("filename", "") for f in file_paths] if file_paths else [],
        }
        web_logger.info(
            "[Chat 요청]\n%s",
            json.dumps(request_json, ensure_ascii=False, indent=2),
        )

        # 첨부 파일 처리
        full_query = user_query
        if file_paths:
            logger.info(f"[첨부파일] {len(file_paths)}개 파일 처리")
            file_content = process_uploaded_files(file_paths)
            full_query = f"{user_query}\n\n{file_content}"

        default_tool_args = _build_default_tool_args(user_query, farm_id, house_id, auth_farm_id=auth_farm_id)

        # [PERF:대화] 하이브리드 컨텍스트 로드 시간 측정
        _t_ctx = time.time()
        conversation_history = load_hybrid_context(session_id, user_query, farm_id)
        _ctx_ms = (time.time() - _t_ctx) * 1000
        logger.debug(f"[PERF:대화] 하이브리드컨텍스트로드={_ctx_ms:.0f}ms (session={session_id[:12] if session_id else '-'})")

        # [2/3] LLM 답변 생성
        llm_start = datetime.now()
        try:
            if _USE_3STAGE_PIPELINE:
                # 3단계 분리형 파이프라인 (to_thread로 이벤트루프 블로킹 방지)
                from agri_ai_core.src.ai.pipeline.runner import run_3stage_pipeline_sync
                logger.info("[LLM시작] 모드=3단계 파이프라인 (질문분석→데이터수집→답변작성)")
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        run_3stage_pipeline_sync,
                        user_query=user_query, full_query=full_query,
                        farm_id=farm_id, house_id=house_id, farm_name=farm_name,
                        default_tool_args=default_tool_args,
                        conversation_history=conversation_history,
                        speech_style=speech_style,
                    ),
                    timeout=_LLM_TIMEOUT,
                )
            else:
                # 기존 Tool Use 루프
                logger.info("[LLM시작] 모드=Tool Use (LLM 자율 도구 선택)")
                result = await _call_llm_with_timeout(full_query, farm_name, default_tool_args, conversation_history, speech_style=speech_style)
        except asyncio.TimeoutError:
            logger.error(f"[LLM타임아웃] {_LLM_TIMEOUT}초 초과")
            yield {
                "response": f"죄송합니다. 응답 생성 시간이 초과되었습니다. ({_LLM_TIMEOUT}초)",
                "sources": [],
                "tools_used": [],
                "response_type": "general",
            }
            return

        response_text, sources, tools_used, response_type, tool_calls_detail = _unpack_llm_result(result)

        llm_elapsed = (datetime.now() - llm_start).total_seconds()
        total_elapsed = (datetime.now() - start_time).total_seconds()

        # [3/3] 최종 답변
        logger.info(f"[LLM완료] 답변생성={llm_elapsed:.1f}s type={response_type} tools={tools_used}")
        logger.debug(f"[PERF:대화] 전체파이프라인={total_elapsed:.1f}s (LLM={llm_elapsed:.1f}s, 전처리={total_elapsed - llm_elapsed:.1f}s)")
        answer_preview = (response_text or "")[:200]
        if len(response_text or "") > 200:
            answer_preview += "..."
        logger.info(f"[최종답변] len={len(response_text or '')} 총소요={total_elapsed:.1f}s")
        logger.info(f"[답변내용] {answer_preview}")

        save_conversation_turn_hybrid(session_id, user_query, response_text, farm_id)

        # 웹 로그: 응답 JSON 기록
        response_json = {
            "type": "chat_response",
            "timestamp": datetime.now().isoformat(),
            "query": user_query,
            "response": response_text,
            "sources": sources,
            "tools_used": tools_used,
            "response_type": response_type,
            "processing_time": round(total_elapsed, 3),
            "farm_name": farm_name,
            "house_name": house_name,
            "session_id": session_id,
        }
        web_logger.info(
            "[Chat 응답]\n%s",
            json.dumps(response_json, ensure_ascii=False, indent=2),
        )

        yield {
            "response": response_text,
            "sources": sources,
            "tools_used": tools_used,
            "response_type": response_type,
            "tool_calls_detail": tool_calls_detail,   # [E1] 감사 로그 pass-through
        }

    except Exception as e:
        logger.error(f"Tool Use 질의 처리 중 오류 발생: {e}")
        logger.error(traceback.format_exc())
        yield {
            "response": f"에러: 질의 처리 중 문제가 발생했습니다. ({str(e)})",
            "sources": [],
            "tools_used": [],
            "response_type": "general",
        }


# ══════════════════════
# SSE 스트리밍 질의 처리
# ══════════════════════
async def query_llm_simple_stream(user_query, farm_id=None, house_id=None,
                                   farm_name=None, house_name=None, session_id=None, speech_style=None,
                                   auth_farm_id=None):
    start_time = datetime.now()

    try:
        # [1] 질문 분석
        yield {"type": "status", "content": "질문을 분석하고 있습니다..."}

        logger.info(f"[스트리밍] \"{(user_query or '')[:120]}\" (farm={farm_name or '-'})")
        web_logger.info(
            "[Chat 스트리밍 요청]\n%s",
            json.dumps({
                "type": "chat_stream_request",
                "timestamp": start_time.isoformat(),
                "query": user_query,
                "farm_id": farm_id, "house_id": house_id,
                "farm_name": farm_name, "house_name": house_name,
            }, ensure_ascii=False, indent=2),
        )

        # [1.5] [2026-05-26 hotfix] fast_classify=greeting 빠른 우회
        # _GREETING_RE 매칭 = 농장 컨텍스트 불필요한 일상 인사 (사용자 룰 예외 허용 범위).
        # load_hybrid_context (ChromaDB 임베딩) 가 5분 hang 발생 사례 (bge-m3 첫 로드 VRAM swap).
        # 이 분기는 *극히 명확한 인사 패턴만* 우회 — 그 외 질문은 모두 ANALYZER+MCP 흐름.
        try:
            from agri_ai_core.src.ai.pipeline.question_analyzer import fast_classify
            from agri_ai_core.src.ai.pipeline.answer_generator import _greeting_quick_response
            if fast_classify(user_query) == "greeting":
                text = _greeting_quick_response(user_query, farm_name, speech_style)
                logger.info(f"[스트리밍] greeting 우회 (load_hybrid_context skip) — {text[:40]!r}")
                yield {"type": "status", "content": "답변을 생성하고 있습니다..."}
                for chunk in _split_for_streaming(text):
                    yield {"type": "token", "content": chunk}
                yield {
                    "type": "done",
                    "session_id": session_id,
                    "sources": [], "tools_used": [], "response_type": "greeting",
                    "tool_calls_detail": [],
                    "elapsed_sec": round((datetime.now() - start_time).total_seconds(), 1),
                }
                try:
                    save_conversation_turn_hybrid(session_id, user_query, text, farm_id, label="스트리밍·greeting][")
                except Exception:
                    pass
                return
        except Exception as _e:
            logger.debug(f"[스트리밍] greeting 우회 실패 (정상 흐름 계속): {_e}")

        full_query = user_query
        default_tool_args = _build_default_tool_args(user_query, farm_id, house_id, auth_farm_id=auth_farm_id)

        # [PERF:대화] 하이브리드 컨텍스트 로드 시간 측정
        _t_ctx = time.time()
        conversation_history = load_hybrid_context(session_id, user_query, farm_id, label="스트리밍][")
        _ctx_ms = (time.time() - _t_ctx) * 1000
        logger.debug(f"[PERF:대화] 스트리밍-하이브리드컨텍스트로드={_ctx_ms:.0f}ms")

        # [3] LLM 답변 생성 (progress_queue로 상세 진행 상태 수신)
        from queue import Queue as ThreadQueue, Empty as QueueEmpty
        progress_queue = ThreadQueue()

        yield {"type": "status", "content": "답변을 생성하고 있습니다..."}

        llm_start = datetime.now()
        if _USE_3STAGE_PIPELINE:
            from agri_ai_core.src.ai.pipeline.runner import run_3stage_pipeline_sync
            logger.info("[스트리밍] 모드=3단계 파이프라인")
            llm_task = asyncio.create_task(
                asyncio.to_thread(
                    run_3stage_pipeline_sync,
                    user_query=user_query, full_query=full_query,
                    farm_id=farm_id, house_id=house_id, farm_name=farm_name,
                    default_tool_args=default_tool_args,
                    conversation_history=conversation_history,
                    speech_style=speech_style,
                    progress_queue=progress_queue,
                )
            )
        else:
            logger.info("[스트리밍] 모드=Tool Use")
            llm_task = asyncio.create_task(
                _call_llm_with_timeout(full_query, farm_name, default_tool_args, conversation_history,
                                       speech_style=speech_style, progress_queue=progress_queue)
            )
        # 진행 상태 이력 (도구 호출 정보 등)을 수집하여 대기 중 순환 표시
        _progress_history = []  # 도구/단계 메시지 이력
        _last_progress_msg = ""
        _idle_cycle = 0  # 새 이벤트 없이 반복된 횟수
        _last_phase = "starting"  # 최근 수신한 phase (하트비트 메시지 선택에 사용)

        # phase별 / 경과시간별 하트비트 메시지 테이블 — 반복을 피하고
        # 현재 내부 진행 단계를 사용자에게 자세히 전달한다.
        # ─ llm_generating(3단계): 답변 생성이 가장 오래 걸리므로 단계별 세분화
        _HEARTBEAT_BY_PHASE = {
            "analyzing": [
                (0,   "🧠 질문 의도를 파악하고 있습니다..."),
                (10,  "🧠 질문 유형을 분류하고 있습니다..."),
                (20,  "🧠 필요한 데이터를 판단하고 있습니다..."),
            ],
            "data_collecting": [
                (0,   "📥 필요한 데이터를 수집하고 있습니다..."),
                (10,  "📥 데이터를 계속 수집하고 있습니다..."),
                (30,  "📥 여러 소스에서 데이터를 확인하고 있습니다..."),
            ],
            "validating": [
                (0,   "🔎 수집한 데이터의 충분성을 검증하고 있습니다..."),
                (10,  "🔎 추가 자료가 필요한지 판단 중입니다..."),
            ],
            "supplementing": [
                (0,   "📥 부족한 자료를 보충 수집하고 있습니다..."),
            ],
            "llm_generating": [
                # 데이터 기반 응답(농장 센서/검색/도구 결과 종합 등) — 표·리스트 가능, 다소 김
                # [변경13 · 2026-04-30] 인사·짧은 답변에 부적절했던 "📊 표와 구조를
                # 구성하고 있습니다" 메시지 제거. 답변 형식과 무관한 일반 표현으로 통일.
                (0,   "✍️ 답변을 작성하고 있습니다..."),
                (10,  "✍️ 답변을 정리하고 있습니다..."),
                (30,  "✍️ 답변을 다듬고 있습니다..."),
                (60,  "🧵 답변을 마무리하고 있습니다..."),
                (110, "🧵 마지막 검토 중입니다..."),
            ],
            "llm_generating_light": [
                # 인사/단순 일반 답변 — 보통 5~10초 내 종료, 메시지도 간결하게
                # 데이터 수집·표 구성과 무관한 표현만 사용.
                (0,  "✍️ 답변을 작성하고 있습니다..."),
                (5,  "✍️ 답변을 정리하고 있습니다..."),
            ],
            "finalizing": [
                (0,   "🧵 답변을 최종 정리하고 있습니다..."),
            ],
        }
        # phase 미지정/기타일 때 폴백 메시지 (3개 순환)
        _waiting_messages = [
            "AI가 답변을 준비하고 있습니다...",
            "최적의 답변을 구성하고 있습니다...",
            "정보를 종합하고 있습니다...",
        ]
        _phase_enter_ts = datetime.now()  # 현재 phase 진입 시점

        # ────────────────────────────────────────────────────────────────────
        # 현재 phase와 해당 phase 내 경과시간으로 안내 문구를 선택.
        # ────────────────────────────────────────────────────────────────────
        def _pick_heartbeat_msg(phase: str, phase_elapsed: int) -> str:
            table = _HEARTBEAT_BY_PHASE.get(phase)
            if not table:
                return _waiting_messages[_idle_cycle % len(_waiting_messages)]
            # 테이블은 (threshold_sec, msg) 오름차순 → 경과시간 이하 최대값 선택
            chosen = table[0][1]
            for th, msg in table:
                if phase_elapsed >= th:
                    chosen = msg
            return chosen

        while True:
            try:
                result = await asyncio.wait_for(
                    asyncio.shield(llm_task),
                    timeout=_STREAM_HEARTBEAT_SECONDS,
                )
                break
            except asyncio.TimeoutError:
                logger.warning(f"[스트리밍] 하트비트 타임아웃 ({_STREAM_HEARTBEAT_SECONDS}s)")
                # LLM 자체 타임아웃이면 즉시 에러 반환
                if llm_task.done():
                    logger.error(f"[스트리밍][LLM타임아웃] {_LLM_TIMEOUT}초 초과")
                    yield {"type": "error", "content": f"응답 생성 시간이 초과되었습니다. ({_LLM_TIMEOUT}초)"}
                    return

                # progress_queue에서 모든 이벤트를 꺼냄
                new_events = []
                try:
                    while True:
                        new_events.append(progress_queue.get_nowait())
                except QueueEmpty:
                    pass

                elapsed_wait = int((datetime.now() - llm_start).total_seconds())

                if new_events:
                    # 새 이벤트가 있으면 최신 것을 표시하고 이력에 추가
                    _idle_cycle = 0
                    for evt in new_events:
                        msg = evt.get("message", "")
                        if msg and msg not in [h.get("message") for h in _progress_history]:
                            _progress_history.append(evt)
                    latest = new_events[-1]
                    _last_progress_msg = latest.get("message", "")
                    new_phase = latest.get("phase", "processing")
                    # phase가 바뀐 경우 진입 타임스탬프 갱신 (하트비트 경과시간 리셋)
                    if new_phase != _last_phase:
                        _phase_enter_ts = datetime.now()
                        _last_phase = new_phase
                    # 도구명 + 단계 정보 포함하여 상세 표시
                    _tool_label = ""
                    if latest.get("tool_display"):
                        _iter_str = ""
                        if latest.get("iteration") and latest.get("max_iterations"):
                            _iter_str = f" {latest['iteration']}/{latest['max_iterations']}단계"
                        _tool_label = f"[{latest['tool_display']}{_iter_str}] "
                    yield {
                        "type": "status",
                        "content": f"{_tool_label}{_last_progress_msg} ({elapsed_wait}초 경과)",
                        "phase": new_phase,
                        "tool_name": latest.get("tool_name"),
                        "tool_display": latest.get("tool_display"),
                        "iteration": latest.get("iteration"),
                        "max_iterations": latest.get("max_iterations"),
                    }
                else:
                    # 새 이벤트 없음 → 현재 phase와 해당 phase 경과시간에 맞춘
                    # 세분화된 하트비트 메시지를 선택해 출력
                    _idle_cycle += 1
                    phase_elapsed = int((datetime.now() - _phase_enter_ts).total_seconds())
                    cycle_msg = _pick_heartbeat_msg(_last_phase, phase_elapsed)
                    yield {
                        "type": "status",
                        "content": f"{cycle_msg} ({elapsed_wait}초 경과)",
                        "phase": _last_phase,
                    }

        response_text, sources, tools_used, response_type, tool_calls_detail = _unpack_llm_result(result)

        llm_elapsed = (datetime.now() - llm_start).total_seconds()
        total_elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"[스트리밍][LLM완료] 답변생성={llm_elapsed:.1f}s type={response_type} tools={tools_used}")
        logger.debug(f"[PERF:대화] 스트리밍-전체파이프라인={total_elapsed:.1f}s (LLM={llm_elapsed:.1f}s, 전처리={total_elapsed - llm_elapsed:.1f}s)")

        # [4] 응답 텍스트를 청크 단위로 전송 (clean_llm_response는 llm_client 내부에서 이미 처리됨)
        for chunk in _split_for_streaming(response_text):
            yield {"type": "token", "content": chunk}

        # [5] 완료 이벤트
        yield {
            "type": "done",
            "session_id": session_id,
            "sources": sources,
            "tools_used": tools_used,
            "response_type": response_type,
            "tool_calls_detail": tool_calls_detail,   # [E1] 감사 로그 pass-through
            "elapsed_sec": round(total_elapsed, 1),
        }

        save_conversation_turn_hybrid(session_id, user_query, response_text, farm_id, label="스트리밍][")

        # 통계 기록
        from agri_ai_core.src.ai.stats_collector import get_stats_collector
        get_stats_collector().record_query(
            success=True,
            processing_time=round(total_elapsed, 3),
            tools_used=tools_used,
            response_type=response_type,
        )

        # 웹 로그
        web_logger.info(
            "[Chat 스트리밍 응답]\n%s",
            json.dumps({
                "type": "chat_stream_response",
                "timestamp": datetime.now().isoformat(),
                "query": user_query,
                "response_length": len(response_text or ""),
                "sources": sources,
                "tools_used": tools_used,
                "response_type": response_type,
                "processing_time": round(total_elapsed, 3),
                "farm_name": farm_name,
                "session_id": session_id,
            }, ensure_ascii=False, indent=2),
        )

    except asyncio.CancelledError:
        logger.warning("[스트리밍] 취소됨 (클라이언트 연결 종료 또는 서버 타임아웃)")
        raise
    except Exception as e:
        logger.error(f"스트리밍 질의 처리 중 오류: {e}")
        logger.error(traceback.format_exc())
        yield {"type": "error", "content": f"질의 처리 중 문제가 발생했습니다. ({str(e)})"}
