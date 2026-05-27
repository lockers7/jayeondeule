# ══════════════════════════════════════════════════════════════════════════════
# test_mcp_gateway_secret_guard — filesystem MCP 로 시크릿·안전장치 접근 차단
#
# 배경(2026-07-18): MCP_GATEWAY_ALLOW_WRITE=1(.env) 로 게이트웨이 쓰기가 열려 있어,
#   ① filesystem 루트가 레포 전체(/workspace/jayeondeule)라 mcp_call('filesystem',
#      'read_file',{path:'.env'}) 로 DB 비밀번호·API 키 열람 가능했고,
#   ② filesystem write 가 edit_source 의 안전장치 deny-list(interlock 등)를 우회했다.
#   자율은 유지하되(그 외 파일은 완전 자유) 시크릿·안전장치만 막는다.
#
# 파일 시작 함수 목록:
#   test_secret_read_blocked        : .env/mcp.json/*.key 읽기 차단
#   test_secret_write_blocked       : 시크릿 쓰기 차단
#   test_safety_source_write_blocked: interlock 등 안전장치 소스 쓰기 차단
#   test_safety_source_read_allowed : 안전장치 소스 읽기는 허용(source_read 대안)
#   test_normal_file_allowed        : 일반 파일 읽기·쓰기는 자유
#   test_nested_path_and_move       : 경로 우회(하위경로·move destination) 차단
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.ai.tools_mcp_gateway import _deny_reason


def test_secret_read_blocked():
    for path in (".env", ".vscode/mcp.json", "certs/server.key", "id_rsa.pem",
                 "config/credentials.json", "kakao_token.txt"):
        d = _deny_reason("filesystem", "read_file", {"path": path})
        assert d and "시크릿" in d, f"{path} 읽기가 차단되지 않음"


def test_secret_write_blocked():
    d = _deny_reason("filesystem", "write_file", {"path": ".env", "content": "x"})
    assert d and "시크릿" in d


def test_safety_source_write_blocked():
    for path in ("agri_ai_core/src/control/interlock.py",
                 "agri_ai_core/src/control/relay_manager.py",
                 "agri_ai_core/src/control/admin_directive.py"):
        d = _deny_reason("filesystem", "write_file", {"path": path, "content": "x"})
        assert d and "안전장치" in d, f"{path} 쓰기가 차단되지 않음"


def test_safety_source_read_allowed():
    # 안전장치 소스도 '읽기'는 허용 — source_read 대안이 있고, 읽기는 위험이 없다
    d = _deny_reason("filesystem", "read_file",
                     {"path": "agri_ai_core/src/control/interlock.py"})
    assert d is None, "안전장치 소스 읽기까지 막으면 과잉 — 읽기는 허용해야 함"


def test_normal_file_allowed():
    # 일반 파일은 읽기·쓰기 모두 자유(자율 최대). write 는 ALLOW_WRITE 게이트에 따름.
    assert _deny_reason("filesystem", "read_file",
                        {"path": "agri_ai_core/src/ai/tools_data.py"}) is None
    # searxng 등 비-filesystem 서버는 경로 가드 무관
    assert _deny_reason("searxng", "searxng_web_search", {"query": "버섯"}) is None


def test_nested_path_and_move():
    # 하위 경로로 .env 를 가리켜도 차단
    assert _deny_reason("filesystem", "read_file", {"path": "../../.env"}) is not None
    # move 의 destination 이 시크릿이어도 차단
    d = _deny_reason("filesystem", "move_file",
                     {"source": "a.txt", "destination": "secret_dump.key"})
    assert d is not None
