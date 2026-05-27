# ══════════════════════════════════════════════════════════════════════════════
# AI 모니터링 Agent
#
# ReAct 패턴: LLM 이 도구를 반복 호출하며 자율 모니터링·보고 작성.
# 운영 스케줄 제어(`ai_control.py`)와 *완전 분리*. import 단방향.
#
# 흐름:
#   user_task → 시스템 프롬프트 (도구 목록 포함) + user task 메시지
#   ↓ LLM 응답 = {"thought","tool","args"} 또는 {"thought","final"}
#   ↓ tool 이면 → 도구 실행 → 결과 messages 에 추가 → LLM 재호출 (loop)
#   ↓ final 이면 → 종료
# MAX_STEPS = 8 강제. 같은 tool+args 3회 연속 = 종료.
# 모든 step 은 history 에 기록 → DB 영속.
#
# 컨텍스트 안정화:
#   · AI_CONTROL_NUM_CTX / AI_CONTROL_NUM_PREDICT 환경변수 → num_ctx/num_predict 반영
#   · tool_result LLM 메시지 800자 truncate (history 는 full 보존)
#   · max_steps-2 step 에서 최종 보고 압박 메시지 주입
#   · 연속 빈 응답 2회 → 조기 종료 (무한 재시도 방지)
#   · 조회 도구 최대 2회 제한 (_MAX_READ_TOOL_CALLS) — 3회 이상 시 final 압박
#   · 쓰기 도구(set_relay 등) 성공 직후 즉시 final 압박 주입
# 자율 재스케줄:
#   · final 응답에 next_check_minutes 파싱 → run_agent 반환값에 포함
#   · 범위 클램프: _NCM_MIN=3 ~ _NCM_MAX=60 분
#
# CLI:
#   python -m agri_ai_core.src.control.ai_monitor_agent \
#          --task "1-3 호기 수온 추세 분석" --farm 1
#
# 파일 시작 함수 목록:
#   _call_llm                 : Ollama /api/chat multi-turn 호출
#   _parse_response           : LLM 응답 JSON parse (실패 시 retry 가이드)
#   _execute_tool             : args dict 로 도구 호출 (validation 포함)
#   _detect_loop              : 같은 (tool, args) 3회 연속 감지
#   _trim_tool_msg            : tool_result → LLM 메시지용 요약 (컨텍스트 보호)
#   build_system_prompt       : 시스템 프롬프트 합성 (control_prompt_m DB 조회, 도구 specs 주입)
#   run_agent                 : 메인 ReAct loop
# ══════════════════════════════════════════════════════════════════════════════
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from agri_ai_core.config import get_ollama_url
from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.llm_runtime_guard import (
    LlmCallLockTimeout,
    is_llm_busy,
    llm_activity,
    llm_call_lock,
)
from agri_ai_core.src.utils.http_client import http_json_request
from agri_ai_core.src.ai.tools_agent_read import (
    TOOL_REGISTRY as _READ_TOOLS,
    tool_specs_text as _read_tool_specs_text,
)
from agri_ai_core.src.ai.tools_agent_write import (
    TOOL_REGISTRY as _WRITE_TOOLS,
    tool_specs_text as _write_tool_specs_text,
)
from agri_ai_core.src.ai.tools_agent_external import (
    TOOL_REGISTRY as _EXTERNAL_TOOLS,
    tool_specs_text as _external_tool_specs_text,
)

# read + write 도구 merge — _execute_tool 은 write 도구일 때 trigger_type 자동 주입
TOOL_REGISTRY = {**_READ_TOOLS, **_WRITE_TOOLS, **_EXTERNAL_TOOLS}
_WRITE_TOOL_NAMES = set(_WRITE_TOOLS.keys())  # 외부도구는 read-only(미포함)


def tool_specs_text() -> str:
    """ReAct system prompt 의 ${TOOLS} 자리에 들어갈 도구 명세 텍스트."""
    return (
        "[조회 도구 — 안전, 즉시 결과]\n"
        + _read_tool_specs_text()
        + "\n\n[변경 도구 — 30초 취소 큐 + 일일/cooldown 제한]\n"
        + _write_tool_specs_text()
        + "\n" + _external_tool_specs_text()
    )

logger = setup_logger(__name__)

