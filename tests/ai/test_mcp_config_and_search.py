# ══════════════════════════════════════════════════════════════════════════════
# test_mcp_config_and_search — MCP 설정 로드 + searxng 검색 응답 파싱 검증
#
# 배경(2026-07-16 실측): .vscode/mcp.json 은 VSCode 포맷("servers")인데 로더가
#   표준 포맷("mcpServers")만 읽어 서버 0개 → 모든 MCP 호출이 "server not found"
#   로 조용히 폴백. 검색의 최후 안전망이 실제로는 없는 상태였다.
#   또 search_web 이 설정에 없는 이름("web-search"/"search")을 불러 이중으로 실패.
#
# 파일 시작 함수 목록:
#   test_load_accepts_vscode_servers_key : "servers"(VSCode 포맷) 수용
#   test_load_accepts_standard_key       : "mcpServers"(표준 포맷) 수용
#   test_load_missing_key_returns_empty  : 두 키 다 없으면 빈 dict
#   test_load_real_config_has_servers    : 실제 .vscode/mcp.json 이 0개가 아님(회귀 방지)
#   test_parse_searxng_basic             : Title/Description/URL 블록 항목 단위 분해
#   test_parse_searxng_multiline_desc    : 여러 줄 Description 결합
#   test_parse_searxng_rejects_garbage   : 형식 불일치 시 빈 list (통짜 폴백 유도)
#   test_search_web_uses_configured_name : 설정에 등록된 서버/도구명으로 호출
# ══════════════════════════════════════════════════════════════════════════════
import json
from unittest.mock import patch

from agri_ai_core.src.ai import mcp_client as mc
from agri_ai_core.src.ai.mcp_utils import parse_searxng_results


def _write_cfg(tmp_path, payload):
    p = tmp_path / "mcp.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_load_accepts_vscode_servers_key(tmp_path):
    p = _write_cfg(tmp_path, {"servers": {"searxng": {"command": "npx"}}})
    with patch.object(mc, "MCP_CONFIG_PATH", p):
        assert list(mc._load_mcp_servers().keys()) == ["searxng"]


def test_load_accepts_standard_key(tmp_path):
    p = _write_cfg(tmp_path, {"mcpServers": {"fetch": {"command": "npx"}}})
    with patch.object(mc, "MCP_CONFIG_PATH", p):
        assert list(mc._load_mcp_servers().keys()) == ["fetch"]


def test_load_missing_key_returns_empty(tmp_path):
    p = _write_cfg(tmp_path, {"somethingElse": {"a": 1}})
    with patch.object(mc, "MCP_CONFIG_PATH", p):
        assert mc._load_mcp_servers() == {}


def test_load_real_config_has_servers():
    # 실제 운영 설정이 0개로 로드되면 MCP 전체가 조용히 죽는다 — 회귀 방지
    servers = mc._load_mcp_servers()
    assert servers, "실제 .vscode/mcp.json 에서 MCP 서버가 하나도 로드되지 않음"
    assert mc._WEB_SEARCH_SERVER in servers, (
        f"검색 서버 '{mc._WEB_SEARCH_SERVER}' 가 설정에 없음 — 호출 시 not found")


def test_parse_searxng_basic():
    text = (
        "Title: 상황버섯 재배법\n"
        "Description: 온도 25도 유지가 핵심\n"
        "URL: https://example.com/a\n"
        "Relevance Score: 0.800\n"
        "\n"
        "Title: 버섯 습도 관리\n"
        "Description: 습도 90%\n"
        "URL: https://example.com/b\n"
        "Relevance Score: 0.700\n"
    )
    r = parse_searxng_results(text)
    assert len(r) == 2
    assert r[0]["title"] == "상황버섯 재배법"
    assert r[0]["url"] == "https://example.com/a"
    assert "25도" in r[0]["snippet"]
    assert r[1]["url"] == "https://example.com/b"
    # Relevance Score 는 결과에 섞이지 않는다
    assert "Relevance" not in r[0]["snippet"]


def test_parse_searxng_multiline_desc():
    text = (
        "Title: 제목\n"
        "Description: 첫 줄\n"
        "이어지는 둘째 줄\n"
        "URL: https://example.com/x\n"
    )
    r = parse_searxng_results(text)
    assert len(r) == 1
    assert "첫 줄" in r[0]["snippet"] and "둘째 줄" in r[0]["snippet"]


def test_parse_searxng_rejects_garbage():
    assert parse_searxng_results("") == []
    assert parse_searxng_results("그냥 평범한 텍스트") == []
    # URL 없는 항목은 유효하지 않다
    assert parse_searxng_results("Title: 제목만\nDescription: 설명만\n") == []


def test_search_web_uses_configured_name():
    seen = {}

    def _fake(server_name, tool_name, arguments, timeout=30):
        seen.update(server_name=server_name, tool_name=tool_name, args=arguments)
        return {"content": [{"type": "text", "text":
                             "Title: T\nDescription: D\nURL: https://e.com/1\n"}]}

    with patch.object(mc, "call_mcp_server_tool", _fake):
        out = mc.search_web("상황버섯", max_results=3)

    assert seen["server_name"] == mc._WEB_SEARCH_SERVER
    assert seen["tool_name"] == mc._WEB_SEARCH_TOOL
    assert seen["args"]["num_results"] == 3      # 'limit' 아님
    assert out["success"] is True
    assert out["results"][0]["url"] == "https://e.com/1"


# ⛔ 회귀 방지 (2026-07-17): communicate() 는 stdin 을 즉시 닫아, 초기화가 느린
#   MCP 서버(naver-search 실측)가 tools/call 을 처리하기 전에 종료되게 만들었다.
#   → "Failed to parse MCP tools/call response" 오진 + postgres 10.67s 오측정.
#   stdin 을 열어둔 채 target id 응답을 읽어야 한다.
def test_read_response_finds_target_id():
    import io as _io
    from agri_ai_core.src.ai import mcp_client as mc

    class _P:
        def __init__(self, lines):
            self.stdout = _io.StringIO("".join(lines))

    # 초기화 응답·notification 을 건너뛰고 id=2 를 찾아야 한다
    p = _P(['{"jsonrpc":"2.0","id":1,"result":{"ok":1}}\n',
            '{"jsonrpc":"2.0","method":"notifications/message"}\n',
            'not-json-noise\n',
            '{"jsonrpc":"2.0","id":2,"result":{"content":[]}}\n'])
    import time as _t
    resp, out = mc._read_response(p, 2, timeout=5, t_start=_t.time())
    assert resp is not None and resp["id"] == 2


def test_read_response_returns_none_on_eof():
    import io as _io, time as _t
    from agri_ai_core.src.ai import mcp_client as mc

    class _P:
        def __init__(self):
            self.stdout = _io.StringIO('{"jsonrpc":"2.0","id":1,"result":{}}\n')

    resp, out = mc._read_response(_P(), 2, timeout=5, t_start=_t.time())
    assert resp is None          # id=2 없이 EOF → None (호출측이 오류 처리)
    assert "id" in out           # 읽은 stdout 은 진단용으로 반환
