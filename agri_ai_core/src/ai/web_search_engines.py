# ════════════════════════════════════════════════════════════════════════════════
# 웹 검색 엔진 구현 — Naver / Brave / SearXNG 및 통합 라우터
# tools_search.py에서 분리된 L5 계층 모듈. 공개 API는 _search_via_api.
# --->
# _search_via_naver_api: Naver 검색 API 호출 (client_id/secret 필요)
# _search_via_brave_api: Brave Search API 호출 (api key 필요)
# _search_via_searxng: 자체 호스팅 SearXNG 메타검색 엔진 호출
# _merge_search_results: primary(Naver) + secondary(SearXNG) 인터리브 병합
# _search_via_api: 3개 엔진 중 사용 가능한 것 자동 선택 호출
# ════════════════════════════════════════════════════════════════════════════════
import json
import os
import re
import time
import threading
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, Any, List, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.utils import has_korean as _is_korean_query

logger = setup_logger(__name__)

_WEB_SEARCH_RESULT_LIMIT = max(3, int(os.getenv("WEB_SEARCH_RESULT_LIMIT", "8")))


# ══════════════════════════════════════════════════════
# Naver 검색 API를 통한 검색 (블로그 + 뉴스)
# Returns: 검색 결과 리스트 또는 None (API 키 없음/실패)
# ══════════════════════════════════════════════════════
def _search_via_naver_api(query: str, display: int = 10) -> Optional[List[Dict[str, Any]]]:
    client_id = os.getenv("NAVER_CLIENT_ID", "").strip()
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None

    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }

    results = []
    seen_urls = set()

    # 블로그 + 뉴스 2개 카테고리 검색
    categories = [
        ("blog", f"https://openapi.naver.com/v1/search/blog.json?query={urllib.parse.quote(query)}&display={display}&sort=sim"),
        ("news", f"https://openapi.naver.com/v1/search/news.json?query={urllib.parse.quote(query)}&display={display}&sort=sim"),
    ]

    for cat_name, url in categories:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            for item in data.get("items", []):
                link = item.get("link", "")
                if not link or link in seen_urls:
                    continue
                seen_urls.add(link)

                # HTML 태그 제거
                title = re.sub(r'<[^>]+>', '', item.get("title", ""))
                description = re.sub(r'<[^>]+>', '', item.get("description", ""))

                results.append({
                    "title": title,
                    "url": link,
                    "description": description,
                    "source": f"naver_{cat_name}",
                })

            logger.info(f"[NaverAPI] {cat_name} 검색 완료: {len(data.get('items', []))}건")

        except urllib.error.HTTPError as e:
            logger.warning(f"[NaverAPI] {cat_name} HTTP 오류: {e.code}")
            if e.code == 429:
                logger.warning("[NaverAPI] API 호출 한도 초과")
            continue
        except Exception as e:
            logger.warning(f"[NaverAPI] {cat_name} 오류: {e}")
            continue

    if not results:
        return None

    logger.info(f"[NaverAPI] 총 {len(results)}건 검색 완료 query=\"{query[:50]}\"")
    return results


