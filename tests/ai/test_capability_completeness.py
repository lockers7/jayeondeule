# ══════════════════════════════════════════════════════════════════════════════
# test_capability_completeness — 로컬 AI 역량 완결성 회귀(완결본, GPU 불요)
#
# 종합 역량감사(2026-07-25) 결과를 영구 회귀로 고정한다. LLM/GPU 없이 결정적으로
# 등록 계층·시드·계획프롬프트를 검증하므로 CI 에서 상시 실행 가능.
#
# 핵심 불변식: 채팅 도구는 3계층(_VALID_TOOLS · tool_definition_m(active) ·
#   tools_executor dispatch)에 동일 집합으로 등록되어야 한다 = "5중 등록" 함정 방지.
#
# 파일 시작 함수 목록:
#   test_registration_three_way_invariant : 3계층 도구 집합 완전 동일
#   test_capability_inventory_present      : 역량군 필수 도구 전멸 방지
#   test_self_learning_trio_in_plan_prompt : 자가학습 3종 계획프롬프트 노출(G-B1)
#   test_selfgrow_seed_persisted           : 자율성장 시드 3종 seed 소스 영속(G-B2)
#   test_learning_types_enumerates_domain  : 학습유형 7종·domain_knowledge 열거(G-B3)
#   test_remote_tools_category_consistent  : 원격 도구 category 일관(G-A1)
# ══════════════════════════════════════════════════════════════════════════════
import re
import inspect
import pytest


def _dispatch_names() -> set:
    src = inspect.getsource(__import__(
        "agri_ai_core.src.ai.tools_executor", fromlist=["x"]))
    return set(re.findall(r'tool_name == "([^"]+)"', src))


def _db_active_ids() -> set:
    from agri_ai_core.src import prompt_registry as pr
    return {r["tool_id"] for r in pr.get_tools()}


def _valid_tools() -> set:
    from agri_ai_core.src.ai.pipeline.question_analyzer import _VALID_TOOLS
    return set(_VALID_TOOLS)


# ────────────────────────────────────────────────────────────────────
# 3계층 등록 완전 동일 — 신규 도구를 한 계층에만 넣고 누락하는 함정을 즉시 검출.
# ────────────────────────────────────────────────────────────────────
def test_registration_three_way_invariant():
    valid = _valid_tools()
    db = _db_active_ids()
    disp = _dispatch_names()
    # 화이트리스트 = DB active
    assert valid == db, (
        f"whitelist-DB 불일치: whitelist-only={sorted(valid - db)}, "
        f"DB-only={sorted(db - valid)}")
    # 화이트리스트 ⊆ dispatch (dispatch 에는 내부 별칭이 더 있을 수 있으나
    # 화이트리스트의 모든 도구는 반드시 dispatch 되어야 함)
    assert valid <= disp, f"dispatch 누락: {sorted(valid - disp)}"


# ────────────────────────────────────────────────────────────────────
# 역량군별 필수 도구 — 세 계층에서 동시에 사라져(전멸) 역량이 통째 증발하는 것 방지.
# ────────────────────────────────────────────────────────────────────
CAPABILITY_INVENTORY = {
    "농장상태/제어": ["get_farm_realtime_data", "get_system_status", "control_relay",
                  "set_house_control_mode", "override_ai_thresholds"],
    "DB조회": ["db_read_query", "db_list_tables", "db_describe_table"],
    "로그/서비스": ["search_logs", "list_log_files", "list_services", "service_status",
               "get_server_resources"],
    "지식/RAG": ["search_farm_knowledge", "save_domain_knowledge",
              "manage_analysis_lesson", "manage_system_knowledge"],
    "원격(RPi/서버)": ["remote_status", "remote_run", "compare_remote_sources",
                  "manage_remote_host", "approve_remote_command"],
    "코딩/소스": ["write_script", "run_script", "source_search", "source_read",
              "edit_source"],
    "MCP/웹": ["mcp_call", "mcp_list_tools", "manage_mcp_server", "search_web",
             "fetch_url_content"],
    "외부정보": ["get_weather_forecast", "get_camera_view"],
    "트레이딩": ["set_trading_strategy"],
}


@pytest.mark.parametrize("group,tools", sorted(CAPABILITY_INVENTORY.items()))
def test_capability_inventory_present(group, tools):
    registered = _valid_tools() & _db_active_ids() & _dispatch_names()
    missing = [t for t in tools if t not in registered]
    assert not missing, f"[{group}] 3계층 등록 누락: {missing}"


# ────────────────────────────────────────────────────────────────────
# 자가학습 3종은 계획프롬프트(ANALYZER)에 반드시 노출 — G-B1 재발 방지.
#   manage_system_knowledge 가 실행기/화이트리스트/DB엔 있으나 계획프롬프트에만
#   빠져 있던 결함(5중 미완)을 락인.
# ────────────────────────────────────────────────────────────────────
def test_self_learning_trio_in_plan_prompt():
    from agri_ai_core.src.ai.pipeline.prompts import get_analyzer_system_prompt
    prompt = get_analyzer_system_prompt()
    for tool in ("save_domain_knowledge", "manage_analysis_lesson",
                 "manage_system_knowledge"):
        assert tool in prompt, f"계획프롬프트에 {tool} 설명 누락(5중 미완)"


