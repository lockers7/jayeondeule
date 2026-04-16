# ════════════════════════════════════════════════════════════════
# LLM 응답 후처리 — 질문 분류, 응답 유형 판정, 재시도 검증, 대화 컨텍스트 구성.
# llm_client.py에서 분리된 순수 헬퍼 + DB 읽기 전용 함수.
# 외부 통신/상태 변경 없음 (get_llm_response_with_tools 보조 계층).
# --->
# _emit_question_log_once: 질문 상세 로그 (호출당 1회)
# _determine_response_type: 응답 유형 (knowledge/control/general/web) 판정
# _build_structured_result: 최종 응답 dict 구성
# _filter_greeting_turns: 인사/잡담 대화 턴 필터링
# _is_conversational_query: 일반 대화 판별 (regex)
# _build_farm_info_text: 농장 기본정보 텍스트 구성 (DB 읽기)
# _check_answer_retry: LLM 응답 검증 + 재시도 결정
# _build_conversation_context: 하이브리드 대화 컨텍스트 messages에 주입
# ════════════════════════════════════════════════════════════════
import re
from typing import Any, Dict, List, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.utils import GREETING_RE as _GREETING_RE

logger = setup_logger(__name__)

def _emit_question_log_once(
    user_query: str,
    farm_name: Optional[str],
    max_tool_iterations: int,
    tools_count: int,

# ═══════════════════════════════════════
# 질문 상세 로그는 호출당 1회만 출력한다.
# ═══════════════════════════════════════
) -> None:
    if not is_true(os.getenv("LLM_VERBOSE_QUESTION_LOG", "true")):
        return

    raw_query = user_query or ""
    logger.debug(
        f"[질문상세] tools={tools_count} max_iter={max_tool_iterations} "
        f"farm={farm_name or '-'} query_len={len(raw_query)}"
    )




# ═════════════════════════════════════════════════════════════
# 도구 결과 정제 (tool_result → LLM 메시지 추가 전 지능형 축약)
# ═════════════════════════════════════════════════════════════




# ════════════════════════════════════
# 사용된 도구 목록으로 응답 유형 결정.
# ════════════════════════════════════
def _determine_response_type(tools_used: List[str]) -> str:
    if "search_web" in tools_used or "fetch_url_content" in tools_used:
        return "web_search"
    if "get_farm_realtime_data" in tools_used:
        return "farm_data"
    if "search_farm_knowledge" in tools_used:
        return "knowledge"
    return "general"


# ════════════════════════
# 구조화된 응답 결과 생성.
# ════════════════════════
def _build_structured_result(
    response_text: str,
    sources: list,
    tools_used: list,
) -> Dict[str, Any]:
    # 출처 URL 기반 중복 제거 (동일 URL 최초 1건만 유지)
    deduped_sources: list = []
    seen_urls: set = set()
    for src in (sources or []):
        url = (src.get("url") or "").strip()
        if url and url not in seen_urls:
            seen_urls.add(url)
            deduped_sources.append(src)
        elif not url:
            deduped_sources.append(src)

    return {
        "response": response_text,
        "sources": deduped_sources,
        "tools_used": tools_used if tools_used else [],
        "response_type": _determine_response_type(tools_used),
    }


# ════════════════════════════════════════════════════════
# 인사/잡담만으로 구성된 턴 쌍(user+assistant)을 제외한다.
# ════════════════════════════════════════════════════════
def _filter_greeting_turns(history: List[Dict[str, str]]) -> List[Dict[str, str]]:
    filtered = []
    i = 0
    while i < len(history):
        turn = history[i]
        role = turn.get("role", "")
        content = turn.get("content", "").strip()

        # user 메시지가 짧고(30자 미만) 인사 패턴에 매칭되면 해당 쌍 스킵
        if (
            role == "user"
            and len(content) < 30
            and _GREETING_RE.search(content)
            and i + 1 < len(history)
            and history[i + 1].get("role") == "assistant"
        ):
            i += 2  # user + assistant 쌍 건너뜀
            continue

        filtered.append(turn)
        i += 1
    return filtered


