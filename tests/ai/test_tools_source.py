# ══════════════════════════════════════════════════════════════════════════════
# test_tools_source — 소스 분석 도구(읽기 전용) 검증
#
# 파일 시작 함수 목록:
#   test_search_finds_known_code   : 실소스에서 알려진 문구 검색
#   test_read_with_line_numbers    : 줄번호 포함 구간 읽기 + 캡
#   test_list_with_pattern         : 파일명 필터 목록
#   test_blocks_secrets            : .env/시크릿 열람 차단
#   test_blocks_outside_root       : 루트 밖 경로 차단
#   test_blocks_excluded_dirs      : venv/node_modules 등 제외 경로 차단
#   test_executor_dispatch         : tools_executor 연결 확인
# ══════════════════════════════════════════════════════════════════════════════
import json

from agri_ai_core.src.ai.tools_source import source_list, source_search, source_read


def test_search_finds_known_code():
    r = source_search("FAN_VALVE_GATE", "agri_ai_core/src/control")
    assert r["success"] is True and r["count"] >= 1
    assert "interlock.py" in r["message"]


def test_read_with_line_numbers():
    r = source_read("agri_ai_core/src/control/interlock.py", 1, 10)
    assert r["success"] is True
    assert "    1|" in r["message"] and "   10|" in r["message"]
    assert "   11|" not in r["message"]
    # 400줄 캡
    r2 = source_read("agri_ai_core/src/ai/tools_definition.py", 1, 9999)
    body_lines = [l for l in r2["message"].splitlines() if "|" in l]
    assert len(body_lines) <= 401


def test_list_with_pattern():
    r = source_list("agri_ai_core/src/ai", "tools_")
    assert r["success"] is True and r["count"] >= 5
    assert "tools_source.py" in r["message"]


def test_blocks_secrets():
    assert source_read(".env")["success"] is False
    assert source_read("agri_ai_core/../.env")["success"] is False


def test_blocks_outside_root():
    assert source_read("../../../etc/passwd")["success"] is False
    assert source_list("/etc")["success"] is False


def test_blocks_excluded_dirs():
    assert source_list("venv")["success"] is False
    assert source_read("web/frontend/node_modules/react/package.json")["success"] is False


def test_multiword_or_search():
    # LLM 이 멀티워드로 검색 — OR 매칭 + 관련도순으로 잡혀야 함
    r = source_search("interlock 흡입팬 배출팬 밸브 선행", "agri_ai_core/src/control")
    assert r["success"] is True and r["count"] >= 3
    assert "interlock.py" in r["message"].splitlines()[1]  # 최상위가 인터록 관련


def test_placeholder_rescue():
    # source_read 플레이스홀더 → 직전 검색 최다매치 파일 자동 대체
    import json as _json
    from agri_ai_core.src.ai.pipeline.data_collector import DataCollector
    dc = DataCollector(default_tool_args={}, raw_user_query="인터록 소스 설명")
    raw = _json.dumps({"success": True, "message":
        "agri_ai_core/src/control/interlock.py:10:...\n"
        "agri_ai_core/src/control/interlock.py:20:...\n"
        "agri_ai_core/src/control/relay_manager.py:5:..."})
    dc.collected_data.append({"tool": "source_search", "result": "요약", "raw": raw})
    merged = dc._merge_args("source_read",
                            {"file_path": "(source_search 결과로 찾은 파일 경로)"})
    assert merged["file_path"] == "agri_ai_core/src/control/interlock.py"
    # 정상 경로는 대체하지 않음
    merged2 = dc._merge_args("source_read", {"file_path": "agri_ai_core/api/app.py"})
    assert merged2["file_path"] == "agri_ai_core/api/app.py"


def test_executor_dispatch():
    from agri_ai_core.src.ai.tools_executor import execute_tool
    raw = execute_tool("source_search", {"query": "def source_read", "path": "agri_ai_core/src/ai"})
    assert json.loads(raw).get("success") is True