# ────────────────────────────────────────────────────────────────────
# 자연어 매매전략 도구도 계획프롬프트에 노출 — G-R1 재발 방지.
#   set_trading_strategy 가 화이트리스트/DB/실행기엔 있으나 계획프롬프트에만
#   빠져 있어 매매 발화가 빈 계획으로 라우팅되던 결함(5중 미완)을 락인.
# ────────────────────────────────────────────────────────────────────
def test_trading_strategy_in_plan_prompt():
    from agri_ai_core.src.ai.pipeline.prompts import get_analyzer_system_prompt
    prompt = get_analyzer_system_prompt()
    assert "set_trading_strategy" in prompt, "계획프롬프트에 set_trading_strategy 누락"
    assert "매매" in prompt, "계획프롬프트에 매매 라우팅 트리거 문구 누락"


# ────────────────────────────────────────────────────────────────────
# ⭐ 마스터 가드 — 모든 라우팅 도구는 ANALYZER 가 발견 가능해야 한다.
#   _VALID_TOOLS 의 모든 도구가 계획프롬프트(정적) 또는 회상 system_knowledge(RAG)
#   중 한 곳에는 반드시 기술돼야 한다. 둘 다 없으면 등록만 돼 있고 LLM 이 호출
#   시점을 몰라 빈 계획으로 라우팅된다(G-B1·G-R1·G-R2 의 공통 근본원인).
#   신규 채팅도구가 이 이중 경로 어디에도 없으면 즉시 검출.
# ────────────────────────────────────────────────────────────────────
def test_all_valid_tools_discoverable_by_analyzer():
    from agri_ai_core.src.ai.pipeline.question_analyzer import _VALID_TOOLS
    from agri_ai_core.src.ai.pipeline.prompts import get_analyzer_system_prompt
    from agri_ai_core.src.ai.system_knowledge import list_system_knowledge
    prompt = get_analyzer_system_prompt()
    know = " ".join(it.get("text", "") for it in list_system_knowledge())
    corpus = prompt + " " + know
    missing = sorted(t for t in _VALID_TOOLS if t not in corpus)
    assert not missing, (
        f"ANALYZER 라우팅 불가(계획프롬프트·시스템지식 모두 부재): {missing} "
        f"— 도구 설명을 계획프롬프트나 system_knowledge 에 추가하라")


# ────────────────────────────────────────────────────────────────────
# 자율성장 시드 3종은 seed_system_knowledge() 소스에 영속 — G-B2 재발 방지.
#   ChromaDB 재구축/재시드 시에도 유실되지 않도록 소스 레벨 존재를 검증.
# ────────────────────────────────────────────────────────────────────
def test_selfgrow_seed_persisted():
    from agri_ai_core.src.ai import system_knowledge as sk
    src = inspect.getsource(sk.seed_system_knowledge)
    for key in ("selfgrow_schedule", "selfgrow_subscriptions",
                "selfgrow_learning_types"):
        assert f'"{key}"' in src, f"seed 소스에 {key} 미포함(재시드 시 유실)"
    # 실제 테이블명 정합(schedule_m_setting) — 환각 근본 차단
    assert "schedule_m_setting" in src


# ────────────────────────────────────────────────────────────────────
# 학습유형 열거에 domain_knowledge 저장소 포함(7종) — G-B3 재발 방지.
# ────────────────────────────────────────────────────────────────────
def test_learning_types_enumerates_domain():
    from agri_ai_core.src.ai import system_knowledge as sk
    src = inspect.getsource(sk.seed_system_knowledge)
    i = src.find("selfgrow_learning_types")
    seg = src[i:i + 1200]
    assert "7가지" in seg, "학습유형 7종 열거 아님"
    assert "domain_knowledge" in seg, "domain_knowledge 저장소 열거 누락"
    assert "save_domain_knowledge" in seg


# ────────────────────────────────────────────────────────────────────
# 원격 도구군 category 일관 — G-A1 재발 방지(형제 4종과 동일 category).
# ────────────────────────────────────────────────────────────────────
def test_remote_tools_category_consistent():
    from agri_ai_core.src.postgresql.connection import db_session
    remote = ["remote_status", "remote_run", "compare_remote_sources",
              "manage_remote_host", "approve_remote_command"]
    with db_session() as d:
        rows = d.fetch_all(
            "SELECT tool_id, category FROM tool_definition_m "
            "WHERE tool_id = ANY(%s)", (remote,))
    cats = {r[0]: r[1] for r in rows}
    assert set(cats) == set(remote), f"원격 도구 DB 누락: {set(remote) - set(cats)}"
    assert set(cats.values()) == {"remote"}, f"category 불일치: {cats}"