# ────────────────────────────────────────────────────────────────────
# 환경변수 — 모델·timeout·max_steps 모두 외부 조정 가능.
# 미래 모델 교체 (gemma4, qwen3, Claude API) 도 env 만 변경.
# ────────────────────────────────────────────────────────────────────
AGENT_LLM_MODEL  = os.getenv("AGENT_LLM_MODEL",  "gemma3:27b")
AGENT_TIMEOUT    = int(os.getenv("AGENT_TIMEOUT", "240"))   # 한 LLM 호출 timeout
AGENT_LLM_LOCK_WAIT = int(os.getenv("AGENT_LLM_LOCK_WAIT", str(AGENT_TIMEOUT)))
AGENT_MAX_STEPS  = int(os.getenv("AGENT_MAX_STEPS", "8"))
AGENT_LOOP_REPEAT_LIMIT = 3   # 같은 (tool, args) N회 연속 시 loop 감지
_TOOL_RESULT_MSG_CHARS = 800  # LLM 메시지용 tool_result 최대 길이 — history 는 full 보존
_NCM_MIN = 3    # next_check_minutes 최솟값 (분)
_NCM_MAX = 60   # next_check_minutes 최댓값 (분)
# ⛔ 기본값 16384 — 제어(ai_control)·분석기·답변 등 모든 gemma3:27b 소비자와 동일해야
#   한다. 과거 이 기본값만 32768 이라, agent 사이클 후 다음 제어/채팅 호출이 매번 90초
#   모델 리로드를 겪었다(27b 가 16GB VRAM 에 겨우 적재 — 2026-07-19 실측). num_ctx 통일.
AI_CONTROL_NUM_CTX     = int(os.getenv("AGENT_NUM_CTX", os.getenv("AI_CONTROL_NUM_CTX", "16384")))
AI_CONTROL_NUM_PREDICT = int(os.getenv("AGENT_NUM_PREDICT", os.getenv("AI_CONTROL_NUM_PREDICT", "800")))
_MAX_READ_TOOL_CALLS   = 2    # 조회 도구 세션 최대 호출 수 — 초과 시 final 압박 주입
_AGENT_RUNTIME_CONTEXT_MAX_CHARS = int(os.getenv("AGENT_RUNTIME_CONTEXT_MAX_CHARS", "4000"))
_AGENT_RUNTIME_CONTEXT_DECISION_HOURS = int(os.getenv("AGENT_RUNTIME_CONTEXT_DECISION_HOURS", "2"))
_AGENT_RUNTIME_CONTEXT_AGENT_LIMIT = int(os.getenv("AGENT_RUNTIME_CONTEXT_AGENT_LIMIT", "3"))
_AGENT_RUNTIME_CONTEXT_RULE_MIN_FREQ = int(os.getenv("AGENT_RUNTIME_CONTEXT_RULE_MIN_FREQ", "3"))


