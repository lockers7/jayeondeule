# ════════════════════════════════════════════════════════════════════════════════
# 3단계 분리형 파이프라인 실행기 — question_analyzer → data_collector → answer_generator
# query_handler_simple.py에서 분리된 L3 계층 모듈.
# 실패 시 기존 Tool Use 루프로 fallback (L4 llm_client 하향 호출).
# --->
# run_3stage_pipeline_sync: 3단계 파이프라인 동기 실행 (asyncio.to_thread로 호출)
# ════════════════════════════════════════════════════════════════════════════════
import time
import traceback

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# 3단계 분리형 파이프라인 실행 (동기 함수 — asyncio.to_thread()로 호출)
# 1단계: 질문유형분석 → 2단계: 데이터수집+검증 → 3단계: 답변작성
# 
# 기존 Tool Use 루프를 대체하며, 실패 시 기존 루프로 fallback.
# ────────────────────────────────────────────────────────────────────
def run_3stage_pipeline_sync(user_query, full_query, farm_id, house_id, farm_name,
                              default_tool_args, conversation_history, speech_style,
                              progress_queue=None):
    from agri_ai_core.src.ai.pipeline.question_analyzer import analyze_question
    from agri_ai_core.src.ai.pipeline.data_collector import DataCollector
    from agri_ai_core.src.ai.pipeline.answer_generator import generate_answer
    from agri_ai_core.src.ai.llm_client import _build_farm_info_text, _report_progress, get_llm_response_with_tools

    t0 = time.time()

    # 진행 상태 콜백 (스트리밍용)
    def _progress(message, phase, tool_name=None):
        _report_progress(progress_queue, message, phase, tool_name=tool_name)

    try:
        # [1단계] 질문유형분석
        _progress("질문을 분석하고 있습니다...", "analyzing")
        logger.info("[3단계파이프라인] === 1단계: 질문유형분석 시작 ===")

        # 대화 컨텍스트를 텍스트로 변환 (1단계 분석기에 전달)
        ctx_for_analyzer = conversation_history

        analysis = analyze_question(
            user_query=full_query,
            conversation_context=ctx_for_analyzer,
            farm_id=farm_id,
            house_id=house_id,
        )

        question_type = analysis.get("question_type", "general")
        required_data = analysis.get("required_data", []) or []
        logger.info(f"[3단계파이프라인] 1단계 완료: type={question_type} 도구={len(required_data)}개")

        # ⛔ 절대 제거 금지 — 분석 자가학습 세이프티넷
        # "앞으로 ~ 질문에는 ~ 하라"류 가르침 발화는 ANALYZER 분류와 무관하게
        # 교훈 등록을 보장한다. 2단계 스킵 판정보다 앞에 두어 general/빈 계획
        # 오분류에도 DataCollector 경로로 강제 진입시킨다. 판정은 사용자 원문만.
        _force_collect = False
        try:
            from agri_ai_core.src.ai.chat_lessons import detect_teaching
            if (detect_teaching(user_query)
                    and not any(d.get("tool") == "manage_analysis_lesson"
                                for d in required_data)):
                required_data.append({
                    "tool": "manage_analysis_lesson",
                    "args": {"action": "register",
                             "lesson_text": (user_query or "")[:400]},
                    "priority": 3,
                })
                analysis["required_data"] = required_data
                _force_collect = True
                logger.warning(
                    f"[세이프티넷] 가르침 발화 감지 — 분석 교훈 등록 자동 보장 "
                    f"(query=\"{(user_query or '')[:60]}\")")
        except Exception:
            pass

        # 2단계 스킵 조건:
        #   - greeting/conversation_ref/general: 도구 불필요 유형
        #   - required_data=[]: LLM이 도구가 필요 없다고 판단한 모든 경우
        _skip_types = ("greeting", "casual_chat", "conversation_ref", "general")
        _is_light = (question_type in _skip_types or not required_data) and not _force_collect
        if _is_light:
            logger.info(
                f"[3단계파이프라인] 2단계 스킵 "
                f"(type={question_type}, 도구 {len(required_data)}개, LLM 자체 지식으로 답변)"
            )
            collected = {"data": [], "sources": [], "tools_used": [], "sufficient": True}
        else:
            # [2단계] 데이터 수집 + 검증
            logger.info("[3단계파이프라인] === 2단계: 데이터수집 시작 ===")
            _progress("필요한 데이터를 수집하고 있습니다...", "data_collecting")

            collector = DataCollector(
                default_tool_args=default_tool_args,
                progress_callback=_progress,
                raw_user_query=user_query,  # 세이프티넷 키워드 판정용 원문
            )
            collected = collector.collect(analysis)

            logger.info(
                f"[3단계파이프라인] 2단계 완료: "
                f"데이터={len(collected.get('data', []))}건 "
                f"도구={collected.get('tools_used', [])} "
                f"sufficient={collected.get('sufficient', False)}"
            )

        # [3단계] 답변 작성
        # 인사/일반/데이터 미수집 케이스는 light 분기로 진입 메시지·heartbeat 풀을 별도 운영
        # → 인사에 "수집된 데이터로", "📊 표 구성" 류 부적절 메시지 노출 차단
        logger.info("[3단계파이프라인] === 3단계: 답변작성 시작 ===")
        if _is_light:
            if question_type == "greeting":
                _progress("인사 답변을 준비하고 있습니다...", "llm_generating_light")
            else:
                _progress("답변을 작성하고 있습니다...", "llm_generating_light")
        else:
            _progress("수집된 데이터로 답변을 작성하고 있습니다...", "llm_generating")

        farm_info = _build_farm_info_text(farm_id)

        result = generate_answer(
            user_query=full_query,
            analysis_result=analysis,
            collected_result=collected,
            conversation_history=conversation_history,
            farm_name=farm_name,
            farm_info=farm_info,
            speech_style=speech_style,
            progress_callback=_progress,
        )

        total_s = time.time() - t0
        logger.info(f"[3단계파이프라인] 전체 완료: {total_s:.1f}s type={result.get('response_type', '?')}")

        return result

    except Exception as e:
        logger.error(f"[3단계파이프라인] 파이프라인 오류, 기존 Tool Use fallback: {e}")
        logger.error(traceback.format_exc())
        # fallback: 기존 Tool Use 루프로 전환
        logger.info("[3단계파이프라인] fallback → 기존 Tool Use 루프 실행")
        return get_llm_response_with_tools(
            user_query=full_query,
            farm_name=farm_name,
            default_tool_args=default_tool_args,
            conversation_history=conversation_history,
            speech_style=speech_style,
            progress_queue=progress_queue,
        )
