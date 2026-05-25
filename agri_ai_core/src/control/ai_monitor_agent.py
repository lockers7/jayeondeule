# ══════════════════════════════════════════════════════════════════════════════
# AI 모니터링 Agent (Phase 1) [2026-05-25 신규]
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
# 모든 step 은 history 에 기록 → DB 영속 (Phase 2 에서 추가).
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
#   build_system_prompt       : 시스템 프롬프트 합성 (도구 specs 주입)
#   run_agent                 : 메인 ReAct loop
# ══════════════════════════════════════════════════════════════════════════════
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from agri_ai_core.config import get_ollama_url
from agri_ai_core.logs import setup_logger
from agri_ai_core.src.utils.http_client import http_json_request
from agri_ai_core.src.ai.tools_agent_read import TOOL_REGISTRY, tool_specs_text

logger = setup_logger(__name__)

# ────────────────────────────────────────────────────────────────────
# 환경변수 — 모델·timeout·max_steps 모두 외부 조정 가능.
# 미래 모델 교체 (gemma4, qwen3, Claude API) 도 env 만 변경.
# ────────────────────────────────────────────────────────────────────
AGENT_LLM_MODEL  = os.getenv("AGENT_LLM_MODEL",  "gemma3:27b")
AGENT_TIMEOUT    = int(os.getenv("AGENT_TIMEOUT", "120"))   # 한 LLM 호출 timeout
AGENT_MAX_STEPS  = int(os.getenv("AGENT_MAX_STEPS", "8"))
AGENT_LOOP_REPEAT_LIMIT = 3   # 같은 (tool, args) N회 연속 시 loop 감지


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
        "options": {"num_predict": 800, "num_ctx": 16384},
    }
    if json_format:
        payload["format"] = "json"

    url = f"{get_ollama_url()}/api/chat"
    logger.info(f"[Agent LLM] 요청 model={AGENT_LLM_MODEL} messages={len(messages)} ctx={payload['options']['num_ctx']}")
    t0 = time.time()
    try:
        status, data, err = http_json_request("POST", url, json_body=payload, timeout=AGENT_TIMEOUT)
    except Exception as e:
        logger.warning(f"[Agent LLM] HTTP 예외: {e}")
        return None

    elapsed = time.time() - t0
    if status != 200 or not isinstance(data, dict):
        logger.warning(f"[Agent LLM] 실패 status={status} err={err}")
        return None
    content = (data.get("message") or {}).get("content")
    logger.info(f"[Agent LLM] 응답 ({elapsed:.1f}s, {len(content or '')}자)")
    return content


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
def _execute_tool(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if tool_name not in TOOL_REGISTRY:
        return {"error": f"unknown tool '{tool_name}'. Available: {list(TOOL_REGISTRY.keys())}"}
    fn = TOOL_REGISTRY[tool_name]
    if not isinstance(args, dict):
        return {"error": f"args 는 dict 여야 합니다. got: {type(args).__name__}"}
    try:
        return fn(**args)
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


# ════════════════════════════════════════════════════════════════════
# 시스템 프롬프트 합성
# ════════════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────────────────────
# prompt_block_m 에 'AGENT_MONITOR_SYSTEM' 이 있으면 사용, 없으면 inline 폴백.
# 도구 목록은 동적으로 주입 (TOOL_SPECS 변경 시 자동 반영).
# ────────────────────────────────────────────────────────────────────
_INLINE_SYSTEM = """/no_think
당신은 자연들에 농장의 스마트팜 모니터링 에이전트입니다.

역할:
- 호기(1-1, 1-2, 1-3 등)의 센서·릴레이·LLM 결정 이력을 자율 분석
- 위험 추세(수온/내부온도/CO2/습도) 선제 감지
- 호기 간 비교로 이상치 검출
- 최종 보고는 한국어, 운영자가 즉시 이해 가능한 수준

사용 가능 도구:
{TOOLS}

응답 형식 (반드시 JSON 한 객체. 다른 텍스트 금지):
  도구 호출:    {{"thought": "왜 이 도구가 필요한지", "tool": "<도구명>", "args": {{...}}}}
  최종 보고:    {{"thought": "결론에 도달한 사고", "final": "한국어 보고 본문"}}

규칙:
- 한 응답에 정확히 thought + (tool/args 또는 final) 만 포함
- args 는 도구 명세에 정의된 키만 사용
- 최대 {MAX_STEPS}단계 안에 final 도달
- 같은 도구를 같은 args 로 3회 연속 호출 금지
"""


def build_system_prompt(max_steps: int = AGENT_MAX_STEPS) -> str:
    # DB 의 prompt_block_m 우선 시도 — 운영자가 web UI 로 수정 가능
    try:
        from agri_ai_core.src.prompt_registry import get_block
        db_block = get_block('AGENT_MONITOR_SYSTEM',
                             TOOLS=tool_specs_text(), MAX_STEPS=str(max_steps))
        if db_block:
            return db_block
    except Exception as e:
        logger.debug(f"[Agent] DB block read 실패 (inline fallback): {e}")
    return _INLINE_SYSTEM.format(TOOLS=tool_specs_text(), MAX_STEPS=max_steps)


# ════════════════════════════════════════════════════════════════════
# DB 영속 — agent_decision_log INSERT
# ════════════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────────────────────
# 통계 산출 + DB 기록. 실패해도 agent 결과는 그대로 반환 (DB 가 죽어도 운영 영향 X).
# 반환: INSERT 된 id (또는 None on error).
# ────────────────────────────────────────────────────────────────────
def _persist_agent_log(result: Dict[str, Any], task: str, farm_id: int,
                       trigger_type: str = "user") -> Optional[int]:
    # [2026-05-01 패턴 준수] db_session().fetch_all(INSERT...RETURNING) 은 commit 안 됨 —
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
    system = build_system_prompt(max_steps=max_steps)
    user_msg = f"농장 ID: {farm_id}\n\n작업: {task}"

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user_msg},
    ]

    logger.info(f"[Agent 시작] farm={farm_id} trigger={trigger_type} task={task!r}")

    for step in range(max_steps):
        raw = _call_llm(messages, json_format=True)
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

        # final → 종료
        if "final" in parsed:
            duration = time.time() - t_start
            logger.info(f"[Agent 완료] step={step} duration={duration:.1f}s final={parsed['final'][:80]!r}")
            result = {"success": True, "final": parsed["final"], "steps": history,
                      "duration_sec": round(duration, 2)}
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

        result = _execute_tool(tool_name, args)
        history[-1]["tool_result"] = result

        messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
        messages.append({"role": "user",
            "content": json.dumps({"tool_result": result}, ensure_ascii=False)})

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