def _agent_retry_backoffs() -> List[float]:
    raw = os.getenv("AGENT_LLM_RETRY_BACKOFFS", "5,15")
    out: List[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            val = float(part)
        except ValueError:
            continue
        if val > 0:
            out.append(min(val, 60.0))
    return out


def _is_transient_llm_failure(status: int, err: str) -> bool:
    text = (err or "").lower()
    return (
        status in {408, 429, 500, 502, 503, 504}
        or "timeout" in text
        or "timed out" in text
        or "connection refused" in text
        or "server disconnected" in text
        or "connection reset" in text
        or "maximum pending requests" in text
        or "server busy" in text
    )


# ════════════════════════════════════════════════════════════════════
# LLM 호출 (Ollama /api/chat multi-turn)
# ════════════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────────────────────
# Ollama chat — messages 배열 그대로 전달. JSON 응답 강제.
# 반환: assistant 의 content 문자열 (또는 None on error).
# ────────────────────────────────────────────────────────────────────
def _call_llm(messages: List[Dict[str, str]], json_format: bool = True) -> Optional[str]:
    payload = {
        "model": AGENT_LLM_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"num_predict": AI_CONTROL_NUM_PREDICT, "num_ctx": AI_CONTROL_NUM_CTX},
    }
    if json_format:
        payload["format"] = "json"

    url = f"{get_ollama_url()}/api/chat"
    logger.info(
        f"[Agent LLM] 요청 model={AGENT_LLM_MODEL} messages={len(messages)} "
        f"ctx={payload['options']['num_ctx']} timeout={AGENT_TIMEOUT}s"
    )

    backoffs = [0.0] + _agent_retry_backoffs()
    last_status = 0
    last_err = ""
    for attempt, backoff in enumerate(backoffs):
        if backoff > 0:
            logger.warning(
                f"[Agent LLM] transient failure retry {attempt}/{len(backoffs)-1} "
                f"after {backoff:.0f}s"
            )
            time.sleep(backoff)

        # 농장 제어 우선 — 제어(ai_control)가 LLM 사용 중이면 agent 는 제어가 끝날
        #   때까지 양보(대기)하고 빈 시간에만 LLM 작업한다. 단일 Ollama 슬롯 경합·
        #   슬롯 핸드오프 충돌([Errno 22])을 원천 차단하고 제어에 슬롯 우선권 보장.
        _yield_deadline = time.time() + AGENT_LLM_LOCK_WAIT
        _yielded = False
        while is_llm_busy(labels={"ai_control"}, exclude_pid=os.getpid()):
            _yielded = True
            if time.time() >= _yield_deadline:
                logger.info("[Agent LLM] 제어 LLM 장시간 점유 — 양보 대기 한도 도달, 진행")
                break
            time.sleep(2)
        if _yielded:
            logger.info("[Agent LLM] 제어 LLM 비가동 확인 → agent LLM 작업 진행")

        t0 = time.time()
        try:
            with llm_call_lock("agent", wait_sec=AGENT_LLM_LOCK_WAIT):
                with llm_activity("agent", AGENT_TIMEOUT):
                    status, data, err = http_json_request(
                        "POST", url, json_body=payload, timeout=AGENT_TIMEOUT
                    )
        except LlmCallLockTimeout as e:
            status, data, err = 503, None, str(e)
        except Exception as e:
            status, data, err = 500, None, str(e)

        elapsed = time.time() - t0
        last_status, last_err = status, err or ""
        if status == 200 and isinstance(data, dict):
            content = (data.get("message") or {}).get("content")
            if content:
                logger.info(f"[Agent LLM] 응답 ({elapsed:.1f}s, {len(content)}자)")
                return content
            last_err = "empty assistant content"
            logger.warning(f"[Agent LLM] 빈 응답 ({elapsed:.1f}s)")
        else:
            logger.warning(
                f"[Agent LLM] 실패 status={status} ({elapsed:.1f}s) "
                f"err={(err or '')[:160]}"
            )

        if attempt >= len(backoffs) - 1:
            break
        if status == 200 and isinstance(data, dict):
            continue
        if not _is_transient_llm_failure(status, last_err):
            break

    logger.warning(f"[Agent LLM] 최종 실패 status={last_status} err={last_err[:160]}")
    return None


# ────────────────────────────────────────────────────────────────────
# LLM 응답 → dict parse. 실패 시 None.
# ────────────────────────────────────────────────────────────────────
def _parse_response(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    raw = raw.strip()
    # JSON 추출 — 응답이 ```json ``` 같은 코드블록에 싸여올 수 있음
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"[Agent] JSON parse 실패: {e} | raw={raw[:200]!r}")
        return None


# ════════════════════════════════════════════════════════════════════
# 도구 실행
# ════════════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────────────────────
# tool 이름·args 로 도구 호출. 미존재·예외는 dict 형태로 반환 (LLM 이 다음 step 결정).
# ────────────────────────────────────────────────────────────────────
def _execute_tool(tool_name: str, args: Dict[str, Any],
                  trigger_type: str = "user") -> Dict[str, Any]:
    if tool_name not in TOOL_REGISTRY:
        return {"error": f"unknown tool '{tool_name}'. Available: {list(TOOL_REGISTRY.keys())}"}
    fn = TOOL_REGISTRY[tool_name]
    if not isinstance(args, dict):
        return {"error": f"args 는 dict 여야 합니다. got: {type(args).__name__}"}
    # write 도구는 LLM 이 모르는 trigger_type 을 자동 주입.
    # LLM 이 명시했더라도 schedule/user 결정 권한은 호출자(ai_monitor_agent)에 있음.
    call_args = args
    if tool_name in _WRITE_TOOL_NAMES:
        call_args = {**args, "trigger_type": trigger_type}
    try:
        return fn(**call_args)
    except TypeError as e:
        return {"error": f"args 불일치: {e}"}
    except Exception as e:
        logger.warning(f"[Agent] tool '{tool_name}' 실행 예외: {e}")
        return {"error": f"tool 실행 실패: {e}"}


# ────────────────────────────────────────────────────────────────────
# 같은 (tool, args) 가 N회 연속 = loop. agent 가 막힘.
# ────────────────────────────────────────────────────────────────────
def _detect_loop(history: List[Dict[str, Any]]) -> bool:
    recent = [h for h in history[-AGENT_LOOP_REPEAT_LIMIT:] if 'tool' in h]
    if len(recent) < AGENT_LOOP_REPEAT_LIMIT:
        return False
    keys = [(h['tool'], json.dumps(h.get('args', {}), sort_keys=True)) for h in recent]
    return len(set(keys)) == 1


