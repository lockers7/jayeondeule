# ════════════════════════════════════════════════════════════════
# MCP 순수 유틸리티 — 상태/통신 없는 pure helper 함수 모음
# mcp_client.py에서 분리된 표준 JSON-RPC 빌더, 결과 추출, 검색 결과 포맷,
# 마크다운 표 파서 등이 포함된다.
# --->
# build_jsonrpc: JSON-RPC 2.0 요청 payload 생성
# find_response_line: stdout 줄 단위 스캔으로 응답 ID 매칭
# extract_text_blocks: MCP result.content 배열에서 텍스트 블록 수집
# format_search_result: 웹 검색 결과 표준 dict 구성
# parse_markdown_table: 마크다운 표를 list[dict]로 변환
# ════════════════════════════════════════════════════════════════
from typing import Any, Dict, List, Optional

from agri_ai_core.src.utils.json_utils import safe_json_load


def build_jsonrpc(id_value: int, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """JSON-RPC 2.0 요청 payload 빌더."""
    payload = {"jsonrpc": "2.0", "id": id_value, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def find_response_line(stdout: str, response_id: int) -> Optional[Dict[str, Any]]:
    """stdout의 여러 줄 JSON 중 id가 response_id인 메시지를 찾아 반환."""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        message = safe_json_load(line)
        if not isinstance(message, dict):
            continue
        if message.get("id") == response_id:
            return message
    return None


def extract_text_blocks(result: Dict[str, Any]) -> List[str]:
    """MCP 도구 응답의 result.content 배열에서 type='text' 블록만 텍스트로 수집."""
    contents = result.get("content")
    if not isinstance(contents, list):
        return []
    texts: List[str] = []
    for item in contents:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text)
    return texts


def format_search_result(title: str, snippet: str, url: str, source: str = "web_search") -> Dict[str, Any]:
    """웹 검색 결과 항목을 표준 dict 형태로 생성."""
    return {"title": title, "snippet": snippet, "url": url, "source": source}


def parse_markdown_table(text: str) -> List[Dict[str, Any]]:
    """마크다운 표 텍스트를 헤더 기반 list[dict]로 파싱.
    구분선(---)은 자동 감지하여 skip. 헤더/데이터 컬럼 수 불일치 행은 제외."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    table_lines = [line for line in lines if line.startswith("|") and line.endswith("|")]
    if len(table_lines) < 2:
        return []

    header = [h.strip() for h in table_lines[0].strip("|").split("|")]
    data_start_idx = 1
    if set(table_lines[1].replace("|", "").replace("-", "").replace(" ", "")) == {""}:
        data_start_idx = 2

    rows: List[Dict[str, Any]] = []
    for line in table_lines[data_start_idx:]:
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) != len(header):
            continue
        rows.append(dict(zip(header, cols)))
    return rows