# ══════════════════════════════════════════════════════
# Brave Search API를 통한 검색
# Returns: 검색 결과 리스트 또는 None (API 키 없음/실패)
# ══════════════════════════════════════════════════════
def _search_via_brave_api(query: str, count: int = 10) -> Optional[List[Dict[str, Any]]]:
    api_key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    if not api_key:
        return None

    params = urllib.parse.urlencode({
        "q": query,
        "count": count,
        "search_lang": "ko",
        "country": "KR",
        "text_decorations": "false",
    })
    url = f"https://api.search.brave.com/res/v1/web/search?{params}"

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            # gzip 처리
            if resp.headers.get("Content-Encoding") == "gzip":
                import gzip
                raw = gzip.decompress(resp.read())
            else:
                raw = resp.read()
            data = json.loads(raw.decode("utf-8"))

        results = []
        web_results = data.get("web", {}).get("results", [])
        for item in web_results:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
                "source": "brave",
            })

        logger.info(f"[BraveAPI] {len(results)}건 검색 완료 query=\"{query[:50]}\"")
        return results if results else None

    except urllib.error.HTTPError as e:
        logger.warning(f"[BraveAPI] HTTP 오류: {e.code}")
        if e.code == 429:
            logger.warning("[BraveAPI] API 호출 한도 초과")
        return None
    except Exception as e:
        logger.warning(f"[BraveAPI] 오류: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════
# SearXNG 자체 호스팅 메타 검색 엔진을 통한 검색
# 무료, API 키 불필요, 다중 검색엔진 (Google/Naver/Bing/DuckDuckGo) 통합
# Returns: 검색 결과 리스트 또는 None (SearXNG 미실행/실패)
# ══════════════════════════════════════════════════════════════════════
def _search_via_searxng(query: str, count: Optional[int] = None) -> Optional[List[Dict[str, Any]]]:
    searxng_url = os.getenv("SEARXNG_URL", "").strip()
    if not searxng_url:
        return None
    if count is None:
        count = _WEB_SEARCH_RESULT_LIMIT

    # 한국 농장 시스템 — 항상 한국어 결과 우선 (LLM이 외국어 query 생성해도 한국어 결과 반환)
    lang = "ko-KR"

    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "language": lang,
        "pageno": 1,
    })
    url = f"{searxng_url}/search?{params}"

    try:
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "AgriAI-Core/1.0",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = []
        seen_urls = set()
        for item in data.get("results", []):
            item_url = item.get("url", "")
            if not item_url or item_url in seen_urls:
                continue
            seen_urls.add(item_url)

            results.append({
                "title": item.get("title", ""),
                "url": item_url,
                "description": item.get("content", ""),
                "source": f"searxng_{item.get('engine', 'unknown')}",
            })

            if len(results) >= count:
                break

        # SearXNG 즉답(answers) + 지식패널(infoboxes) 수집 — 기존 results 파이프라인에 영향 없이 추가 데이터 제공
        answers = data.get("answers", []) or []
        infoboxes = data.get("infoboxes", []) or []
        if answers:
            logger.info(f"[SearXNG] 즉답(answers) {len(answers)}건 확보")
        if infoboxes:
            logger.info(f"[SearXNG] 지식패널(infoboxes) {len(infoboxes)}건 확보")

        # answers/infoboxes 텍스트를 results 앞에 우선 정보로 삽입
        priority_items = []
        for ans in answers[:2]:
            if isinstance(ans, str) and ans.strip():
                priority_items.append({
                    "title": "[즉답]",
                    "url": "",
                    "description": ans.strip(),
                    "source": "searxng_answer",
                })
        for ibox in infoboxes[:1]:
            if isinstance(ibox, dict):
                ibox_content = ibox.get("content", "")
                ibox_title = ibox.get("infobox", "")
                if ibox_content:
                    priority_items.append({
                        "title": f"[지식] {ibox_title}",
                        "url": ibox.get("urls", [{}])[0].get("url", "") if ibox.get("urls") else "",
                        "description": ibox_content[:500],
                        "source": "searxng_infobox",
                    })

        if priority_items:
            results = priority_items + results

        engines_used = list(set(item.get("engine", "") for item in data.get("results", []) if item.get("engine")))
        logger.info(f"[SearXNG] {len(results)}건 검색 완료 engines={engines_used[:5]} query=\"{query[:50]}\"")
        return results if results else None

    except urllib.error.URLError as e:
        logger.warning(f"[SearXNG] 연결 실패 (SearXNG 미실행?): {e}")
        return None
    except Exception as e:
        logger.warning(f"[SearXNG] 오류: {e}")
        return None


# ════════════════════════════════════════════════════════
# 두 검색 결과 병합 (URL 중복 제거, primary 우선 인터리브)
# ════════════════════════════════════════════════════════
def _merge_search_results(
    primary: List[Dict[str, Any]],
    secondary: List[Dict[str, Any]],
    max_count: int = 10,
) -> List[Dict[str, Any]]:
    """primary(Naver) 와 secondary(SearXNG) 를 인터리브 병합.
    URL 중복 제거 후 primary 1건 → secondary 1건 순으로 교차 삽입.
    """
    seen_urls: set = set()
    merged: List[Dict[str, Any]] = []

    pri_q = list(primary)
    sec_q = list(secondary)

    while (pri_q or sec_q) and len(merged) < max_count:
        if pri_q:
            item = pri_q.pop(0)
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                merged.append(item)
        if sec_q and len(merged) < max_count:
            item = sec_q.pop(0)
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                merged.append(item)

    return merged