# ────────────────────────────────────────────────────────────────────
# tool_result → LLM 메시지용 dict.
# 길면 핵심 필드(success/error/n/note)만 남기고 preview 로 압축.
# history 에는 항상 원본 full result 를 저장하므로 DB 기록에 영향 없음.
# ────────────────────────────────────────────────────────────────────
def _trim_tool_msg(result: Dict[str, Any]) -> Dict[str, Any]:
    full = json.dumps(result, ensure_ascii=False)
    if len(full) <= _TOOL_RESULT_MSG_CHARS:
        return result
    core = {k: result[k] for k in ("success", "error", "n", "note") if k in result}
    core["_truncated"] = True
    core["_preview"] = full[:_TOOL_RESULT_MSG_CHARS - 80]
    return core


# ════════════════════════════════════════════════════════════════════
# 시스템 프롬프트 합성
# ════════════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────────────────────
# control_prompt_m 의 'CTRL_AGENT_SYSTEM' 을 사용 (DB 단일 소스).
# 도구 목록·최대단계는 ${TOOLS}/${MAX_STEPS} placeholder 로 동적 주입.
# ────────────────────────────────────────────────────────────────────
# 외부정보 조사 임무 판정 — 해당 시 제어프롬프트가 아닌 외부전용 프롬프트로 라우팅.
# (제어 프레이밍이 강해 gemma3 가 외부임무에도 릴레이 순찰로 빠지는 것을 근본 차단.)
_EXTERNAL_TASK_RE = re.compile(
    r"웹\s*검색|검색해|검색하|인터넷|외부\s*정보|외부에서|논문|시세|가격|뉴스|기사|"
    r"기상\s*예보|날씨|병해충|재배\s*기술|재배\s*정보|재배\s*팁|정보를?\s*찾|알아봐|"
    r"조사해|search_web|mcp|arxiv|paper[- ]?search|naver", re.IGNORECASE)


def _is_external_info_task(task: str) -> bool:
    return bool(task and _EXTERNAL_TASK_RE.search(str(task)))


def build_system_prompt(max_steps: int = AGENT_MAX_STEPS, task: str = None) -> str:
    from agri_ai_core.src.prompt_registry import get_control_block
    block_id = 'CTRL_AGENT_EXTERNAL' if _is_external_info_task(task) else 'CTRL_AGENT_SYSTEM'
    block = get_control_block(block_id, TOOLS=tool_specs_text(), MAX_STEPS=str(max_steps))
    if not block and block_id != 'CTRL_AGENT_SYSTEM':   # 외부블록 부재 시 제어블록 폴백
        block = get_control_block('CTRL_AGENT_SYSTEM',
                                  TOOLS=tool_specs_text(), MAX_STEPS=str(max_steps))
    if block:
        return block
    logger.warning("[Agent] 시스템 프롬프트 DB 조회 실패 — 빈 프롬프트 반환")
    return ""


def _short_text(value: Any, limit: int = 160) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _flag_text(value: Any) -> str:
    if value is True:
        return "ON"
    if value is False:
        return "OFF"
    return "-"


def _build_prompt_management_context() -> str:
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as db:
            ctrl = db.fetch_one(
                "SELECT COUNT(*) AS active_count, "
                "       TO_CHAR(MAX(updt_dttm),'YYYY-MM-DD HH24:MI:SS') AS last_update "
                "FROM control_prompt_m WHERE active_yn='Y'"
            ) or {}
            prompt = db.fetch_one(
                "SELECT COUNT(*) AS active_count, "
                "       TO_CHAR(MAX(updt_dttm),'YYYY-MM-DD HH24:MI:SS') AS last_update "
                "FROM prompt_block_m WHERE active_yn='Y'"
            ) or {}
        return (
            "[프롬프트관리/LLM 제어관리]\n"
            f"- control_prompt_m 활성 {int(ctrl.get('active_count') or 0)}건, "
            f"최종수정 {ctrl.get('last_update') or '-'}\n"
            f"- prompt_block_m 활성 {int(prompt.get('active_count') or 0)}건, "
            f"최종수정 {prompt.get('last_update') or '-'}"
        )
    except Exception as e:
        logger.debug(f"[Agent Context] prompt 관리 요약 실패: {e}")
        return ""


