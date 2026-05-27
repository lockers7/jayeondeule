# ══════════════════════════════════════════════════════════════════════════════════════
# MCP 서버 프로세스 누수 재발방지 테스트.
# 2026-07-17 실장애: call_mcp_server_tool 성공 경로에 finally 가 없어 MCP 호출마다
# npx→sh→npm exec→node 트리가 통째로 잔존. 12시간 5,201개 누적 → RAM 94GB 고갈 →
# Ollama OOM-kill → 농장제어가 LLM 판단을 잃고 "keep(LLM 호출 실패)" 로 폴백.
# ⛔ 이 테스트들이 지키는 불변식을 훼손하지 말 것.
# --->
# test_terminate_reaps_process_tree: 손자까지 회수되는가 (npx 구조 모사)
# test_terminate_closes_stdin_for_graceful_exit: stdin EOF 자발종료 유도
# test_terminate_handles_none: None 안전
# test_terminate_survives_dead_process: 이미 죽은 프로세스에도 예외 없음
# test_all_popen_use_start_new_session: Popen 전수 프로세스그룹 분리
# test_call_paths_have_finally_terminate: Popen 함수 전수 finally 회수 보장
# ══════════════════════════════════════════════════════════════════════════════════════
import ast
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agri_ai_core.src.ai.mcp_client import _terminate

_MCP_CLIENT_PATH = (
    Path(__file__).resolve().parents[2] / "agri_ai_core" / "src" / "ai" / "mcp_client.py"
)


def _alive(pid: int) -> bool:
    try:
        import os

        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ────────────────────────────────────────────────────────────────────
# 핵심 회귀: 실장애는 손자 프로세스(node)가 살아남아 발생했다.
# sh -c 로 자식이 손자를 낳는 구조를 만들어 트리 회수를 검증한다.
# ────────────────────────────────────────────────────────────────────
def test_terminate_reaps_process_tree():
    proc = subprocess.Popen(
        ["sh", "-c", "sleep 300 & echo $!; wait"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    grandchild_pid = int(proc.stdout.readline().strip())
    assert _alive(grandchild_pid), "사전조건: 손자가 살아있어야 한다"

    _terminate(proc)
    time.sleep(1)

    assert proc.poll() is not None, "직계 자식이 회수되지 않았다"
    assert not _alive(grandchild_pid), (
        "손자 프로세스가 고아로 생존 — 2026-07-17 5,201개 누수의 재발"
    )


def test_terminate_closes_stdin_for_graceful_exit():
    proc = subprocess.Popen(
        ["cat"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    _terminate(proc)
    assert proc.poll() is not None, "stdin EOF 로 자발 종료되어야 한다"
    assert proc.stdin.closed, "stdin 이 닫히지 않았다"


def test_terminate_handles_none():
    _terminate(None)


def test_terminate_survives_dead_process():
    proc = subprocess.Popen(["true"], stdin=subprocess.PIPE, start_new_session=True)
    proc.wait()
    _terminate(proc)
    _terminate(proc)


# ────────────────────────────────────────────────────────────────────
# 정적 검증: 신규 Popen 이 추가되어도 규약을 강제한다.
# ────────────────────────────────────────────────────────────────────
def _popen_calls(tree):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "Popen":
            yield node


def test_all_popen_use_start_new_session():
    tree = ast.parse(_MCP_CLIENT_PATH.read_text(encoding="utf-8"))
    calls = list(_popen_calls(tree))
    assert calls, "Popen 호출을 찾지 못했다 — 테스트 전제 붕괴"
    for call in calls:
        kwargs = {kw.arg for kw in call.keywords}
        assert "start_new_session" in kwargs, (
            f"{_MCP_CLIENT_PATH.name}:{call.lineno} Popen 에 start_new_session=True 누락 "
            "— 프로세스그룹 분리 없이는 손자를 회수할 수 없다"
        )


def test_call_paths_have_finally_terminate():
    tree = ast.parse(_MCP_CLIENT_PATH.read_text(encoding="utf-8"))
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not list(_popen_calls(func)):
            continue
        finally_terminates = any(
            isinstance(n, ast.Try)
            and any(
                isinstance(c, ast.Call)
                and isinstance(c.func, ast.Name)
                and c.func.id == "_terminate"
                for stmt in n.finalbody
                for c in ast.walk(stmt)
            )
            for n in ast.walk(func)
        )
        assert finally_terminates, (
            f"{func.name}() 가 Popen 하지만 finally 에서 _terminate 하지 않는다 "
            "— 성공 경로 누수(2026-07-17 실장애)의 재발"
        )
