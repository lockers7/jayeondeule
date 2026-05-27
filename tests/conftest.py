# ══════════════════════════════════════════════════════════════════════════════
# pytest 전역 설정 — 운영 로그 보호
# 테스트가 생성하는 모든 로그를 logs/test/ 로 무조건 분리한다 (농장주 지시).
# 본 파일은 테스트 모듈 import 전에 로드되므로 setup_logger 초기화보다 선행한다.
# ══════════════════════════════════════════════════════════════════════════════
import os

os.environ["AGRI_TEST_LOG"] = "1"


# ══════════════════════════════════════════════════════════════════════════════
# 부분 통합 단위(partial-integration groups) 자동 마킹
#   최소 단위(개별 테스트)를 의미있는 서브시스템 그룹으로 묶어 부분통합 테스트 가능.
#   파일명 패턴 → 그룹 마커 1:1 매핑(첫 매칭 우선). 개별 파일 수정 불필요.
#   실행: pytest -m mcp   /   pytest -m "control or trading"   등.
# ══════════════════════════════════════════════════════════════════════════════
import os as _os
import pytest as _pytest

_GROUP_ORDER = [
    ("trading",     ("trading", "agent_trade")),
    ("remote_code", ("remote", "agent_coding", "agent_external", "tools_source", "tools_script")),
    ("mcp",         ("mcp", "kis_order", "korea_weather", "weather_tool", "external_api")),
    ("llm",         ("call_llm", "llm_autonomy", "all_modes_use_gate", "fallback_gating")),
    ("rag",         ("system_knowledge", "sysadmin", "analysis_lesson", "selfgrow",
                     "autonomous_knowledge", "knowledge_scope", "rag_", "self_evolve",
                     "ai_context_modules", "rule_mining", "rule_approve")),
    ("chat",        ("analyzer", "casual_chat", "greeting", "chat_supplement",
                     "reformat", "farm_info_session")),
    ("tools",       ("tools_agent", "tools_auth", "tools_data", "tools_db", "tools_logs",
                     "tools_resources", "tools_service", "tool_provenance",
                     "tool_registration", "default_tool", "camera_view", "house_control")),
    ("db_status",   ("db_read", "audit_log", "system_status", "relay_truth",
                     "prompt_content", "prompt_registry", "control_prompt",
                     "dead_path", "parse_time", "simplify")),
    ("agent",       ("agent_", "ai_monitor_agent", "directive", "event_listener")),
    ("data_sched",  ("setting", "schedule", "listen_notify", "farm_cache",
                     "data_collector", "farm_geo", "task_scheduler", "kakao")),
    ("control",     ("ai_control", "emergency", "interlock", "valve_fan", "set_relay",
                     "humidity_fog", "mode_and_thresholds", "device_safety",
                     "atm_stagnation", "keep_full", "unified_control",
                     "user_prompt_water", "sensor_fault", "ai_thresholds")),
]
_ALL_GROUPS = [g for g, _ in _GROUP_ORDER] + ["misc"]


def _group_for(basename):
    for g, pats in _GROUP_ORDER:
        if any(p in basename for p in pats):
            return g
    return "misc"


def pytest_configure(config):
    for g in _ALL_GROUPS:
        config.addinivalue_line("markers", f"{g}: 부분 통합 단위 그룹 '{g}'")


def pytest_collection_modifyitems(config, items):
    for it in items:
        base = _os.path.basename(str(getattr(it, "fspath", "")))
        it.add_marker(getattr(_pytest.mark, _group_for(base)))