def _build_recent_control_decisions_context(farm_id: int) -> str:
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as db:
            rows = db.fetch_all(
                "SELECT TO_CHAR(decided_at,'MM-DD HH24:MI') AS at, house_id, action, "
                "       circulation, water_heater, fog_occurs, drainage_motor, "
                "       LEFT(COALESCE(reason,''), 160) AS reason "
                "FROM ai_decision_log "
                "WHERE farm_id=%s AND decided_at > NOW() - %s::interval "
                "ORDER BY decided_at DESC LIMIT 10",
                (int(farm_id), f"{_AGENT_RUNTIME_CONTEXT_DECISION_HOURS} hours"),
                as_dict=True,
            )
        if not rows:
            return ""
        lines = [
            f"[최근 환경제어 LLM 판단(ai_decision_log, 최근 {_AGENT_RUNTIME_CONTEXT_DECISION_HOURS}시간)]"
        ]
        for r in rows:
            lines.append(
                f"- {r.get('at')} h{r.get('house_id')}: {r.get('action')} "
                f"circ={r.get('circulation') or '-'} "
                f"heater={_flag_text(r.get('water_heater'))} "
                f"fog={_flag_text(r.get('fog_occurs'))} "
                f"drain={_flag_text(r.get('drainage_motor'))} · "
                f"{_short_text(r.get('reason'), 120)}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.debug(f"[Agent Context] 최근 제어결정 요약 실패: {e}")
        return ""


def _build_rule_candidate_context(farm_id: int) -> str:
    try:
        from agri_ai_core.src.control.ai_self_evolve import (
            analyze_decision_patterns, format_candidate_rule,
        )
        patterns = analyze_decision_patterns(
            farm_id=int(farm_id), days=7,
            min_freq=_AGENT_RUNTIME_CONTEXT_RULE_MIN_FREQ,
            top_k=5,
        )
        if not patterns:
            return ""
        lines = [
            f"[룰 후보 요약(rule-candidates, 최근 7일, 최소 {_AGENT_RUNTIME_CONTEXT_RULE_MIN_FREQ}회)]"
        ]
        for p in patterns[:5]:
            rule = format_candidate_rule(p)
            lines.append(
                f"- {rule.get('title')}: {int(rule.get('frequency') or 0)}회 · "
                f"{_short_text(rule.get('content'), 180)}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.debug(f"[Agent Context] 룰 후보 요약 실패: {e}")
        return ""


def _build_recent_agent_history_context(farm_id: int) -> str:
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as db:
            rows = db.fetch_all(
                "SELECT TO_CHAR(COALESCE(ended_at, started_at),'MM-DD HH24:MI') AS at, "
                "       trigger_type, farm_id, success, "
                "       LEFT(COALESCE(final_report, reason, ''), 220) AS summary "
                "FROM agent_decision_log "
                "WHERE farm_id=%s OR farm_id IS NULL "
                "ORDER BY id DESC LIMIT %s",
                (int(farm_id), _AGENT_RUNTIME_CONTEXT_AGENT_LIMIT),
                as_dict=True,
            )
        if not rows:
            return ""
        lines = [f"[최근 Agent 이력(agent-history, {len(rows)}건)]"]
        for r in rows:
            status = "성공" if r.get('success') else "실패"
            scope = f"farm={r.get('farm_id')}" if r.get('farm_id') is not None else "farm=ALL"
            lines.append(
                f"- {r.get('at')} {r.get('trigger_type')} {scope} {status}: "
                f"{_short_text(r.get('summary'), 160)}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.debug(f"[Agent Context] 최근 Agent 이력 요약 실패: {e}")
        return ""


def _build_admin_directive_context(farm_id: int) -> str:
    # 관리자 강제 지시 — agent 가 지시된 장치를 건드리지 않도록 주입.
    # (relay_manager 최종 관문에서도 하드 강제되지만 agent 의 불필요한 시도 자체를 방지)
    try:
        from agri_ai_core.src.control.admin_directive import format_prompt_block
        blocks = []
        for h in (1, 2, 3):
            b = format_prompt_block(farm_id, h)
            if b:
                blocks.append(f"[{h}호] " + b)
        return "\n".join(blocks)
    except Exception:
        return ""


def _build_runtime_context(farm_id: int) -> str:
    sections = []
    for builder in (
        lambda: _build_admin_directive_context(farm_id),
        lambda: _build_prompt_management_context(),
        lambda: _build_recent_control_decisions_context(farm_id),
        lambda: _build_rule_candidate_context(farm_id),
        lambda: _build_recent_agent_history_context(farm_id),
    ):
        block = builder()
        if block:
            sections.append(block)
    if not sections:
        return ""
    context = (
        "[Agent 운영 컨텍스트]\n"
        "이 블록은 관리 화면의 프롬프트/룰/이력 데이터를 자동 요약한 참고자료입니다. "
        "현재 센서·릴레이 도구 결과가 더 최신이면 도구 결과를 우선하세요.\n\n"
        + "\n\n".join(sections)
    )
    if len(context) > _AGENT_RUNTIME_CONTEXT_MAX_CHARS:
        context = context[:_AGENT_RUNTIME_CONTEXT_MAX_CHARS - 1] + "…"
    return context


# ════════════════════════════════════════════════════════════════════
# DB 영속 — agent_decision_log INSERT
# ════════════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────────────────────
# 통계 산출 + DB 기록. 실패해도 agent 결과는 그대로 반환 (DB 가 죽어도 운영 영향 X).
# 반환: INSERT 된 id (또는 None on error).
# ────────────────────────────────────────────────────────────────────
def _persist_agent_log(result: Dict[str, Any], task: str, farm_id: int,
                       trigger_type: str = "user") -> Optional[int]:
    # ⚠ db_session().fetch_all(INSERT...RETURNING) 은 commit 안 됨 —
    # ai_decision_log.record_decision 과 동일한 _getconn() + execute + commit 패턴 사용.
    try:
        from agri_ai_core.src.postgresql.connection import db
        from psycopg2.extras import RealDictCursor

        steps = result.get("steps", [])
        llm_calls = len(steps)
        tool_counts: Dict[str, int] = {}
        for h in steps:
            t = h.get("tool")
            if t:
                tool_counts[t] = tool_counts.get(t, 0) + 1

        vals = (
            trigger_type, farm_id, task,
            json.dumps(steps, ensure_ascii=False, default=str),
            result.get("final"),
            bool(result.get("success", False)),
            result.get("reason"),
            result.get("duration_sec"),
            llm_calls,
            json.dumps(tool_counts),
            AGENT_LLM_MODEL,
        )
        sql = (
            "INSERT INTO agent_decision_log "
            "(ended_at, trigger_type, farm_id, task, steps, final_report, "
            " success, reason, duration_sec, llm_calls, tool_calls, model) "
            "VALUES (NOW(), %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb, %s) "
            "RETURNING id"
        )

        conn = db._getconn()
        if conn is None:
            logger.warning("[Agent DB] connection 획득 실패")
            return None
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, vals)
                row = cur.fetchone()
                conn.commit()
            log_id = int(row['id']) if row and 'id' in row else None
        finally:
            try: db._putconn(conn)
            except Exception: pass

        logger.info(f"[Agent DB] log id={log_id} (trigger={trigger_type}, "
                    f"steps={llm_calls}, tools={tool_counts}, success={result.get('success')})")

        # 이번 사이클이 등록한 agent_pending_actions 의 agent_log_id 채우기
        if log_id is not None:
            try:
                pending_ids = [
                    int(h["tool_result"]["action_id"])
                    for h in steps
                    if isinstance(h.get("tool_result"), dict)
                    and h["tool_result"].get("action_id") is not None
                ]
                if pending_ids:
                    conn2 = db._getconn()
                    if conn2:
                        try:
                            with conn2.cursor() as cur2:
                                cur2.execute(
                                    "UPDATE agent_pending_actions "
                                    "SET agent_log_id=%s WHERE id = ANY(%s)",
                                    (log_id, pending_ids))
                                conn2.commit()
                            logger.info(f"[Agent DB] pending_actions {len(pending_ids)}건에 "
                                        f"agent_log_id={log_id} 연결")
                        finally:
                            try: db._putconn(conn2)
                            except Exception: pass
            except Exception as ee:
                logger.warning(f"[Agent DB] pending_actions agent_log_id 연결 실패: {ee}")

        return log_id
    except Exception as e:
        logger.warning(f"[Agent DB] 기록 실패 (운영 영향 없음): {e}")
        return None


# ════════════════════════════════════════════════════════════════════
# 메인 ReAct loop
# ════════════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────────────────────
# user_task 한 건 처리. 최종 보고 dict 반환:
#   {"success": True,  "final": "...",  "steps": [...], "duration_sec": N, "log_id": ...}
#   {"success": False, "reason": "...", "steps": [...], "duration_sec": N, "log_id": ...}
# trigger_type: 'schedule' (cron) / 'event' / 'user' (default).
# persist_db=False 시 DB INSERT 안 함 (단위테스트용).
# ────────────────────────────────────────────────────────────────────
def run_agent(task: str, farm_id: int = 1, max_steps: int = None,
              trigger_type: str = "user", persist_db: bool = True) -> Dict[str, Any]:
    max_steps = max_steps or AGENT_MAX_STEPS
    t_start = time.time()
    history: List[Dict[str, Any]] = []
    system = build_system_prompt(max_steps=max_steps, task=task)
    runtime_context = _build_runtime_context(farm_id)
    user_parts = [f"농장 ID: {farm_id}"]
    if runtime_context:
        user_parts.extend(["", runtime_context])
        logger.info(f"[Agent Context] runtime context {len(runtime_context)}자 주입")
    user_parts.extend(["", f"작업: {task}"])
    user_msg = "\n".join(user_parts)

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user_msg},
    ]

    logger.info(f"[Agent 시작] farm={farm_id} trigger={trigger_type} task={task!r}")
    _empty_count = 0  # 연속 빈 응답 카운터 — 컨텍스트 포화 조기 감지
    _read_counts: Dict[str, int] = {}  # 조회 도구 세션 호출 횟수 (루프 방지용)

    for step in range(max_steps):
        raw = _call_llm(messages, json_format=True)

        # 빈 응답 추적 (None 또는 "" 모두 컨텍스트 포화 신호)
        if not raw:
            _empty_count += 1
            logger.warning(f"[Agent step {step}] 빈 응답 {_empty_count}회 연속")
            if _empty_count >= 2:
                duration = time.time() - t_start
                logger.warning(f"[Agent] 빈 응답 {_empty_count}회 → 조기 종료 (컨텍스트 포화 추정)")
                result = {"success": False,
                          "reason": f"연속 빈 응답 {_empty_count}회 (컨텍스트 포화)",
                          "steps": history, "duration_sec": round(duration, 2)}
                if persist_db:
                    result["log_id"] = _persist_agent_log(result, task, farm_id, trigger_type)
                return result
        else:
            _empty_count = 0

        parsed = _parse_response(raw)

        if parsed is None:
            # JSON parse 실패 — 한 번 더 가이드 주고 retry
            logger.warning(f"[Agent step {step}] JSON parse 실패, 가이드 후 retry")
            messages.append({"role": "assistant", "content": raw or "(빈 응답)"})
            messages.append({"role": "user",
                "content": "응답이 유효한 JSON 이 아닙니다. 다음 형식 중 하나로 한 객체만 반환하세요:\n"
                           '도구 호출: {"thought":"...", "tool":"...", "args":{...}}\n'
                           '최종 보고: {"thought":"...", "final":"..."}'})
            history.append({"step": step, "error": "json_parse_fail", "raw": (raw or "")[:300]})
            continue

        history.append({"step": step, **parsed})

        # LLM 이 "final" 대신 다른 키를 사용한 경우 정규화 (answer/result/report/conclusion 등)
        if "final" not in parsed and "tool" not in parsed:
            _ALT_FINAL_KEYS = ("answer", "result", "response", "report",
                               "conclusion", "summary", "output")
            for _alt in _ALT_FINAL_KEYS:
                if _alt in parsed:
                    _val = parsed.pop(_alt)
                    parsed["final"] = _val
                    history[-1].pop(_alt, None)
                    history[-1]["final"] = _val
                    logger.info(f"[Agent step {step}] '{_alt}' → 'final' 정규화")
                    break
            else:
                # alt 키도 없으면 — thought 가 100자 이상이면 최종 보고로 처리
                _thought = parsed.get("thought", "")
                if len(_thought) > 100:
                    parsed["final"] = _thought
                    history[-1]["final"] = _thought
                    logger.info(f"[Agent step {step}] thought({len(_thought)}자) → final 대체 처리")

        # final → 종료
        if "final" in parsed:
            duration = time.time() - t_start
            # next_check_minutes 파싱 + 클램프 (자율 재스케줄)
            ncm = parsed.get("next_check_minutes")
            if ncm is not None:
                try:
                    ncm = max(_NCM_MIN, min(_NCM_MAX, int(ncm)))
                except (TypeError, ValueError):
                    ncm = None
            logger.info(
                f"[Agent 완료] step={step} duration={duration:.1f}s "
                f"next_check={ncm}min final={parsed['final'][:80]!r}"
            )
            result = {"success": True, "final": parsed["final"], "steps": history,
                      "duration_sec": round(duration, 2), "next_check_minutes": ncm}
            if persist_db:
                result["log_id"] = _persist_agent_log(result, task, farm_id, trigger_type)
            return result

        # tool 호출
        tool_name = parsed.get("tool")
        args = parsed.get("args", {})
        if not tool_name:
            messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
            messages.append({"role": "user",
                "content": '응답에 "tool" 또는 "final" 중 하나가 반드시 있어야 합니다.'})
            continue

        # loop 감지
        if _detect_loop(history):
            duration = time.time() - t_start
            logger.warning(f"[Agent 종료] loop 감지 (같은 도구 {AGENT_LOOP_REPEAT_LIMIT}회 연속)")
            result = {"success": False, "reason": f"loop 감지: {tool_name}", "steps": history,
                      "duration_sec": round(duration, 2)}
            if persist_db:
                result["log_id"] = _persist_agent_log(result, task, farm_id, trigger_type)
            return result

        # 조회 도구 세션 호출 횟수 제한 — 초과 시 도구 실행 없이 final 압박
        if tool_name not in _WRITE_TOOL_NAMES:
            _read_counts[tool_name] = _read_counts.get(tool_name, 0) + 1
            if _read_counts[tool_name] > _MAX_READ_TOOL_CALLS:
                logger.warning(
                    f"[Agent step {step}] '{tool_name}' 세션 {_read_counts[tool_name]}회 호출 — 제한 초과, final 압박 주입"
                )
                messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
                messages.append({"role": "user",
                    "content": (
                        f"'{tool_name}'은 이미 {_read_counts[tool_name] - 1}회 조회되었습니다. "
                        "추가 수집 없이 지금 바로 set_relay 로 제어하거나 최종 보고서를 작성하세요.\n"
                        '형식: {"thought":"결론","final":"한국어 보고","next_check_minutes":N}'
                    )})
                history[-1]["_skipped"] = f"read_limit_{tool_name}"
                continue

        result = _execute_tool(tool_name, args, trigger_type=trigger_type)
        history[-1]["tool_result"] = result  # history 에는 항상 full result

        messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
        # LLM 메시지에는 truncate 버전 — 컨텍스트 보호 (history full 은 유지)
        messages.append({"role": "user",
            "content": json.dumps({"tool_result": _trim_tool_msg(result)}, ensure_ascii=False)})

        # 쓰기 도구 성공 직후 즉시 final 압박 — 컨텍스트 추가 소모 없이 보고 유도
        if tool_name in _WRITE_TOOL_NAMES and result.get("success"):
            logger.info(f"[Agent step {step}] '{tool_name}' 성공 → final 즉시 압박 주입")
            messages.append({
                "role": "user",
                "content": (
                    "제어가 완료되었습니다. 지금까지 수집·제어한 내용을 바탕으로 즉시 최종 보고서를 작성하세요.\n"
                    '형식: {"thought":"결론 사유","final":"한국어 최종 보고","next_check_minutes":N}'
                ),
            })
        # max_steps-2 step 완료 후 최종 보고 압박 — 다음(마지막) LLM 호출에서 final 유도
        elif step == max_steps - 2:
            messages.append({
                "role": "user",
                "content": (
                    "이것이 마지막 데이터 수집입니다. "
                    "지금까지 수집한 정보로 즉시 최종 보고를 작성하세요.\n"
                    '형식: {"thought":"결론 사유","final":"한국어 최종 보고","next_check_minutes":N}'
                ),
            })

    duration = time.time() - t_start
    logger.warning(f"[Agent 종료] MAX_STEPS({max_steps}) 초과")
    result = {"success": False, "reason": "MAX_STEPS exceeded", "steps": history,
              "duration_sec": round(duration, 2)}
    if persist_db:
        result["log_id"] = _persist_agent_log(result, task, farm_id, trigger_type)
    return result