# ═════════════════════════════════════════════════
# 일반 대화 여부 판단 (순수 대화 vs 도구 필요 요청)
# ═════════════════════════════════════════════════
_CONVERSATIONAL_EXTRA_RE = re.compile(
    r"^(맞아|그렇구나|알겠어|알겠습니다|응|넵|네|오케이|오케|ㅎㅎ|ㅋㅋ|ㄱㄱ"
    r"|잘됐|잘됐네|좋네|좋겠다|다행|아 그래|그렇군|그렇구|알았어|이해"
    r"|그랬군|저런|힘드셨겠다|괜찮아|괜찮으세요)"
)
_PREV_CONV_REF_WORDS = ("아까", "방금", "이전에", "그때 뭐", "지난번", "이전 대화", "아까 말한", "방금 말한")


def _is_conversational_query(query: str) -> bool:
    """요구/지시가 아닌 순수 일반 대화인지 판단한다.
    True: 인사·감탄·짧은 반응·이전 대화 참조 등 → 직전 대화 맥락 포함 가능
    False(기본): 데이터 조회·장치 제어·정보 요청 등 → 최신 도구 데이터 우선, assistant 맥락 불포함
    """
    q = (query or "").strip()
    if not q:
        return True
    # 인사 패턴 (기존 GREETING_RE)
    if len(q) <= 30 and _GREETING_RE.search(q):
        return True
    # 추가 감탄/반응 패턴 (짧은 경우만)
    if len(q) <= 20 and _CONVERSATIONAL_EXTRA_RE.search(q):
        return True
    # 이전 대화 참조 질문 ("아까 뭐라고 했어?", "방금 말한 온도가 뭐야?")
    if any(ref in q for ref in _PREV_CONV_REF_WORDS):
        return True
    return False


# ═════════════════════════════════════════════════════════════════════
# 농장 기본 정보 텍스트 생성
# DB에서 농장/재배사 정보를 조회하여 system prompt에 삽입할 텍스트 생성
# Returns: str | None: 농장 정보 텍스트
# ═════════════════════════════════════════════════════════════════════
def _build_farm_info_text() -> str:
    try:
        from agri_ai_core.src.postgresql.reader import read_farm_house_list
        from agri_ai_core.src.postgresql.connection import db_session

        # 농장 기본 정보 (주요 재배 작물, 주소 포함)
        with db_session() as db:
            farms = db.fetch_all(
                "SELECT f.farm_id, f.farm_name, f.addr, "
                "c.code_name AS main_crop, f.rmks "
                "FROM FARM_M_INFO f "
                "LEFT JOIN CODE_M_INFO c ON c.code_id = 'main_prdt' AND c.code_item = f.main_prdt "
                "WHERE f.farm_id != 0",
                as_dict=True,
            )

        if not farms:
            return None

        lines = []
        for farm in farms:
            lines.append(f"- 농장명: {farm.get('farm_name', '-')}")
            if farm.get("main_crop"):
                lines.append(f"- 주요 재배 작물: {farm['main_crop']}")
            if farm.get("addr"):
                lines.append(f"- 주소: {farm['addr']}")
            if farm.get("rmks"):
                lines.append(f"- 비고: {farm['rmks']}")

        # 재배사 목록
        house_list = read_farm_house_list()
        if house_list:
            house_names = [h.get("hous_name", "") for h in house_list]
            lines.append(f"- 재배사: {', '.join(house_names)}")

        return "\n".join(lines) if lines else None
    except Exception as e:
        logger.debug(f"[농장정보] 조회 실패: {e}")
        return None

