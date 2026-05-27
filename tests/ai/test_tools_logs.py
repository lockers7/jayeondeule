# ══════════════════════════════════════════════════════════════════════════════
# test_tools_logs — 로그 분석 도구(읽기 전용) 검증
#
# 배경: 로그는 3GB(하루 56만 줄, 파일당 80MB) 규모라 source_* 로는 접근 불가
#   (logs 가 제외 디렉토리 + 400줄 캡). grep/tail 기반 전용 도구가 필요했다.
#
# 파일 시작 함수 목록:
#   test_safe_path_blocks_traversal   : 경로 이탈(../) 차단
#   test_safe_path_rejects_non_log    : .log 아닌 파일 거부
#   test_mask_secrets                 : 시크릿 값 마스킹
#   test_cap_limits                   : 줄수/문자수 캡 + truncated 플래그
#   test_search_level_filter          : 레벨 필터 + matched 전체 건수
#   test_search_query_and             : 다중어 AND 검색
#   test_search_tail_mode             : 조건 없으면 최근 N줄
#   test_search_invalid_level         : 잘못된 레벨 거부
#   test_search_missing_target        : 대상 로그 없으면 안내 반환
#   test_list_log_files               : 파일 목록 + 크기
# ══════════════════════════════════════════════════════════════════════════════
import os
from unittest.mock import patch

import pytest

from agri_ai_core.src.ai import tools_logs as tl


@pytest.fixture
def fake_logs(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    (d / "ai_2026-01-01.log").write_text(
        "[2026-01-01 00:00:01,000] [INFO] [mod] -> 순환밸브 relay_10 ON\n"
        "[2026-01-01 00:00:02,000] [ERROR] [mod] -> DB 연결 실패\n"
        "[2026-01-01 00:00:03,000] [ERROR] [mod] -> 순환밸브 relay_10 OFF\n"
        "[2026-01-01 00:00:04,000] [WARNING] [mod] -> 수온 결함\n",
        encoding="utf-8")
    (d / "web.log").write_text("[2026-01-01 00:00:01,000] [INFO] [web] -> ok\n",
                              encoding="utf-8")
    with patch.object(tl, "_ROOT", str(tmp_path)):
        yield d


def test_safe_path_blocks_traversal(fake_logs):
    assert tl._safe_log_file("../../etc/passwd") is None
    assert tl._safe_log_file("../secret.log") is None


def test_safe_path_rejects_non_log(fake_logs):
    (fake_logs / "data.txt").write_text("x", encoding="utf-8")
    assert tl._safe_log_file("data.txt") is None
    assert tl._safe_log_file("ai_2026-01-01.log") is not None


def test_mask_secrets():
    assert "***" in tl._mask_secrets('password="hunter2"')
    assert "hunter2" not in tl._mask_secrets('password="hunter2"')
    assert "***" in tl._mask_secrets("api_key=ABCDEF123")
    # 일반 로그는 그대로
    plain = "[INFO] 순환밸브 ON"
    assert tl._mask_secrets(plain) == plain


def test_cap_limits():
    lines, trunc = tl._cap([f"line{i}" for i in range(10)], 3)
    assert len(lines) == 3 and trunc is True
    lines, trunc = tl._cap(["a", "b"], 5)
    assert len(lines) == 2 and trunc is False


def test_search_level_filter(fake_logs):
    r = tl.search_logs(level="ERROR", date="2026-01-01", max_results=10)
    assert r["success"] is True
    assert r["matched"] == 2                 # 전체 매칭 건수 — "몇 건" 답변용
    assert all("[ERROR]" in ln for ln in r["lines"])


def test_search_query_and(fake_logs):
    # 두 단어 AND — 둘 다 포함한 줄만
    r = tl.search_logs(query="순환밸브 relay_10", date="2026-01-01", max_results=10)
    assert r["matched"] == 2
    # 레벨 + 검색어 조합
    r2 = tl.search_logs(query="순환밸브", level="ERROR", date="2026-01-01")
    assert r2["matched"] == 1
    assert "OFF" in r2["lines"][0]


def test_search_tail_mode(fake_logs):
    r = tl.search_logs(date="2026-01-01", max_results=2)
    assert r["mode"] == "tail"
    assert len(r["lines"]) == 2
    assert "수온 결함" in r["lines"][-1]      # 최근 줄


def test_search_invalid_level(fake_logs):
    r = tl.search_logs(level="NOPE", date="2026-01-01")
    assert r["success"] is False


def test_search_missing_target(fake_logs):
    r = tl.search_logs(date="1999-12-31", max_results=5)
    assert r["success"] is False
    assert "대상 로그 없음" in r["error"]


def test_list_log_files(fake_logs):
    r = tl.list_log_files()
    assert r["success"] is True
    names = [f["file"] for f in r["files"]]
    assert "ai_2026-01-01.log" in names and "web.log" in names
