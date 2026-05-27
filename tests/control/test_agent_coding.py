# ══════════════════════════════════════════════════════════════════════════════
# test_agent_coding — Agent 코딩 실행·체이닝 결합 검증
#
# 주기 Agent(ReAct)가 write→run→수정→재실행으로 코드를 작성·디버깅할 수 있게 됐는지.
# 코딩 도구 결합 · 코딩임무 라우팅(CTRL_AGENT_CODE) · 디버깅 반복용 캡 상향을 검증.
#
# 파일 시작 함수 목록:
#   test_code_wrappers_delegate   : 래퍼가 채팅 구현에 위임하고 dict 반환
#   test_code_wrappers_validate   : 필수 인자 누락 시 error dict
#   test_code_wrappers_swallow    : 하위 예외를 삼켜 error dict
#   test_merged_into_agent        : Agent TOOL_REGISTRY 결합 + read-only(비 제어-write)
#   test_execute_dispatch         : _execute_tool 로 코딩도구 디스패치
#   test_coding_task_detection    : 코딩임무 판정(제어·외부와 분리)
#   test_prompt_routes_code       : 코딩임무→CTRL_AGENT_CODE, 제어→CTRL_AGENT_SYSTEM
#   test_code_cap_higher          : 코딩도구 캡 > 조회도구 캡(디버깅 반복 허용)
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.ai import tools_agent_code as code


def test_code_wrappers_delegate(monkeypatch):
    monkeypatch.setattr("agri_ai_core.src.ai.tools_script.write_script",
                        lambda script, content, reason="": {"success": True, "s": script})
    assert code.agent_write_script(script="x.py", content="print(1)")["s"] == "x.py"

    monkeypatch.setattr("agri_ai_core.src.ai.tools_script.run_script",
                        lambda script, args=None, timeout=60, reason="": {"success": True, "ran": script, "a": args})
    r = code.agent_run_script(script="x.py")
    assert r["ran"] == "x.py" and r["a"] == []

    monkeypatch.setattr("agri_ai_core.src.ai.tools_source.source_read",
                        lambda file_path, start_line=1, end_line=None: {"success": True, "f": file_path, "sl": start_line})
    assert code.agent_source_read(file_path="a.py", start_line=5)["sl"] == 5

    monkeypatch.setattr("agri_ai_core.src.ai.tools_db.db_read_query",
                        lambda sql, limit=50: {"success": True, "q": sql, "lim": limit})
    assert code.agent_db_read(sql="SELECT 1", limit=10)["lim"] == 10


def test_code_wrappers_validate():
    assert "error" in code.agent_write_script(content="x")          # script 누락
    assert "error" in code.agent_write_script(script="x.py")        # content 누락
    assert "error" in code.agent_run_script()                       # script 누락
    assert "error" in code.agent_source_read()                      # file_path 누락
    assert "error" in code.agent_source_search(query="a")           # 2자 미만
    assert "error" in code.agent_db_read()                          # sql 누락


def test_code_wrappers_swallow(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("깨짐")
    monkeypatch.setattr("agri_ai_core.src.ai.tools_script.run_script", boom)
    r = code.agent_run_script(script="x.py")
    assert "error" in r and "실패" in r["error"]


def test_merged_into_agent():
    from agri_ai_core.src.control import ai_monitor_agent as ama
    for name in ("write_script", "run_script", "read_script", "list_scripts",
                 "source_read", "source_search", "db_read_query"):
        assert name in ama.TOOL_REGISTRY                 # Agent 도구셋 결합
        assert name not in ama._WRITE_TOOL_NAMES         # 농장 제어-write 아님(트리거큐 미대상)
        assert name in ama._CODE_TOOL_NAMES              # 코딩도구 집합
    assert "코딩 도구" in ama.tool_specs_text()           # ReAct 프롬프트 노출


def test_execute_dispatch(monkeypatch):
    from agri_ai_core.src.control import ai_monitor_agent as ama
    monkeypatch.setattr("agri_ai_core.src.ai.tools_script.list_scripts",
                        lambda: {"success": True, "scripts": []})
    out = ama._execute_tool("list_scripts", {})
    assert out.get("success") is True


def test_coding_task_detection():
    from agri_ai_core.src.control import ai_monitor_agent as ama
    for t in ["다음 파이썬 코드를 디버깅해줘", "이 함수의 버그를 찾아 고쳐 실행해봐",
              "스크립트를 작성해서 돌려봐", "소스 분석해서 오류 수정해"]:
        assert ama._is_coding_task(t), t
    # 제어·외부·일상은 코딩 아님
    for t in ["전체 재배사 순찰하고 제어해", "1호 습도 확인", None, ""]:
        assert not ama._is_coding_task(t), t
    # 외부정보 임무는 코딩 키워드 있어도 외부 우선
    assert not ama._is_coding_task("웹에서 파이썬 재배정보 검색해")


def test_prompt_routes_code(monkeypatch):
    from agri_ai_core.src.control import ai_monitor_agent as ama
    seen = {}
    monkeypatch.setattr("agri_ai_core.src.prompt_registry.get_control_block",
                        lambda block_id, **kw: (seen.update(id=block_id), f"P[{block_id}]")[1])
    ama.build_system_prompt(task="이 코드 디버깅해줘")
    assert seen["id"] == "CTRL_AGENT_CODE"
    ama.build_system_prompt(task="전체 호기 제어")
    assert seen["id"] == "CTRL_AGENT_SYSTEM"


def test_code_cap_higher():
    from agri_ai_core.src.control import ai_monitor_agent as ama
    # 디버깅 반복(write→run 여러 라운드)을 위해 코딩 캡이 조회 캡보다 커야 한다
    assert ama._MAX_CODE_TOOL_CALLS > ama._MAX_READ_TOOL_CALLS
    assert ama.AGENT_CODE_MAX_STEPS > ama.AGENT_MAX_STEPS
