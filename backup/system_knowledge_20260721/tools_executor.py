# ══════════════════════════════════════════════════════════════════════════════
# LLM Tool 실행기 (라우터) — LLM이 요청한 도구를 적절한 모듈로 dispatch.
# 실제 구현은 tools_data.py(데이터), tools_control.py(제어),
# tools_search.py(웹검색) 등에 분산되어 있다.
# --->
# execute_tool: tool_name에 따라 적절한 함수로 dispatch 후 JSON 문자열 반환
# ══════════════════════════════════════════════════════════════════════════════
import json
import time
import traceback
from typing import Dict, Any

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.tools_utils import json_default as _json_default

# 도구 구현 모듈 (모두 L5 동급 계층)
from agri_ai_core.src.ai.tools_data import (
    delete_farm_knowledge,
    search_farm_knowledge,
    get_farm_realtime_data,
    get_weather_forecast,
)
from agri_ai_core.src.ai.tools_control import (
    control_relay,
    control_relays_batch,
    _control_relay_all_houses,
)
from agri_ai_core.src.ai.tools_search import search_web, fetch_url_content
from agri_ai_core.src.ai.tools_external_api import call_external_api, manage_external_api
from agri_ai_core.src.ai.chat_lessons import manage_analysis_lesson
from agri_ai_core.src.ai.tools_source import source_list, source_search, source_read
# 관리 도구 — 제어 모드/생육단계/순환모드/스케줄/임계값/시스템상태
from agri_ai_core.src.ai.tools_db import (
    db_list_tables,
    db_describe_table,
    db_read_query,
    db_write_query,
)
from agri_ai_core.src.ai.tools_admin import (
    manage_control_prompt,
    set_admin_directive,
    release_admin_directive,
    set_house_control_mode,
    set_growth_stage,
    set_circulation_mode,
    set_schedule,
    override_ai_thresholds,
)
# Agent 모니터링 — schedule_monitor / list_monitors / cancel_monitor
from agri_ai_core.src.ai.tools_agent import (
    schedule_monitor,
    list_monitors,
    cancel_monitor,
)