# ═════════════════════════════════════════════════════════
# API 검색 통합 라우터
# 한국어: SearXNG + NaverAPI 병렬 실행 → 결과 인터리브 병합
# 영어:   SearXNG → Brave → Naver 순차 폴백
# ═════════════════════════════════════════════════════════
def _search_via_api(query: str, count: Optional[int] = None) -> Optional[Dict[str, Any]]:
    t_start = time.time()
    is_korean = _is_korean_query(query)

    target_count = max(3, int(count or _WEB_SEARCH_RESULT_LIMIT))
    naver_display = min(10, target_count)
    brave_count = min(20, target_count)

    from agri_ai_core.src.ai.stats_collector import get_stats_collector

    # ── 한국어: SearXNG + Naver 병렬 실행 후 병합 ──────────────
    if is_korean:
        searxng_results: List[Dict[str, Any]] = []
        naver_results: List[Dict[str, Any]] = []

        def _run_searxng() -> None:
            try:
                r = _search_via_searxng(query, count=target_count)
                if r:
                    searxng_results.extend(r)
                    get_stats_collector().record_search("searxng", success=True)
                else:
                    get_stats_collector().record_search("searxng", success=False)
            except Exception as e:
                logger.warning(f"[API검색] searxng 실패: {e}")
                get_stats_collector().record_search("searxng", success=False)

        def _run_naver() -> None:
            try:
                r = _search_via_naver_api(query, display=naver_display)
                if r:
                    naver_results.extend(r)
                    get_stats_collector().record_search("naver", success=True)
                else:
                    get_stats_collector().record_search("naver", success=False)
            except Exception as e:
                logger.warning(f"[API검색] naver 실패: {e}")
                get_stats_collector().record_search("naver", success=False)

        t_sx = threading.Thread(target=_run_searxng, daemon=True)
        t_nv = threading.Thread(target=_run_naver, daemon=True)
        t_sx.start()
        t_nv.start()
        t_sx.join(timeout=16)   # SearXNG 자체 timeout 15s + 여유
        t_nv.join(timeout=6)    # Naver API 는 빠름

        elapsed = time.time() - t_start

        if naver_results or searxng_results:
            merged = _merge_search_results(naver_results, searxng_results, max_count=target_count)
            providers = []
            if naver_results:
                providers.append(f"naver({len(naver_results)}건)")
            if searxng_results:
                providers.append(f"searxng({len(searxng_results)}건)")
            logger.info(
                f"[API검색] 병렬병합 완료 ({elapsed:.1f}s) "
                f"{' + '.join(providers)} → 병합={len(merged)}건"
            )
            return {
                "success": True,
                "query": query,
                "results": merged,
                "search_provider": "naver+searxng" if (naver_results and searxng_results)
                                   else ("naver" if naver_results else "searxng"),
            }

        # 병렬 모두 실패 → Brave 폴백
        try:
            brave_res = _search_via_brave_api(query, count=brave_count)
            if brave_res:
                elapsed = time.time() - t_start
                logger.info(f"[API검색] brave 폴백 성공 ({elapsed:.1f}s) {len(brave_res)}건")
                get_stats_collector().record_search("brave", success=True)
                return {"success": True, "query": query, "results": brave_res, "search_provider": "brave"}
        except Exception as e:
            logger.warning(f"[API검색] brave 실패: {e}")
            get_stats_collector().record_search("brave", success=False)

    # ── 영어: 기존 순차 폴백 ────────────────────────────────────
    else:
        search_order = [
            ("searxng", lambda: _search_via_searxng(query, count=target_count)),
            ("brave",   lambda: _search_via_brave_api(query, count=brave_count)),
            ("naver",   lambda: _search_via_naver_api(query, display=naver_display)),
        ]
        for provider_name, search_fn in search_order:
            try:
                results = search_fn()
                if results:
                    elapsed = time.time() - t_start
                    logger.info(f"[API검색] {provider_name} 성공 ({elapsed:.1f}s) {len(results)}건")
                    get_stats_collector().record_search(provider_name, success=True)
                    return {
                        "success": True,
                        "query": query,
                        "results": results,
                        "search_provider": provider_name,
                    }
            except Exception as e:
                logger.warning(f"[API검색] {provider_name} 실패: {e}")
                get_stats_collector().record_search(provider_name, success=False)
                continue

    elapsed = time.time() - t_start
    logger.info(f"[API검색] 모든 API 실패 또는 미설정 ({elapsed:.1f}s) → MCP fallback")
    return None
