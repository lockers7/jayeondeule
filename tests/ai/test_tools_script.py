# ══════════════════════════════════════════════════════════════════════════════
# test_tools_script — 스크립트 작성·실행 도구 (2단계, 2026-07-17)
#
# ⛔ 이 경계들은 3단계(서버관리)·4단계(소스변경)의 전제다. 완화 금지.
#   scripts/llm/ 밖 작성·실행 불가 / .py 만 / 구문검증 통과분만 저장 /
#   sudo 없음 / timeout / 감사기록
#
# 파일 시작 함수 목록:
#   test_path_escape_blocked      : 경로이탈·절대경로·비.py 차단
#   test_syntax_error_not_written : 구문오류는 파일로 남지 않음
#   test_write_run_roundtrip      : 작성→실행→stdout 왕복
#   test_run_failure_returns_stderr : 실행 실패 시 LLM 이 stderr 를 읽을 수 있음
#   test_timeout_enforced         : timeout 강제
#   test_missing_script           : 없는 스크립트 실행 시 안내
#   test_list_and_read            : 목록·본문 조회
#   test_registered_in_5_places   : 5중 등록 (도구 노출·ANALYZER·executor)
# ══════════════════════════════════════════════════════════════════════════════
import os

import pytest

from agri_ai_core.src.ai import tools_script as ts


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    d = tmp_path / "llm"
    d.mkdir()
    monkeypatch.setattr(ts, "_SCRIPT_DIR", str(d))
    monkeypatch.setattr(ts, "_audit", lambda *a, **k: None)   # DB 분리
    yield d


def test_path_escape_blocked(sandbox):
    for bad in ("../../etc/x.py", "/etc/passwd.py", "evil.sh", "../../../tmp/x.py"):
        r = ts.write_script(bad, "print(1)")
        assert r["success"] is False, f"경로 우회됨: {bad}"
        r = ts.run_script(bad)
        assert r["success"] is False, f"실행 경로 우회됨: {bad}"


def test_syntax_error_not_written(sandbox):
    r = ts.write_script("broken.py", "def f(:\n  pass")
    assert r["success"] is False and "구문" in r["error"]
    assert not (sandbox / "broken.py").exists(), "구문오류 코드가 디스크에 남음"


def test_write_run_roundtrip(sandbox):
    r = ts.write_script("hello.py", "print('안녕 농장')", reason="pytest")
    assert r["success"] is True and r["action"] == "작성"
    r = ts.run_script("hello.py", reason="pytest")
    assert r["success"] is True and r["returncode"] == 0
    assert "안녕 농장" in r["stdout"]
    # 재작성은 '수정'
    r = ts.write_script("hello.py", "print('수정됨')", reason="pytest")
    assert r["action"] == "수정"


def test_run_failure_returns_stderr(sandbox):
    ts.write_script("err.py", "raise ValueError('의도된 오류')")
    r = ts.run_script("err.py")
    assert r["success"] is False and r["returncode"] != 0
    assert "ValueError" in r["stderr"], "LLM 이 오류를 읽고 고칠 수 없음"


def test_timeout_enforced(sandbox):
    ts.write_script("slow.py", "import time; time.sleep(30)")
    r = ts.run_script("slow.py", timeout=2)
    assert r["success"] is False and "초" in r["error"]


def test_missing_script(sandbox):
    r = ts.run_script("nope.py")
    assert r["success"] is False and "없는 스크립트" in r["error"]


def test_list_and_read(sandbox):
    ts.write_script("a.py", "x = 1")
    r = ts.list_scripts()
    assert r["success"] is True and "a.py" in [s["script"] for s in r["scripts"]]
    r = ts.read_script("a.py")
    assert r["success"] is True and "x = 1" in r["content"]
    assert ts.read_script("../../etc/passwd.py")["success"] is False


def test_registered_in_5_places():
    # 5중 등록이 하나라도 빠지면 LLM 이 도구를 못 쓰거나 ANALYZER 가 계획을 폐기한다
    from agri_ai_core.src.ai.tools_definition import get_available_tools
    from agri_ai_core.src.ai.pipeline.question_analyzer import _VALID_TOOLS
    names = [t["function"]["name"] for t in get_available_tools()]
    for tool in ("write_script", "run_script", "list_scripts", "read_script"):
        assert tool in names, f"{tool} LLM 미노출 (tool_definition_m/코드 확인)"
        assert tool in _VALID_TOOLS, f"{tool} ANALYZER _VALID_TOOLS 누락"