logger = setup_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# 도구 실행기 (메인)
# ────────────────────────────────────────────────────────────────────
def execute_tool(tool_name: str, tool_args: Dict[str, Any]) -> str:
    t_start = time.time()
    logger.info(f"[도구실행] 시작 tool={tool_name} args={tool_args}")

    try:
        if tool_name == "save_domain_knowledge":
            # 사용자 채팅 → 도메인 RAG 영속 저장 → 다음 AI 사이클 자동 참조
            from agri_ai_core.src.control.ai_doc_rag import save_domain_knowledge
            tags_raw = tool_args.get("tags")
            tags_list = None
            if tags_raw:
                tags_list = [t.strip() for t in str(tags_raw).split(",") if t.strip()]
            result = save_domain_knowledge(
                title=tool_args.get("title", "").strip(),
                content=tool_args.get("content", "").strip(),
                category=(tool_args.get("category") or "운영노하우").strip() or "운영노하우",
                farm_id=tool_args.get("farm_id"),
                house_id=tool_args.get("house_id"),
                tags=tags_list,
                auth_farm_id=tool_args.get("auth_farm_id"),
            )

        elif tool_name == "delete_farm_knowledge":
            result = delete_farm_knowledge(
                file_name=tool_args.get("file_name"),
                farm_id=tool_args.get("farm_id"),
                auth_farm_id=tool_args.get("auth_farm_id"),
            )

        elif tool_name == "search_farm_knowledge":
            result = search_farm_knowledge(
                query=tool_args.get("query"),
                n_results=tool_args.get("n_results", 5),
                file_name=tool_args.get("file_name"),
                farm_id=tool_args.get("farm_id"),
                house_id=tool_args.get("house_id"),
                auth_farm_id=tool_args.get("auth_farm_id"),
                _meta_hint=bool(tool_args.get("_meta_hint")),
            )

        elif tool_name == "get_farm_realtime_data":
            result = get_farm_realtime_data(
                house_id=tool_args.get("house_id"),
                farm_id=tool_args.get("farm_id"),
                data_type=tool_args.get("data_type", "all")
            )

        elif tool_name == "get_weather_forecast":
            result = get_weather_forecast(
                farm_id=tool_args.get("farm_id"),
                house_id=tool_args.get("house_id"),
            )

        elif tool_name == "db_write_query":
            result = db_write_query(
                sql=tool_args.get("sql"),
                reason=tool_args.get("reason", ""),
                auth_farm_id=tool_args.get("auth_farm_id"),
            )

        elif tool_name == "source_list":
            result = source_list(path=tool_args.get("path", "."),
                                 pattern=tool_args.get("pattern"))

        elif tool_name == "source_search":
            result = source_search(query=tool_args.get("query"),
                                   path=tool_args.get("path", "."),
                                   max_results=tool_args.get("max_results"))

        elif tool_name == "source_read":
            result = source_read(file_path=tool_args.get("file_path"),
                                 start_line=tool_args.get("start_line", 1),
                                 end_line=tool_args.get("end_line"))

        elif tool_name == "call_external_api":
            result = call_external_api(
                api_name=tool_args.get("api_name"),
                params=tool_args.get("params"),
            )

        elif tool_name == "manage_external_api":
            result = manage_external_api(
                action=tool_args.get("action"),
                api_name=tool_args.get("api_name"),
                description=tool_args.get("description"),
                url_template=tool_args.get("url_template"),
                response_hint=tool_args.get("response_hint"),
                auth_farm_id=tool_args.get("auth_farm_id"),
            )

        elif tool_name == "control_relay":
            devices = tool_args.get("devices")
            h_id = tool_args.get("house_id")
            f_id = tool_args.get("farm_id")
            auth_fid = tool_args.get("auth_farm_id")
            # house_id='all' + devices 배열 → 전 재배사 다중 장치 일괄 제어
            if devices and isinstance(devices, list) and len(devices) > 0:
                if str(h_id or "").strip().lower() in ("all", "전체", "모든"):
                    result = _control_relay_all_houses(
                        farm_id=f_id, devices=devices, mode=tool_args.get("mode"),
                        auth_farm_id=auth_fid,
                    )
                else:
                    result = control_relays_batch(
                        house_id=h_id, devices=devices,
                        farm_id=f_id, mode=tool_args.get("mode"),
                        auth_farm_id=auth_fid,
                    )
            else:
                result = control_relay(
                    house_id=h_id,
                    device_name=tool_args.get("device_name"),
                    action=tool_args.get("action"),
                    farm_id=f_id,
                    mode=tool_args.get("mode"),
                    auth_farm_id=auth_fid,
                )

        elif tool_name == "search_web":
            result = search_web(
                query=tool_args.get("query"),
                n_results=tool_args.get("n_results"),
                auto_fetch_max=tool_args.get("auto_fetch_max"),
            )

        elif tool_name == "fetch_url_content":
            result = fetch_url_content(
                url=tool_args.get("url", "")
            )

        elif tool_name == "db_list_tables":
            result = db_list_tables()

        elif tool_name == "db_describe_table":
            result = db_describe_table(table_name=tool_args.get("table_name"))

        elif tool_name == "db_read_query":
            # LLM 이 인자 키를 'sql' 대신 'query'/'sql_query' 로 주는 경우도 허용(견고화)
            _sql = (tool_args.get("sql") or tool_args.get("query")
                    or tool_args.get("sql_query") or tool_args.get("statement"))
            result = db_read_query(sql=_sql,
                                   limit=tool_args.get("limit", 50),
                                   auth_farm_id=tool_args.get("auth_farm_id"))

        elif tool_name == "manage_analysis_lesson":
            result = manage_analysis_lesson(
                action=tool_args.get("action"),
                lesson_text=tool_args.get("lesson_text"),
                lesson_id=tool_args.get("lesson_id"),
                auth_farm_id=tool_args.get("auth_farm_id"),
            )

        elif tool_name == "manage_control_prompt":
            result = manage_control_prompt(
                action=tool_args.get("action"),
                block_id=tool_args.get("block_id"),
                body_text=tool_args.get("body_text"),
                auth_farm_id=tool_args.get("auth_farm_id"),
            )

        elif tool_name == "set_admin_directive":
            result = set_admin_directive(
                house_id=tool_args.get("house_id"),
                device_name=tool_args.get("device_name"),
                state=tool_args.get("state"),
                note=tool_args.get("note", ""),
                farm_id=tool_args.get("farm_id"),
                auth_farm_id=tool_args.get("auth_farm_id"),
            )

        elif tool_name == "release_admin_directive":
            result = release_admin_directive(
                house_id=tool_args.get("house_id"),
                device_name=tool_args.get("device_name"),
                farm_id=tool_args.get("farm_id"),
                auth_farm_id=tool_args.get("auth_farm_id"),
            )

        elif tool_name == "set_house_control_mode":
            result = set_house_control_mode(
                house_id=tool_args.get("house_id"),
                mode=tool_args.get("mode"),
                farm_id=tool_args.get("farm_id"),
                auth_farm_id=tool_args.get("auth_farm_id"),
            )

        elif tool_name == "set_growth_stage":
            result = set_growth_stage(
                house_id=tool_args.get("house_id"),
                stage=tool_args.get("stage"),
                farm_id=tool_args.get("farm_id"),
                auth_farm_id=tool_args.get("auth_farm_id"),
            )

        elif tool_name == "set_circulation_mode":
            result = set_circulation_mode(
                house_id=tool_args.get("house_id"),
                mode=tool_args.get("mode"),
                farm_id=tool_args.get("farm_id"),
                auth_farm_id=tool_args.get("auth_farm_id"),
            )

        elif tool_name == "set_schedule":
            result = set_schedule(
                action=tool_args.get("action", "list"),
                house_id=tool_args.get("house_id"),
                unit_type=tool_args.get("unit_type", "light"),
                start_time=tool_args.get("start_time"),
                end_time=tool_args.get("end_time"),
                interval_min=tool_args.get("interval_min"),
                weekdays=tool_args.get("weekdays"),
                excs_type=tool_args.get("excs_type", "daily"),
                farm_id=tool_args.get("farm_id"),
                auth_farm_id=tool_args.get("auth_farm_id"),
            )

        elif tool_name == "override_ai_thresholds":
            result = override_ai_thresholds(
                action=tool_args.get("action"),
                key=tool_args.get("key"),
                value=tool_args.get("value"),
                farm_id=tool_args.get("farm_id"),
                house_id=tool_args.get("house_id"),
                auth_farm_id=tool_args.get("auth_farm_id"),
            )

        elif tool_name == "get_system_status":
            from agri_ai_core.src.ai.tools_data import get_system_status
            result = get_system_status(
                farm_id=tool_args.get("farm_id"),
            )

        elif tool_name == "get_camera_view":
            from agri_ai_core.src.ai.tools_data import get_camera_view
            result = get_camera_view(
                farm_id=tool_args.get("farm_id"),
                house_id=tool_args.get("house_id"),
            )

        # ─────── Agent 모니터링 ───────
        elif tool_name == "schedule_monitor":
            result = schedule_monitor(
                intent=tool_args.get("intent") or tool_args.get("purpose") or "모니터링",
                start_time=tool_args.get("start_time"),
                end_time=tool_args.get("end_time"),
                interval_min=int(tool_args.get("interval_min", 30)),
                house_ids=tool_args.get("house_ids"),
                farm_id=tool_args.get("farm_id"),
                alert_on_normal=bool(tool_args.get("alert_on_normal", False)),
            )

        elif tool_name == "list_monitors":
            result = list_monitors()

        elif tool_name == "cancel_monitor":
            result = cancel_monitor(job_id=tool_args.get("job_id"))

        # ─────── 반복 agent 구독 ───────
        elif tool_name == "agent_subscribe":
            from agri_ai_core.src.ai.tools_agent_sub import agent_subscribe
            result = agent_subscribe(
                task=tool_args.get("task", ""),
                interval_min=tool_args.get("interval_min", 60),
                farm_id=tool_args.get("farm_id"),
                house_id=tool_args.get("house_id"),
                user_id=tool_args.get("user_id"),
                intent=tool_args.get("intent"),
            )

        elif tool_name == "list_agent_subscriptions":
            from agri_ai_core.src.ai.tools_agent_sub import list_agent_subscriptions
            result = list_agent_subscriptions(
                user_id=tool_args.get("user_id"),
                include_default=bool(tool_args.get("include_default", False)),
            )

        elif tool_name == "set_alert_interval":
            from agri_ai_core.src.ai.tools_agent_sub import set_alert_interval
            result = set_alert_interval(
                interval_min=tool_args.get("interval_min"),
                farm_id=tool_args.get("farm_id"),
                subscription_id=tool_args.get("subscription_id"),
                auth_farm_id=tool_args.get("auth_farm_id"),
            )

        elif tool_name == "edit_source":
            from agri_ai_core.src.ai.tools_source_edit import edit_source
            result = edit_source(path=tool_args.get("path"),
                                 content=tool_args.get("content"),
                                 reason=tool_args.get("reason", ""),
                                 test_target=tool_args.get("test_target") or "tests/")

        elif tool_name == "revert_source":
            from agri_ai_core.src.ai.tools_source_edit import revert_source
            result = revert_source(audit_id=tool_args.get("audit_id"),
                                   reason=tool_args.get("reason", ""))

        elif tool_name == "list_source_edits":
            from agri_ai_core.src.ai.tools_source_edit import list_source_edits
            result = list_source_edits(limit=tool_args.get("limit") or 10)

        elif tool_name == "get_server_resources":
            from agri_ai_core.src.ai.tools_resources import get_server_resources
            result = get_server_resources()

        elif tool_name == "restart_service":
            from agri_ai_core.src.ai.tools_service import restart_service
            result = restart_service(service_no=tool_args.get("service_no"),
                                     reason=tool_args.get("reason", ""))

        elif tool_name == "service_status":
            from agri_ai_core.src.ai.tools_service import service_status
            result = service_status(service_no=tool_args.get("service_no"))

        elif tool_name == "list_services":
            from agri_ai_core.src.ai.tools_service import list_services
            result = list_services()

        elif tool_name == "write_script":
            from agri_ai_core.src.ai.tools_script import write_script
            result = write_script(script=tool_args.get("script"),
                                  content=tool_args.get("content"),
                                  reason=tool_args.get("reason", ""))

        elif tool_name == "run_script":
            from agri_ai_core.src.ai.tools_script import run_script
            result = run_script(script=tool_args.get("script"),
                                args=tool_args.get("args"),
                                timeout=tool_args.get("timeout") or 60,
                                reason=tool_args.get("reason", ""))

        elif tool_name == "list_scripts":
            from agri_ai_core.src.ai.tools_script import list_scripts
            result = list_scripts()

        elif tool_name == "read_script":
            from agri_ai_core.src.ai.tools_script import read_script
            result = read_script(script=tool_args.get("script"))

        elif tool_name == "mcp_call":
            from agri_ai_core.src.ai.tools_mcp_gateway import mcp_call
            result = mcp_call(
                server=tool_args.get("server"),
                tool=tool_args.get("tool"),
                args=tool_args.get("args"),
                timeout=tool_args.get("timeout") or 45,
            )

        elif tool_name == "mcp_list_tools":
            from agri_ai_core.src.ai.tools_mcp_gateway import mcp_list_tools
            result = mcp_list_tools(server=tool_args.get("server"))

        elif tool_name == "search_logs":
            from agri_ai_core.src.ai.tools_logs import search_logs
            result = search_logs(
                query=tool_args.get("query"),
                level=tool_args.get("level"),
                date=tool_args.get("date"),
                log_type=tool_args.get("log_type"),
                max_results=tool_args.get("max_results") or 50,
            )

        elif tool_name == "list_log_files":
            from agri_ai_core.src.ai.tools_logs import list_log_files
            result = list_log_files()

        elif tool_name == "set_alert_level":
            from agri_ai_core.src.ai.tools_agent_sub import set_alert_level
            result = set_alert_level(
                level=tool_args.get("level"),
                auth_farm_id=tool_args.get("auth_farm_id"),
            )

        elif tool_name == "cancel_agent_subscription":
            from agri_ai_core.src.ai.tools_agent_sub import cancel_agent_subscription
            result = cancel_agent_subscription(
                subscription_id=tool_args.get("subscription_id") or tool_args.get("id"),
                user_id=tool_args.get("user_id"),
                reason=tool_args.get("reason"),
            )

        elif tool_name == "get_pending_alerts":
            from agri_ai_core.src.ai.tools_agent_sub import get_pending_alerts
            result = get_pending_alerts(
                user_id=tool_args.get("user_id"),
                limit=int(tool_args.get("limit", 10) or 10),
                mark_read=bool(tool_args.get("mark_read", True)),
            )

        # ─────── Agent 즉시 1회 분석 ───────
        elif tool_name == "agent_one_shot":
            from agri_ai_core.src.control.ai_monitor_agent import run_agent
            task = (tool_args.get("task") or "농장 모니터링").strip()
            try:
                farm_id_arg = int(tool_args.get("farm_id") or 1)
            except (TypeError, ValueError):
                farm_id_arg = 1
            agent_result = run_agent(task=task, farm_id=farm_id_arg,
                                     trigger_type="user")
            # LLM 합성에 필요한 핵심만 압축 — steps 전체는 너무 길어 final + 메타만
            tool_counts: Dict[str, int] = {}
            for h in agent_result.get("steps", []):
                t = h.get("tool")
                if t:
                    tool_counts[t] = tool_counts.get(t, 0) + 1
            result = {
                "success": bool(agent_result.get("success")),
                "duration_sec": agent_result.get("duration_sec"),
                "steps": len(agent_result.get("steps", [])),
                "tool_calls": tool_counts,
                "final": agent_result.get("final"),
                "reason": agent_result.get("reason"),
                "log_id": agent_result.get("log_id"),
            }

        else:
            result = {
                "success": False,
                "error": f"알 수 없는 도구: {tool_name}"
            }

        elapsed = time.time() - t_start
        success = result.get("success", True) if isinstance(result, dict) else True
        json_result = json.dumps(result, ensure_ascii=False, indent=2, default=_json_default)
        logger.info(f"[도구실행] 완료 tool={tool_name} ({elapsed:.1f}s) success={success} 결과길이={len(json_result)}자")
        return json_result

    except Exception as e:
        elapsed = time.time() - t_start
        logger.error(f"[도구실행] 오류 tool={tool_name} ({elapsed:.1f}s): {e}")
        logger.error(traceback.format_exc())

        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False, default=_json_default)
