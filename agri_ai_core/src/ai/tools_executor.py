# ══════════════════════════════════════════════════════════════════════════════
# LLM Tool 실행기 (라우터) — LLM이 요청한 도구를 적절한 모듈로 dispatch.
# 실제 구현은 tools_data.py(데이터), tools_control.py(제어),
# tools_search.py(웹검색), opinet_tools.py(유가)에 분산되어 있다.
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
)
from agri_ai_core.src.ai.tools_control import (
    control_relay,
    control_relays_batch,
    _control_relay_all_houses,
)
from agri_ai_core.src.ai.tools_search import search_web, fetch_url_content
from agri_ai_core.src.ai.opinet_tools import search_gas_price
# [Phase 1] 관리 도구 — 제어 모드/생육단계/순환모드/스케줄/임계값/시스템상태
from agri_ai_core.src.ai.tools_admin import (
    set_house_control_mode,
    set_growth_stage,
    set_circulation_mode,
    set_schedule,
    override_ai_thresholds,
)
# [Phase 4] Agent 모니터링 — schedule_monitor / list_monitors / cancel_monitor
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
            # [2026-05-01] 사용자 채팅 → 도메인 RAG 영속 저장 → 다음 AI 사이클 자동 참조
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

        elif tool_name == "search_gas_price":
            result = search_gas_price(
                query_type=tool_args.get("query_type", "avg_national"),
                sido=tool_args.get("sido"),
                sigun=tool_args.get("sigun"),
                prodcd=tool_args.get("prodcd", "B027"),
                fuel_name=tool_args.get("fuel_name"),
            )

        # ─────── [Phase 1 신규 관리 도구] ───────
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
                action=tool_args.get("action", "get"),
                key=tool_args.get("key"),
                value=tool_args.get("value"),
            )

        elif tool_name == "get_system_status":
            from agri_ai_core.src.ai.tools_data import get_system_status
            result = get_system_status(
                farm_id=tool_args.get("farm_id"),
            )

        # ─────── [Phase 4 Agent 모니터링] ───────
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
