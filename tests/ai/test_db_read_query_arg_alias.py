# db_read_query 인자 별칭 견고화 — LLM 이 'sql' 대신 'query' 등으로 줘도 실행 (2026-07-19)
from dotenv import load_dotenv
load_dotenv("/workspace/jayeondeule/.env")
from agri_ai_core.src.ai.tools_executor import execute_tool


def _needs_db():
    import pytest
    s = execute_tool("db_read_query", {"sql": "SELECT 1 AS x"})
    if "DB 연결 실패" in s:
        pytest.skip("DB 연결 불가")


def test_query_key_alias_works():
    _needs_db()
    s = execute_tool("db_read_query", {"query": "SELECT 1 AS x"})
    assert "빈 쿼리" not in s
    assert "sql 이 필요" not in s


def test_sql_key_still_works():
    _needs_db()
    s = execute_tool("db_read_query", {"sql": "SELECT 1 AS x"})
    assert "빈 쿼리" not in s
