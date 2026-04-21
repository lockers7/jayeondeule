# ════════════════════════════════════════════════════════════════════════════════
# URL 본문 수집 유틸 — HTTP 요청 + HTML 정제 + 병렬 자동 수집.
# tools_search.py에서 분리된 L5 계층 모듈. 공개 API는 fetch_url_content.
# --->
# _strip_html: HTML 태그/script/style 제거 후 텍스트만 추출
# _direct_fetch_url: urllib 직접 HTTP 가져오기 (MCP fallback용)
# _auto_fetch_urls: 검색 결과 상위 URL 본문을 병렬로 읽어 page_content로 저장
# fetch_url_content: 공개 API — MCP fetch → urllib 직접 요청 폴백
# ════════════════════════════════════════════════════════════════════════════════
import os
import re
import time
from typing import Dict, Any

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_WEB_SEARCH_CONTENT_MAX_CHARS = max(500, int(os.getenv("WEB_SEARCH_CONTENT_MAX_CHARS", "2000")))


# ────────────────────────────────────────────────────────────────────
# HTML → 텍스트 변환 (script/style 제거)
# ────────────────────────────────────────────────────────────────────
def _strip_html(raw_text: str) -> str:
    text = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', raw_text, flags=re.IGNORECASE)
    text = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ────────────────────────────────────────────────────────────────────
# urllib로 직접 URL을 가져온다 (MCP fallback용).
# ────────────────────────────────────────────────────────────────────
def _direct_fetch_url(url: str, timeout: int = 15) -> Dict[str, Any]:
    logger.debug(f"[직접HTTP] 요청 시작 url={url[:120]} timeout={timeout}s")
    from urllib import request as urlrequest, error as urlerror

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
    }
    req = urlrequest.Request(url, headers=headers)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return {"success": True, "text": raw}
    except urlerror.HTTPError as e:
        logger.warning(f"[직접HTTP] HTTPError url={url[:120]} code={e.code}")
        return {"success": False, "text": f"HTTP {e.code}"}
    except Exception as e:
        return {"success": False, "text": str(e)}


# ────────────────────────────────────────────────────────────────────
# 검색 결과 상위 URL의 본문을 병렬로 읽어 item["page_content"]에 주입.
# 부작용 함수 — 인자로 받은 results 리스트를 직접 변경한다.
# ────────────────────────────────────────────────────────────────────
def _auto_fetch_urls(results: list, max_fetch: int = 3) -> None:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    urls_to_fetch = []
    for item in results[:max_fetch]:
        url = item.get("url", "")
        if url and not any(skip in url for skip in ["youtube.com", "apkgk.com"]):
            urls_to_fetch.append((item, url))

    if not urls_to_fetch:
        return

    def _fetch_one(item_url_pair):
        item, url = item_url_pair
        content_result = _direct_fetch_url(url, timeout=10)
        if content_result.get("success"):
            text = _strip_html(content_result.get("text", ""))
            if len(text) > _WEB_SEARCH_CONTENT_MAX_CHARS:
                text = text[:_WEB_SEARCH_CONTENT_MAX_CHARS]
            item["page_content"] = text
            return True
        return False

    try:
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_fetch_one, pair): pair for pair in urls_to_fetch}
            for future in as_completed(futures, timeout=15):
                try:
                    future.result()
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"[웹검색] 자동 본문 읽기 중 오류: {e}")


# ────────────────────────────────────────────────────────────────────
# URL의 웹페이지 본문 텍스트를 가져온다 (공개 API).
# MCP fetch → 실패시 urllib 직접 요청으로 fallback.
# ────────────────────────────────────────────────────────────────────
def fetch_url_content(url: str) -> Dict[str, Any]:
    t_start = time.time()
    logger.info(f"[URL본문] 시작 url={url[:120]}")
    MAX_CONTENT_LEN = 8000

    try:
        # 1차: MCP fetch 시도
        from agri_ai_core.src.ai.mcp_client import mcp_fetch_request
        result = mcp_fetch_request(url=url, method="GET", timeout=15)
        raw_text = ""

        if result.get("success"):
            raw_text = result.get("text", "") or ""
            logger.info(f"[URL본문] MCP fetch 성공 url={url[:120]} raw_len={len(raw_text)}자")
        else:
            # 2차: 직접 HTTP 요청 fallback
            mcp_error = result.get("text", "")[:80]
            logger.info(f"[URL본문] MCP fetch 실패 → 직접 HTTP 요청 시도 (mcp_error={mcp_error})")
            direct_result = _direct_fetch_url(url, timeout=15)
            if direct_result.get("success"):
                raw_text = direct_result.get("text", "") or ""
                logger.info(f"[URL본문] 직접 HTTP 성공 raw_len={len(raw_text)}자")
            else:
                elapsed = time.time() - t_start
                error_msg = direct_result.get("text", "URL 본문을 가져올 수 없습니다.")
                logger.warning(f"[URL본문] 최종 실패 ({elapsed:.1f}s) url={url[:120]} error={error_msg}")
                return {"success": False, "error": error_msg, "url": url}

        # HTML → 텍스트 변환
        text = _strip_html(raw_text)

        # 본문이 너무 길면 앞부분만 (LLM 컨텍스트 보호)
        truncated = False
        if len(text) > MAX_CONTENT_LEN:
            text = text[:MAX_CONTENT_LEN]
            truncated = True

        elapsed = time.time() - t_start
        logger.info(f"[URL본문] 완료 ({elapsed:.1f}s) content_len={len(text)}자 truncated={truncated}")
        return {
            "success": True,
            "url": url,
            "content": text,
            "content_length": len(text),
            "truncated": truncated,
        }

    except Exception as e:
        elapsed = time.time() - t_start
        logger.error(f"[URL본문] 오류 ({elapsed:.1f}s): {e}")
        return {"success": False, "error": str(e), "url": url}