def _check_answer_retry(
    final_answer: str, user_query: str, tools_used: List[str],
    iteration: int, max_iterations: int, done_reason: str,
    had_tools: bool, retry_state: dict,
) -> Optional[str]:
    """LLM 답변을 검증하고, 재시도가 필요하면 재시도 메시지를 반환. 불필요하면 None.
    retry_state: 각 유형별 중복 방지 플래그 딕셔너리 (호출자에서 관리)
    """
    _stripped = final_answer.strip()
    _can_retry = iteration < max_iterations - 1

    # 1) 1차 반복 토큰 한도 도달 → 도구 사용 강제
    if iteration == 0 and done_reason == "length" and had_tools:
        _relay_kws = ("반대로", "반전", "셋팅", "설정", "제어", "켜", "꺼", "가동", "중지")
        if any(kw in user_query for kw in _relay_kws):
            msg = ("릴레이 제어 요청은 반드시 control_relay 도구를 호출해야 합니다. "
                   "이전 대화의 답변을 복사하지 마세요. "
                   "먼저 get_farm_realtime_data(data_type='all', house_id='1')로 현재 상태를 확인하고, "
                   "control_relay로 실제 제어를 수행하세요.")
        else:
            msg = ("위 요청을 처리하려면 반드시 도구를 호출해야 합니다. "
                   "직접 답변하지 말고 적절한 도구를 호출하세요.")
        logger.warning(f"[Tool Use] 1차 반복 토큰한도(length) → 도구 강제 재시도")
        return msg

    # 2) 삭제 의도 감지 + delete 미호출
    _delete_phrases = ("삭제", "지웠", "제거", "지울 수 없", "찾을 수 없어 삭제")
    if (any(p in _stripped for p in _delete_phrases)
            and "delete_farm_knowledge" not in tools_used
            and _can_retry and not retry_state.get("delete")):
        retry_state["delete"] = True
        logger.warning(f"[Tool Use] 삭제 의도 감지 + delete 미호출 (반복{iteration + 1}) → 재시도")
        return f"반드시 delete_farm_knowledge 도구를 호출하여 삭제를 실행하세요. 원래 요청: \"{user_query}\""

    # 3) 학습/파일 내용 감지 + search 미호출
    _knowledge_hints = ("학습", "파일", "문서", "목록", "리스트", ".pdf", ".csv", ".txt", "farm_scope", "자료")
    if (any(kw in _stripped for kw in _knowledge_hints)
            and "search_farm_knowledge" not in tools_used
            and "delete_farm_knowledge" not in tools_used
            and _can_retry and not retry_state.get("knowledge")):
        retry_state["knowledge"] = True
        logger.warning(f"[Tool Use] 학습/파일 내용 감지 + search 미호출 (반복{iteration + 1}) → 재시도")
        return (f"반드시 search_farm_knowledge 도구를 호출하여 실제 데이터를 검색한 후 답변하세요. "
                f"원래 요청: \"{user_query}\"")

    # 4) 릴레이 제어 답변 + control_relay 미호출
    _relay_done = ("설정했어요", "설정했습니다", "제어했어요", "제어했습니다", "완료했어요", "완료했습니다",
                   "변경했어요", "변경했습니다", "반전했어요", "반전했습니다", "전환했어요", "전환했습니다",
                   "켜드렸어요", "꺼드렸어요", "켰어요", "껐어요", "켜줬어요", "꺼줬어요",
                   "켜드렸습니다", "꺼드렸습니다", "성공적으로 켜", "성공적으로 꺼")
    if (any(p in _stripped for p in _relay_done)
            and "control_relay" not in tools_used
            and _can_retry and not retry_state.get("relay")):
        retry_state["relay"] = True
        logger.warning(f"[Tool Use] 릴레이 답변 + control_relay 미호출 (반복{iteration + 1}) → 재시도")
        return f"이전 답변을 복사하지 말고, 반드시 control_relay 도구를 호출하세요. 원래 요청: \"{user_query}\""

    # 5) 도구 결과 raw 덤프 (JSON 그대로 출력)
    if (_stripped.startswith('{"content":')
            and "get_farm_realtime_data" in tools_used
            and "control_relay" not in tools_used
            and _can_retry and not retry_state.get("dump")):
        retry_state["dump"] = True
        logger.warning(f"[Tool Use] raw 덤프 감지 (반복{iteration + 1}) → 재시도")
        return f"도구 결과를 그대로 출력하지 말고 한국어로 자연스럽게 설명하세요. 원래 요청: \"{user_query}\""

    # 6) JSON 형식 응답
    if _stripped.startswith("{") and _stripped.endswith("}") and _can_retry:
        try:
            if isinstance(json.loads(_stripped), dict) and not retry_state.get("json"):
                retry_state["json"] = True
                logger.warning(f"[Tool Use] JSON 응답 감지 (반복{iteration + 1}) → 자연어 재생성")
                return f"JSON이 아닌 한국어 문장으로 답변하세요. 원래 요청: \"{user_query}\""
        except (json.JSONDecodeError, TypeError):
            pass

    # 7) 도구 호출 후 짧은 답변 (대기 문구)
    if (tools_used and len(_stripped) < 80 and _can_retry
            and not _stripped.startswith("|") and not retry_state.get("short")):
        retry_state["short"] = True
        logger.warning(f"[Tool Use] 짧은 답변 감지 (반복{iteration + 1}, {len(_stripped)}자) → 재시도")
        return (f"도구 결과가 이미 제공되었습니다. 대기 문구 없이 바로 답변하세요. "
                f"정보 부족 시 search_web으로 추가 검색하세요. 원래 요청: \"{user_query}\"")

    return None  # 재시도 불필요