# ════════════════════════════════════════════════════════════════════
# CLI 진입점
# ════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Agent monitor CLI")
    parser.add_argument("--task", required=True, help="agent 가 수행할 작업 (한국어)")
    parser.add_argument("--farm", type=int, default=1, help="농장 ID")
    parser.add_argument("--max-steps", type=int, default=AGENT_MAX_STEPS)
    parser.add_argument("--json", action="store_true", help="결과를 JSON 으로만 출력")
    args = parser.parse_args()

    result = run_agent(task=args.task, farm_id=args.farm, max_steps=args.max_steps)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*70}")
        print(f"Agent 결과: success={result['success']} duration={result.get('duration_sec')}s steps={len(result['steps'])}")
        print(f"{'='*70}\n")
        if result.get("final"):
            print("📋 최종 보고:")
            print(result["final"])
        else:
            print(f"⚠ 실패: {result.get('reason')}")
        print(f"\n--- Step history ---")
        for h in result["steps"]:
            print(f"  [{h.get('step')}] thought={h.get('thought','')[:60]!r}", end="")
            if 'tool' in h:
                print(f" tool={h['tool']}({h.get('args')})")
            elif 'final' in h:
                print(f" final=...")
            elif 'error' in h:
                print(f" ERROR={h['error']}")
            else:
                print()
