# ══════════════════════════════════════════════════════════════════════════════
# test_mcp_registry — MCP 서버 자체추가(manage_mcp_server) 검증
#
# 로컬 AI 가 요청받은 MCP 서버를 스스로 .vscode/mcp.json 에 추가/제거한다.
# 안전: 런처 allowlist·관리자 전용·백업·원자적 쓰기·이름검증·덮어쓰기 가드.
#
# 파일 시작 함수 목록:
#   _use_tmp_cfg              : 임시 mcp.json 으로 경로 대체(실파일 보호)
#   test_list_add_get         : add→list→get 기본 흐름 + env 마스킹
#   test_add_rejects_bad_command : allowlist 밖 command 거부
#   test_add_rejects_duplicate : 기존 이름 add 거부(update 로만)
#   test_update_and_remove    : update 덮어쓰기 + remove + .bak 백업
#   test_admin_only           : auth_farm_id 있으면 변경 차단
#   test_name_validation      : 잘못된 이름 거부
#   test_url_server           : HTTP(url) 형 서버 등록
#   test_atomic_write_valid_json : 쓰기 후 파일이 유효 JSON·서버 반영
#   test_registered_5places   : 5중 등록(impl+정의+디스패치+화이트리스트+DB표)
#   test_codedev_knowledge_seeded : 코드개발 지식이 시드에 포함
# ══════════════════════════════════════════════════════════════════════════════
import inspect
import json

import agri_ai_core.src.ai.tools_mcp_registry as reg


def _use_tmp_cfg(monkeypatch, tmp_path, servers=None):
    cfg = tmp_path / "mcp.json"
    data = {"servers": servers if servers is not None
            else {"existing": {"command": "npx", "args": ["-y", "pkg"]}}}
    cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setattr(reg, "_config_path", lambda: cfg)
    return cfg


def test_list_add_get(monkeypatch, tmp_path):
    cfg = _use_tmp_cfg(monkeypatch, tmp_path)
    # add
    r = reg.manage_mcp_server(action="add", name="time",
                              command="uvx", args=["mcp-server-time"],
                              env={"TZ": "${TZ}"})
    assert r["success"] and r["server"] == "time"
    # list 에 노출
    lst = reg.manage_mcp_server(action="list")
    names = {s["name"] for s in lst["servers"]}
    assert {"existing", "time"} <= names
    # get + env 플레이스홀더는 그대로, 실제값은 마스킹
    g = reg.manage_mcp_server(action="get", name="time")
    assert g["config"]["command"] == "uvx"
    assert g["config"]["env"]["TZ"] == "${TZ}"
    # 파일에 실제 기록됐는지
    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert saved["servers"]["time"]["args"] == ["mcp-server-time"]


def test_add_rejects_bad_command(monkeypatch, tmp_path):
    _use_tmp_cfg(monkeypatch, tmp_path)
    r = reg.manage_mcp_server(action="add", name="evil", command="rm", args=["-rf", "/"])
    assert not r["success"] and "허용" in r["error"]      # 임의 실행 차단


def test_add_rejects_duplicate(monkeypatch, tmp_path):
    _use_tmp_cfg(monkeypatch, tmp_path)
    r = reg.manage_mcp_server(action="add", name="existing", command="npx", args=["x"])
    assert not r["success"] and "update" in r["error"]     # 덮어쓰기는 update 로만


def test_update_and_remove(monkeypatch, tmp_path):
    cfg = _use_tmp_cfg(monkeypatch, tmp_path)
    # update 로 덮어쓰기
    u = reg.manage_mcp_server(action="update", name="existing",
                              command="python", args=["-m", "srv"])
    assert u["success"]
    assert json.loads(cfg.read_text())["servers"]["existing"]["command"] == "python"
    # remove + .bak 백업 생성
    rm = reg.manage_mcp_server(action="remove", name="existing")
    assert rm["success"] and rm["removed"] == "existing"
    assert "existing" not in json.loads(cfg.read_text())["servers"]
    assert (tmp_path / "mcp.json.bak").exists()            # 롤백용 백업


def test_admin_only(monkeypatch, tmp_path):
    _use_tmp_cfg(monkeypatch, tmp_path)
    # 농장주(auth_farm_id 존재) 는 변경 불가, 조회는 가능
    assert not reg.manage_mcp_server(action="add", name="x", command="npx",
                                     args=[], auth_farm_id="1")["success"]
    assert not reg.manage_mcp_server(action="remove", name="existing",
                                     auth_farm_id="1")["success"]
    assert reg.manage_mcp_server(action="list", auth_farm_id="1")["success"]


def test_name_validation(monkeypatch, tmp_path):
    _use_tmp_cfg(monkeypatch, tmp_path)
    for bad in ("a", "-bad", "has space", "너무" * 40):
        r = reg.manage_mcp_server(action="add", name=bad, command="npx", args=[])
        assert not r["success"]


def test_url_server(monkeypatch, tmp_path):
    cfg = _use_tmp_cfg(monkeypatch, tmp_path)
    r = reg.manage_mcp_server(action="add", name="remote",
                              url="https://mcp.example.com/sse", transport="sse")
    assert r["success"]
    saved = json.loads(cfg.read_text())["servers"]["remote"]
    assert saved["url"] == "https://mcp.example.com/sse" and saved["type"] == "sse"
    # 사설/비http url 방어
    bad = reg.manage_mcp_server(action="add", name="badurl", url="ftp://x")
    assert not bad["success"]


def test_atomic_write_valid_json(monkeypatch, tmp_path):
    cfg = _use_tmp_cfg(monkeypatch, tmp_path)
    reg.manage_mcp_server(action="add", name="alpha", command="node", args=["a.js"])
    reg.manage_mcp_server(action="add", name="beta", command="npx", args=["b"])
    # 여러 번 써도 항상 유효 JSON + 기존 서버 보존
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert {"existing", "alpha", "beta"} <= set(data["servers"])


def test_registered_5places(monkeypatch):
    # 1) 구현 함수
    from agri_ai_core.src.ai.tools_mcp_registry import manage_mcp_server  # noqa: F401
    # 2) 코드정의 스펙(폴백)
    monkeypatch.setenv("USE_DB_TOOLS", "0")
    from agri_ai_core.src.ai.tools_definition import get_available_tools
    assert "manage_mcp_server" in {t["function"]["name"] for t in get_available_tools()}
    # 3) executor 디스패치
    from agri_ai_core.src.ai import tools_executor
    assert 'tool_name == "manage_mcp_server"' in inspect.getsource(tools_executor)
    # 4) analyzer 화이트리스트
    from agri_ai_core.src.ai.pipeline import question_analyzer
    assert "manage_mcp_server" in inspect.getsource(question_analyzer)
    # 5) tool_definition_m 테이블(USE_DB_TOOLS=1 1순위)
    from agri_ai_core.src.prompt_registry import get_tools
    assert "manage_mcp_server" in {r["tool_id"] for r in get_tools()}


def test_codedev_knowledge_seeded():
    # 코드 읽기/개발 지식이 시드에 포함(재시드시 영속)
    from agri_ai_core.src.ai import system_knowledge as sk
    src = inspect.getsource(sk.seed_system_knowledge)
    for key in ("code_dev_workflow", "code_edit_safety", "sql_dev_howto",
                "python_dev_howto", "mcp_add_howto"):
        assert key in src, key