def _build_conversation_context(messages: list, conversation_history: list, user_query: str):
    """하이브리드 대화 컨텍스트를 messages 리스트에 주입.
    - system 메시지(관련 과거 대화): 400자 제한, 참고용 명시
    - 최근 턴: system role로 묶어 참고용 맥락 주입 (user/assistant role 오염 방지)
    - 요구/지시 쿼리: assistant 이전 응답 제외 (최신 도구 데이터 우선)
    - 유사 중복 턴 자동 제거
    """
    system_context = [t for t in conversation_history if t.get("role") == "system"]
    actual_turns = [t for t in conversation_history if t.get("role") != "system"]
    filtered_turns = _filter_greeting_turns(actual_turns)
    skipped = len(actual_turns) - len(filtered_turns)

    # 관련 과거 대화 주입
    for ctx in system_context:
        content = ctx.get("content", "")[:400]
        if len(ctx.get("content", "")) > 400:
            content += "..."
        messages.append({"role": "system", "content": f"[이전 대화 요약 - 참고용, 답변 근거로 사용 금지]\n{content}"})

    # 쿼리 유형 판단
    _user_query_stripped = (user_query or "").strip()
    _user_refs_number = bool(re.search(r'\d+번', _user_query_stripped))
    _is_conv = _is_conversational_query(user_query)
    if not _is_conv:
        logger.info("[멀티턴] 요구/지시 쿼리 감지 → assistant 이전 맥락 제외 (최신 데이터 우선)")

    # 최근 턴 필터링 및 조립
    _context_parts = []
    _skip_next_assistant = False
    _prev_assistant_prefix = ""
    _dedup_count = 0

    for turn in filtered_turns:
        role, content = turn.get("role", "user"), turn.get("content", "")

        # 빈/실패 assistant 응답 제거
        if role == "assistant":
            if not content.strip():
                _skip_next_assistant = False
                continue
            if len(content.strip()) < 30 and content.strip().rstrip(".") in ("확인이 필요합니다", "확인이 필요해요", "정보가 없습니다"):
                _skip_next_assistant = False
                continue

        # 중복 user 턴 대응 assistant 스킵
        if _skip_next_assistant and role == "assistant":
            _skip_next_assistant = False
            continue

        # 현재 질문과 동일한 과거 user 턴 제거
        if role == "user" and content.strip() == _user_query_stripped:
            _skip_next_assistant = True
            continue

        # 직전 대화 내 연속 동일 user 질문 제거
        if role == "user" and _context_parts:
            _last = next((cp[5:] for cp in reversed(_context_parts) if cp.startswith("사용자: ")), None)
            if _last and _last.strip()[:60] == content.strip()[:60]:
                _skip_next_assistant = True
                _dedup_count += 1
                continue

        _skip_next_assistant = False

        # 유사 assistant 답변 중복 제거 (앞 150자 80% 이상 유사)
        if role == "assistant" and len(content) > 80:
            _cur_prefix = content.strip()[:150]
            if _prev_assistant_prefix and _cur_prefix:
                _common = sum(1 for a, b in zip(_prev_assistant_prefix, _cur_prefix) if a == b)
                _max_len = max(len(_prev_assistant_prefix), len(_cur_prefix))
                if _max_len > 0 and _common / _max_len > 0.8:
                    removed = min(2, len(_context_parts))
                    for _ in range(removed):
                        _context_parts.pop()
                    _dedup_count += 1
            _prev_assistant_prefix = _cur_prefix

        # assistant 컨텐츠 처리
        if role == "assistant":
            if not _is_conv:
                continue  # 요구/지시: assistant 이전 응답 전체 제외
            # 릴레이 제어 결과는 내용 대체
            _relay_indicators = ("릴레이", "AI 환경 판단", "AI 권장", "반대로")
            _done_indicators = ("설정했어요", "변경했어요", "제어했어요", "반전했어요", "전환했어요",
                                "설정했습니다", "변경했습니다", "제어했습니다",
                                "켜드렸어요", "꺼드렸어요", "켰어요", "껐어요", "켜줬어요", "꺼줬어요",
                                "켜드렸습니다", "꺼드렸습니다", "성공적으로 켜", "성공적으로 꺼")
            if any(i in content for i in _relay_indicators) and any(i in content for i in _done_indicators):
                content = "(이전 제어 완료)"
            else:
                _has_list = bool(
                    re.search(r'\d+[\.\)]\s*\*{0,2}\S+\.(pdf|txt|csv|json|md)', content)
                    or re.search(r'\|\s*\d+\s*\|.*\.(pdf|txt|csv|json|md)', content)
                )
                _max_len = 800 if (_has_list or _user_refs_number) else 350
                if len(content) > _max_len:
                    content = content[:_max_len] + "..."
        elif role == "user" and len(content) > 400:
            content = content[:400] + "..."

        _context_parts.append(f"{'사용자' if role == 'user' else 'AI'}: {content}")

    if _dedup_count:
        logger.info(f"[멀티턴] 유사 답변 중복 {_dedup_count}건 제거 완료")

    if _context_parts:
        _prev_context = "\n".join(_context_parts)
        if _is_conv:
            _header = (
                "[직전 대화 맥락 - 대화 연속성 참고용]\n"
                "아래는 직전 대화예요. 현재 질문이 직전 대화와 자연스럽게 이어지는 경우(예: '그럼', '그래서', '또', '다른') 맥락을 이어서 답변하세요.\n"
                "중요: 이 맥락은 참고용이며, 파일/학습/자료/문서/데이터 관련 질문에는 반드시 search_farm_knowledge 도구를 사용하세요.\n"
                "이전 대화에서 비슷한 답변이 있더라도, 도구를 다시 호출하여 최신 정보를 검색하세요.\n"
                "이전 답변을 그대로 복사하거나 반복하는 것은 금지합니다.\n"
            )
        else:
            _header = (
                "[직전 대화 흐름 - 사용자 질문 맥락 파악용]\n"
                "아래는 사용자의 이전 질문 흐름이에요. 현재 요청의 맥락(예: '그럼', '그것도')을 파악하는 데만 참고하세요.\n"
                "중요: 반드시 도구를 호출하여 최신 데이터로 응답하세요. 이전 답변 내용은 포함되지 않으므로 절대 추측하거나 복사하지 마세요.\n"
            )
        messages.append({"role": "system", "content": _header + _prev_context})

    logger.info(
        f"[멀티턴] 하이브리드 컨텍스트: 관련대화={len(system_context)}건, "
        f"최근턴={len(filtered_turns)}턴 (인사/잡담 {skipped}턴 제외, messages={len(messages)}개)"
    )

