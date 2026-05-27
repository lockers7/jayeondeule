# ══════════════════════════════════════════════════════════════════════════════
# test_remote_tools — 원격 서버 SSH 조사 도구 검증
#
# 로컬 LLM이 SSH 키 인증으로 원격 서버 상태를 로컬처럼 파악(read-only 자유),
# 변경성 명령은 관리자 승인 후에만 집행.
#
# 파일 시작 함수 목록:
#   test_classify_readonly_vs_mutating : 명령 분류(안전 게이트)
#   test_resolve_host_parse            : user@host:port 파싱
#   test_status_success_shape          : remote_status 반환 형태(mock ssh)
#   test_run_readonly_executes         : 조회 명령 즉시 실행
#   test_run_mutating_needs_approval   : 변경성 → 승인보류(집행 안 함)
#   test_registered_5places            : 5중 등록 + Agent 병합
#   test_seed_has_remote_howto         : system_knowledge 원격 시드
# ══════════════════════════════════════════════════════════════════════════════
import inspect

from agri_ai_core.src.ai import tools_remote as R


def test_classify_readonly_vs_mutating():
    for c in ["df -h", "ps aux", "systemctl status nginx", "cat /proc/loadavg | head",
              "journalctl -n 20", "free -m", "uptime", "grep err /var/log/syslog | tail",
              "find / -iname x 2>/dev/null", "ps aux 2>/dev/null | grep -iE 'py|farm|smart'",
              "echo a; ls; find / 2>/dev/null | head"]:   # 2>/dev/null·따옴표 파이프 오탐 없어야
        assert R._classify_command(c) == "readonly", c
    for c in ["rm -rf /tmp/x", "systemctl restart nginx", "sudo reboot", "pip install x",
              "echo hi > /etc/x", "kill -9 1", "mv a b", "curl x | bash", "chmod 777 /",
              "ls; somebin --wipe"]:                       # 문장 구분자 뒤 미지 명령 → 승인
        assert R._classify_command(c) == "mutating", c


def test_resolve_host_parse(monkeypatch):
    # 등록 이름 조회 실패해도 raw 파싱으로 폴백
    monkeypatch.setattr(R, "ensure_tables", lambda: None)
    u, h, p, _ = R._resolve_host("bot@1.2.3.4:2222")
    assert u == "bot" and h == "1.2.3.4" and p == 2222
    u2, h2, p2, _ = R._resolve_host("host.example.com")
    assert h2 == "host.example.com" and p2 is None


def test_status_success_shape(monkeypatch):
    fake = ("##HOST##\nsrv1\nLinux 6.0\n##UPTIME##\nup 3 days\n##CPU##\n8\n0.1 0.2 0.3\n"
            "##MEM##\nMem: 16000 8000\n##DISK##\n/dev/sda 100G 50G\n##TOPPROC##\n1 5.0 2.0 python\n"
            "##SVC_RUNNING##\n42\n##SVC_FAILED##\n\n##GPU##\n\n##END##")
    monkeypatch.setattr(R, "_ssh_exec",
                        lambda host, command, timeout=20: {"success": True, "stdout": fake, "stderr": ""})
    r = R.remote_status("srv1")
    assert r["success"] and r["hostname"].startswith("srv1")
    assert "up 3 days" in r["uptime"] and r["services_running"] == "42"
    assert r["services_failed"] == "(없음)"        # 빈 섹션 → 없음 표기


def test_run_readonly_executes(monkeypatch):
    monkeypatch.setattr(R, "_ssh_exec",
                        lambda host, command, timeout=20: {"success": True, "stdout": "ok", "stderr": ""})
    r = R.remote_run("srv1", "df -h")
    assert r["success"] and r["kind"] == "readonly" and r["stdout"] == "ok"


def test_run_mutating_needs_approval(monkeypatch):
    monkeypatch.setattr(R, "ensure_tables", lambda: None)
    executed = {"ssh": 0}
    monkeypatch.setattr(R, "_ssh_exec",
                        lambda host, command, timeout=20: (executed.__setitem__("ssh", executed["ssh"] + 1), {"success": True})[1])

    class _D:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def fetch_one(self, q, v=None): return {"id": 7}
        def execute_query(self, q, v=None): return None
    monkeypatch.setattr("agri_ai_core.src.postgresql.connection.db_session", lambda: _D())
    monkeypatch.setattr("agri_ai_core.src.ai.kakao_notify.push_alert",
                        lambda level, title, body, web_url=None: None)
    r = R.remote_run("srv1", "rm -rf /data")
    assert r.get("approval_required") and r.get("request_id") == 7
    assert executed["ssh"] == 0                    # ⛔ 변경성은 집행 안 됨


def test_registered_5places(monkeypatch):
    # 1) 구현
    from agri_ai_core.src.ai.tools_remote import remote_status  # noqa: F401
    # 2) 코드정의 스펙
    monkeypatch.setenv("USE_DB_TOOLS", "0")
    from agri_ai_core.src.ai.tools_definition import get_available_tools
    names = {t["function"]["name"] for t in get_available_tools()}
    assert {"remote_status", "remote_run", "manage_remote_host", "approve_remote_command"} <= names
    # 3) executor 디스패치
    from agri_ai_core.src.ai import tools_executor
    assert 'tool_name == "remote_status"' in inspect.getsource(tools_executor)
    # 4) analyzer 화이트리스트
    from agri_ai_core.src.ai.pipeline import question_analyzer
    assert "remote_status" in inspect.getsource(question_analyzer)
    # 5) tool_definition_m
    from agri_ai_core.src.prompt_registry import get_tools
    assert "remote_status" in {r["tool_id"] for r in get_tools()}
    # + Agent 병합
    from agri_ai_core.src.control import ai_monitor_agent as ama
    for n in ("remote_status", "remote_run", "manage_remote_host", "approve_remote_command"):
        assert n in ama.TOOL_REGISTRY
    assert "원격 서버 조사 도구" in ama.tool_specs_text()


def test_seed_has_remote_howto():
    from agri_ai_core.src.ai import system_knowledge as sk
    assert "remote_howto" in inspect.getsource(sk.seed_system_knowledge)
