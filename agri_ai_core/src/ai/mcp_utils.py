# ════════════════════════════════════════════════════════════════
# MCP 순수 유틸리티 — 상태/통신 없는 pure helper 함수 모음
# 표준 JSON-RPC 빌더, 결과 추출, 검색 결과 포맷, 마크다운 표 파서 등이
# 포함된다 (mcp_client.py 에서 사용).
# --->
# build_jsonrpc: JSON-RPC 2.0 요청 payload 생성
# find_response_line: stdout 줄 단위 스캔으로 응답 ID 매칭
# extract_text_blocks: MCP result.content 배열에서 텍스트 블록 수집
# format_search_result: 웹 검색 결과 표준 dict 구성
# parse_markdown_table: 마크다운 표를 list[dict]로 변환
# parse_searxng_results: mcp-searxng 의 Title/Description/URL 텍스트 블록 파싱
# ════════════════════════════════════════════════════════════════
from typing import Any, Dict, List, Optional

from agri_ai_core.src.utils.json_utils import safe_json_load


# ────────────────────────────────────────────────────────────────────
# JSON-RPC 2.0 요청 payload 빌더.
# ────────────────────────────────────────────────────────────────────
def build_jsonrpc(id_value: int, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = {"jsonrpc": "2.0", "id": id_value, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


# ────────────────────────────────────────────────────────────────────
# stdout의 여러 줄 JSON 중 id가 response_id인 메시지를 찾아 반환.
# ────────────────────────────────────────────────────────────────────
def find_response_line(stdout: str, response_id: int) -> Optional[Dict[str, Any]]:
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


# ────────────────────────────────────────────────────────────────────
# MCP 도구 응답의 result.content 배열에서 type='text' 블록만 텍스트로 수집.
# ────────────────────────────────────────────────────────────────────
def extract_text_blocks(result: Dict[str, Any]) -> List[str]:
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


# ────────────────────────────────────────────────────────────────────
# 웹 검색 결과 항목을 표준 dict 형태로 생성.
# ────────────────────────────────────────────────────────────────────
def format_search_result(title: str, snippet: str, url: str, source: str = "web_search") -> Dict[str, Any]:
    return {"title": title, "snippet": snippet, "url": url, "source": source}


# ────────────────────────────────────────────────────────────────────
# mcp-searxng(searxng_web_search) 응답 파싱.
# 응답은 JSON 이 아니라 아래 형태의 구조화 텍스트 블록이다:
#   Title: ...
#   Description: ...
#   URL: https://...
#   Relevance Score: 0.800
#   (빈 줄로 항목 구분)
# Title/URL 이 모두 있는 항목만 유효로 본다. 형식이 어긋나면 빈 list 반환 →
# 호출측이 비구조 텍스트 폴백으로 처리.
# ────────────────────────────────────────────────────────────────────
def parse_searxng_results(text: str) -> List[Dict[str, Any]]:
    if not text or "Title:" not in text:
        return []
    out: List[Dict[str, Any]] = []
    cur: Dict[str, str] = {}

    def _flush():
        if cur.get("title") and cur.get("url"):
            out.append(format_search_result(
                cur["title"], (cur.get("description") or "")[:1000], cur["url"]))
        cur.clear()

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("Title:"):
            if cur.get("title"):        # 다음 항목 시작 — 직전 항목 확정
                _flush()
            cur["title"] = line[len("Title:"):].strip()
        elif line.startswith("Description:"):
            cur["description"] = line[len("Description:"):].strip()
        elif line.startswith("URL:"):
            cur["url"] = line[len("URL:"):].strip()
        elif line.startswith("Relevance Score:"):
            continue
        elif cur.get("description") is not None and not cur.get("url"):
            cur["description"] = f"{cur.get('description','')} {line}".strip()
    _flush()
    return out


# ────────────────────────────────────────────────────────────────────
# 마크다운 표 텍스트를 헤더 기반 list[dict]로 파싱.
# 구분선(---)은 자동 감지하여 skip. 헤더/데이터 컬럼 수 불일치 행은 제외.
# ────────────────────────────────────────────────────────────────────
def parse_markdown_table(text: str) -> List[Dict[str, Any]]:
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
