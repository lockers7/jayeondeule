# ══════════════════════════════════════════════════════════════════════════════
# test_tools_source_edit — 운영 소스 자율 변경 (4단계, 2026-07-17)
#
# ⛔ 이 도구는 LLM 이 자기가 도는 코드를 고친다. 안전의 축은 "차단"이 아니라
#   "되돌릴 수 있음" 이다. 두 가지를 못 박는다:
#     ① LLM 이 자기 안전장치를 지울 수 없다 (deny-list)
#     ② 테스트 실패한 코드는 운영에 남지 않는다 (자동 원복)
#
# 파일 시작 함수 목록:
#   test_deny_self               : 자기 자신 변경 불가 (지우면 모든 보호 무의미)
#   test_deny_safety_modules     : 인터록·비상가드·수온안전·관리자지시 보호
#   test_deny_boundaries         : 2·3단계 경계(스크립트/서비스) 보호
#   test_deny_secrets            : 시크릿 계열 보호
#   test_path_escape_blocked     : 경로 이탈 차단
#   test_allows_normal_module    : 일반 모듈은 과차단 없음
#   test_syntax_error_no_write   : 구문오류 시 파일 미변경
#   test_test_failure_reverts    : 테스트 실패 시 자동 원복 (핵심)
#   test_success_keeps_change    : 성공 시 변경 유지 + 감사기록
#   test_registered_in_5_places  : 5중 등록
# ══════════════════════════════════════════════════════════════════════════════
import hashlib
import os
from unittest.mock import patch

import pytest

from agri_ai_core.src.ai import tools_source_edit as tse


def _deny(path):
    return tse._deny_reason(path) is not None


def test_deny_self():
    # ⛔ 이걸 고칠 수 있으면 아래 모든 보호를 LLM 이 스스로 제거할 수 있다
    assert _deny("agri_ai_core/src/ai/tools_source_edit.py")


def test_deny_safety_modules():
    for p in ("agri_ai_core/src/control/interlock.py",
              "agri_ai_core/src/control/relay_manager.py",
              "agri_ai_core/src/control/environment_logic.py",
              "agri_ai_core/src/control/admin_directive.py",
              "agri_ai_core/src/ai/tools_db.py"):
        assert _deny(p), f"안전장치 미보호: {p}"


def test_deny_boundaries():
    for p in ("agri_ai_core/src/ai/tools_script.py",
              "agri_ai_core/src/ai/tools_service.py"):
        assert _deny(p), f"단계 경계 미보호: {p}"


def test_deny_secrets():
    for p in (".env", "agri_ai_core/src/ai/kakao_notify.py", "x/secret_key.py"):
        assert _deny(p), f"시크릿 미보호: {p}"


def test_path_escape_blocked():
    for bad in ("/etc/passwd.py", "../../../tmp/x.py", "x.sh"):
        r = tse.edit_source(bad, "print(1)\n", reason="pytest")
        assert r["success"] is False


def test_allows_normal_module():
    # 과차단이면 4단계가 무의미해진다
    assert not _deny("agri_ai_core/src/ai/tools_logs.py")
    assert not _deny("agri_ai_core/src/control/ai_control.py")


def test_syntax_error_no_write(tmp_path, monkeypatch):
    f = tmp_path / "m.py"
    f.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(tse, "_ROOT", str(tmp_path))
    r = tse.edit_source("m.py", "def broken(:\n", reason="pytest")
    assert r["success"] is False and "구문" in r["error"]
    assert f.read_text(encoding="utf-8") == "x = 1\n", "구문오류인데 파일이 변경됨"


def test_test_failure_reverts(tmp_path, monkeypatch):
    # 핵심: 테스트 실패 → 자동 원복 → 원본 완전 복구
    f = tmp_path / "m.py"
    orig = "x = 1\n"
    f.write_text(orig, encoding="utf-8")
    h0 = hashlib.md5(orig.encode()).hexdigest()
    monkeypatch.setattr(tse, "_ROOT", str(tmp_path))
    monkeypatch.setattr(tse, "_audit", lambda *a, **k: 1)
    monkeypatch.setattr(tse, "_run_pytest", lambda t: (False, "FAILED 1 test"))

    r = tse.edit_source("m.py", "x = 2\n", reason="pytest")
    assert r["success"] is False
    assert r["reverted"] is True
    assert hashlib.md5(f.read_text(encoding="utf-8").encode()).hexdigest() == h0, \
        "자동 원복 실패 — 깨진 코드가 운영에 남음"


def test_success_keeps_change(tmp_path, monkeypatch):
    f = tmp_path / "m.py"
    f.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(tse, "_ROOT", str(tmp_path))
    monkeypatch.setattr(tse, "_audit", lambda *a, **k: 7)
    monkeypatch.setattr(tse, "_run_pytest", lambda t: (True, "10 passed"))

    r = tse.edit_source("m.py", "x = 2\n", reason="pytest")
    assert r["success"] is True and r["tests_passed"] is True
    assert r["audit_id"] == 7
    assert f.read_text(encoding="utf-8") == "x = 2\n"
    assert "restart_service" in r["message"], "반영 방법 안내 누락"
    # 동일 내용 재변경은 거부
    assert tse.edit_source("m.py", "x = 2\n")["success"] is False


def test_registered_in_5_places():
    from agri_ai_core.src.ai.tools_definition import get_available_tools
    from agri_ai_core.src.ai.pipeline.question_analyzer import _VALID_TOOLS
    names = [t["function"]["name"] for t in get_available_tools()]
    for tool in ("edit_source", "revert_source", "list_source_edits"):
        assert tool in names, f"{tool} LLM 미노출"
        assert tool in _VALID_TOOLS, f"{tool} ANALYZER 누락"


# ⛔ 회귀 방지 (2026-07-17 실측): fetch_one 은 읽기 경로라 커밋하지 않는다.
#   INSERT..RETURNING 을 fetch_one 으로 하면 id 는 돌아오지만 행이 롤백돼
#   감사기록이 사라지고 revert_source 가 "없는 감사기록"으로 실패한다.
#   → 복원 가능성이 무너지므로 4단계의 안전 전제가 깨진다.
def test_audit_actually_persists(tmp_path, monkeypatch):
    from agri_ai_core.src.postgresql.connection import db_session

    f = tmp_path / "m.py"
    f.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(tse, "_ROOT", str(tmp_path))
    monkeypatch.setattr(tse, "_run_pytest", lambda t: (True, "ok"))

    r = tse.edit_source("m.py", "x = 2\n", reason="pytest 영속성")
    assert r["success"] is True
    aid = r["audit_id"]
    assert aid is not None, "감사 id 미반환"

    # 별도 세션에서 실제로 조회돼야 한다 (커밋됐다는 뜻)
    with db_session() as d:
        row = d.fetch_one("SELECT path, before_text FROM llm_source_audit WHERE id=%s", (aid,))
    assert row is not None, "감사기록이 롤백됨 — revert 불가 상태"
    assert row["before_text"] == "x = 1\n", "변경 전 내용이 보존되지 않음"

    with db_session() as d:
        d.execute_query("DELETE FROM llm_source_audit WHERE id=%s", (aid,))
