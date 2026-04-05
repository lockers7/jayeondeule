# ════════════════════════════════════════════════════════════
# LLM Tool — 웹 검색 및 URL 본문 가져오기 모듈.
# ════════════════════════════════════════════════════════════
import json
import os
import re
import time
import threading
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from typing import Dict, Any, List, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.utils import has_korean as _is_korean_query

logger = setup_logger(__name__)

_WEB_SEARCH_RESULT_LIMIT = max(3, int(os.getenv("WEB_SEARCH_RESULT_LIMIT", "8")))
_WEB_SEARCH_AUTO_FETCH_MAX = max(1, int(os.getenv("WEB_SEARCH_AUTO_FETCH_MAX", "3")))
_WEB_SEARCH_CONTENT_MAX_CHARS = max(500, int(os.getenv("WEB_SEARCH_CONTENT_MAX_CHARS", "2000")))


# ════════════════════════════════════════════════════════════
# 웹 검색 API 모듈 (Naver / Brave)
# API 키가 설정되면 JSON API 우선 사용, 실패 시 MCP fallback
# 쿼리에 한국어가 포함되어 있는지 판별
# ════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════
# Naver 검색 API를 통한 검색 (블로그 + 웹)
# Returns: 검색 결과 리스트 또는 None (API 키 없음/실패)
# ════════════════════════════════════════════════════════════
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


# ════════════════════════════════════════════════════════════
# Brave Search API를 통한 검색
# Returns: 검색 결과 리스트 또는 None (API 키 없음/실패)
# ════════════════════════════════════════════════════════════
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


# ════════════════════════════════════════════════════════════
# SearXNG 자체 호스팅 메타 검색 엔진을 통한 검색
# 무료, API 키 불필요, 다중 검색엔진 (Google/Naver/Bing/DuckDuckGo) 통합
# Returns: 검색 결과 리스트 또는 None (SearXNG 미실행/실패)
# ════════════════════════════════════════════════════════════
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


# ════════════════════════════════════════════════════════════
# 두 검색 결과 병합 (URL 중복 제거, primary 우선 인터리브)
# ════════════════════════════════════════════════════════════
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


# ════════════════════════════════════════════════════════════
# API 검색 통합 라우터
# 한국어: SearXNG + NaverAPI 병렬 실행 → 결과 인터리브 병합
# 영어:   SearXNG → Brave → Naver 순차 폴백
# ════════════════════════════════════════════════════════════
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


# ════════════════════════════════════════════════════════════
# 웹 검색 결과 관련성 필터
# ════════════════════════════════════════════════════════════
_NOISE_KEYWORDS = ("경매", "이사", "이삿짐", "이사짐", "부동산", "매매", "분양", "임대", "중개", "공인")
_PROVINCE_NAMES = frozenset(("전북", "전남", "경북", "경남", "충북", "충남", "강원", "제주", "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종"))
# 지역명 판별: "XX시", "XX군" 등 3글자 이상이고 행정구역 접미사로 끝나는 단어
_LOCATION_RE = re.compile(r'^.{2,}(?:특별자치도|광역시|특별시|시|군|구|면|읍|리|동|도)$')


def _is_location(word: str) -> bool:
    """지역명 여부 판별 (3글자 이상 + 행정구역 접미사, 또는 광역시도 약칭)"""
    if word in _PROVINCE_NAMES:
        return True
    if len(word) < 3:
        return False
    return bool(_LOCATION_RE.match(word))


def _filter_relevant_results(query: str, results: list) -> list:
    if not query or not results:
        return results

    # 쿼리에서 2글자 이상 키워드 추출
    all_keywords = [w for w in query.split() if len(w) >= 2]
    if not all_keywords:
        return results

    # 지역명과 핵심 키워드 분리
    location_kws = []
    core_kws = []
    for kw in all_keywords:
        if _is_location(kw):
            location_kws.append(kw.lower())
        else:
            core_kws.append(kw.lower())

    # 핵심 키워드가 없으면 전체를 핵심으로 취급 (지역 검색 등)
    if not core_kws:
        core_kws = [kw.lower() for kw in all_keywords]

    filtered = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").lower()
        desc = (item.get("description") or item.get("snippet") or "").lower()
        text = f"{title} {desc}"

        # 노이즈 키워드가 제목에 포함되면 제거 (경매, 이사 등 무관 광고)
        if any(nk in title for nk in _NOISE_KEYWORDS):
            # 단, 핵심 키워드도 함께 포함되어 있으면 유지 (예: "낚시 부동산" 같은 복합 결과)
            core_matched = sum(1 for kw in core_kws if kw in text)
            if core_matched == 0:
                logger.debug(f"[웹검색] 노이즈 필터 제거: {item.get('title', '')[:50]}")
                continue

        # 핵심 키워드 중 최소 1개 이상이 제목+설명에 포함되어야 함
        core_matched = sum(1 for kw in core_kws if kw in text)
        if core_matched >= 1:
            filtered.append(item)
        else:
            logger.debug(f"[웹검색] 관련성 필터 제거: {item.get('title', '')[:50]}")

    # 필터 후 결과가 너무 적으면 원본에서 노이즈만 제거한 목록 반환
    if len(filtered) < 2 and len(results) >= 2:
        noise_removed = [
            r for r in results
            if not any(nk in (r.get("title") or "").lower() for nk in _NOISE_KEYWORDS)
        ]
        return noise_removed if noise_removed else results

    return filtered


# 관련 결과 부족 시 재검색용 쿼리 생성 (지역명·일반명사 제거, 핵심 키워드만)
_GENERIC_WORDS = frozenset(("주변", "근처", "부근", "인근", "추천", "장소", "곳", "어디", "알려", "농장"))


def _build_retry_query(query: str) -> Optional[str]:
    words = [w for w in query.split() if len(w) >= 2]
    core = [w for w in words if not _is_location(w) and w not in _GENERIC_WORDS]
    if not core or core == words:
        return None
    # 넓은 지역명 1개만 유지 (시/도 단위)
    broad_loc = next((w for w in words if w in _PROVINCE_NAMES), None)
    parts = ([broad_loc] if broad_loc else []) + core + ["추천"]
    retry = " ".join(parts)
    return retry if retry != query else None


# ════════════════════════════════════════════════════════════
# MCP를 통한 웹 검색 + 상위 URL 본문 자동 읽기
# Args: query: 검색 키워드
# Returns: dict: 검색 결과 (page_content 포함)
# ════════════════════════════════════════════════════════════
def search_web(
    query: str,
    n_results: Optional[int] = None,
    auto_fetch_max: Optional[int] = None,
) -> Dict[str, Any]:
    t_start = time.time()
    logger.info(f"[웹검색] 시작 query=\"{(query or '')[:100]}\"")

    result = None
    search_limit = _WEB_SEARCH_RESULT_LIMIT
    fetch_limit = _WEB_SEARCH_AUTO_FETCH_MAX

    try:
        if n_results is not None:
            search_limit = max(3, min(20, int(n_results)))
    except (TypeError, ValueError):
        pass

    try:
        if auto_fetch_max is not None:
            fetch_limit = max(1, min(5, int(auto_fetch_max)))
    except (TypeError, ValueError):
        pass

    # 1단계: API 검색 시도 (Naver/Brave - API 키가 있을 때만)
    try:
        _t_api = time.time()
        api_result = _search_via_api(query, count=search_limit)
        _api_ms = (time.time() - _t_api) * 1000
        if api_result and api_result.get("success") and api_result.get("results"):
            result = api_result
            provider = api_result.get("search_provider", "api")
            logger.info(f"[웹검색] API 검색 성공 (provider={provider})")
        logger.debug(f"[PERF:대화] 웹검색-API단계={_api_ms:.0f}ms (provider={api_result.get('search_provider', 'none') if api_result else 'fail'})")
    except Exception as e:
        logger.warning(f"[웹검색] API 검색 예외: {e}")

    # 2단계: API 실패 시 MCP 스크래핑 fallback
    if not result or not result.get("results"):
        try:
            _t_mcp = time.time()
            from agri_ai_core.src.ai.mcp_client import search_web as mcp_search
            mcp_result = mcp_search(query, max_results=search_limit)
            _mcp_ms = (time.time() - _t_mcp) * 1000
            if mcp_result.get("success") and mcp_result.get("results"):
                result = mcp_result
                result["search_provider"] = "mcp_scraping"
                logger.info(f"[웹검색] MCP 스크래핑 fallback 성공")
            elif not result:
                result = mcp_result
            logger.debug(f"[PERF:대화] 웹검색-MCP스크래핑={_mcp_ms:.0f}ms")
        except Exception as e:
            logger.warning(f"[웹검색] MCP 스크래핑 fallback 실패: {e}")
            if not result:
                result = {"success": False, "error": str(e), "results": []}

    # 검색 결과 관련성 필터: 쿼리 키워드와 무관한 결과 제거
    if isinstance(result, dict) and result.get("results"):
        result["results"] = _filter_relevant_results(query, result["results"])

    # 관련 결과 부족 시 핵심 키워드로 재검색 (지역명·일반명사 제거)
    result_count = len(result.get("results", [])) if isinstance(result, dict) else 0
    if result_count < 3:
        retry_query = _build_retry_query(query)
        if retry_query and retry_query != query:
            logger.info(f"[웹검색] 관련 결과 부족({result_count}건), 재검색: \"{retry_query}\"")
            retry_result = None
            try:
                retry_result = _search_via_api(retry_query, count=search_limit)
            except Exception:
                pass
            if not retry_result or not retry_result.get("results"):
                try:
                    retry_result = _search_via_searxng(retry_query, count=search_limit)
                    if retry_result:
                        retry_result = {"success": True, "results": retry_result, "search_provider": "searxng_retry"}
                except Exception:
                    pass
            if retry_result and retry_result.get("results"):
                retry_filtered = _filter_relevant_results(retry_query, retry_result["results"])
                # 기존 결과와 병합 (URL 중복 제거)
                existing_urls = {r.get("url") for r in (result.get("results", []) if isinstance(result, dict) else [])}
                for item in retry_filtered:
                    if item.get("url") not in existing_urls:
                        result.setdefault("results", []).append(item)
                        existing_urls.add(item.get("url"))
                logger.info(f"[웹검색] 재검색 병합 후 총 {len(result.get('results', []))}건")

    search_elapsed = time.time() - t_start
    result_count = len(result.get("results", [])) if isinstance(result, dict) else 0
    provider = result.get("search_provider", "unknown") if isinstance(result, dict) else "none"
    logger.info(f"[웹검색] 검색완료 ({search_elapsed:.1f}s) provider={provider} results={result_count}건")

    if result_count > 0:
        for idx, item in enumerate(result.get("results", [])[:5], start=1):
            if isinstance(item, dict):
                logger.info(f"[웹검색] 결과[{idx}] title={item.get('title','')[:50]} url={item.get('url','')[:80]}")

        # 상위 URL 본문 자동 읽기 (병렬)
        _auto_fetch_urls(result.get("results", []), max_fetch=fetch_limit)

        fetched = sum(1 for r in result.get("results", []) if r.get("page_content"))
        total_elapsed = time.time() - t_start
        logger.info(f"[웹검색] 본문읽기완료 ({total_elapsed:.1f}s) 본문확보={fetched}건/{result_count}건")

        # LLM 지시: 본문 데이터 기반으로 답변하라 (환각 방지 강화)
        result["instruction"] = (
            "page_content 필드에 각 URL의 본문이 포함되어 있습니다. "
            "반드시 이 본문 내용을 꼼꼼히 읽고, 여러 출처의 정보를 종합하여 "
            "구체적이고 자세한 답변을 작성하세요. "
            "핵심 요약 + 세부 항목 정리 + 출처 링크 형식으로 답변하세요. "
            "단답형이나 URL만 나열하는 것은 금지합니다. "
            "절대 규칙: 검색 결과(제목/URL/요약/본문)에 명시적으로 언급된 장소명·시설명·주소만 사용하세요. "
            "검색 결과에 없는 장소, 시설, 공원, 교육장, 주소, 전화번호를 만들어내는 것은 엄격히 금지합니다. "
            "검색 결과에 없는 정보를 추측하거나 일반 지식으로 보충하지 마세요. "
            "요청 개수보다 확인된 정보가 부족하면 확인된 것만 답변하고 '추가 검색이 필요합니다'라고 안내하세요."
        )

        # web_knowledge 캐싱: 검색 결과를 VectorDB에 저장 (백그라운드)
        try:
            threading.Thread(
                target=_cache_web_results_to_vectordb,
                args=(query, result.get("results", [])),
                daemon=True,
                name="web-knowledge-cache",
            ).start()
        except Exception as cache_err:
            logger.debug(f"[웹검색] web_knowledge 캐싱 실패: {cache_err}")

    return result


# ════════════════════════════════════════════════════════════
# 웹 검색 결과를 web_knowledge 컬렉션에 임베딩 저장 (URL 해시 기반 중복 방지)
# ════════════════════════════════════════════════════════════
def _cache_web_results_to_vectordb(query: str, results: list) -> None:
    import hashlib
    from agri_ai_core.src.ai.rag.embedder import embed_text
    from agri_ai_core.src.chroma.collections import web_knowledge_collection
    from agri_ai_core.src.chroma.operations import upsert_documents_with_embedding

    collection_name = web_knowledge_collection()
    if not collection_name:
        return

    ids_batch = []
    docs_batch = []
    embeddings_batch = []
    metadatas_batch = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for item in results[:5]:
        if not isinstance(item, dict):
            continue
        url = item.get("url", "")
        title = item.get("title", "")
        description = item.get("description", "")
        page_content = item.get("page_content", "")

        if not url or not (title or description):
            continue

        # URL 해시 기반 doc_id (중복 방지)
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        doc_id = f"web_{url_hash}"

        # 임베딩 대상 텍스트: title + description + page_content 앞부분
        embed_source = f"{title} {description}"
        if page_content:
            embed_source += f" {page_content[:500]}"

        embedding = embed_text(embed_source)
        if not embedding:
            continue

        ids_batch.append(doc_id)
        docs_batch.append(embed_source[:1500])
        embeddings_batch.append(embedding)
        metadatas_batch.append({
            "url": url[:500],
            "title": title[:200],
            "description": description[:500],
            "query": query[:200],
            "data_kind": "web_knowledge",
            "record_datetime": now_str,
        })

    if ids_batch:
        docs = []
        for i, doc_id in enumerate(ids_batch):
            docs.append({
                "doc_id": doc_id,
                "text": docs_batch[i],
                "metadata": metadatas_batch[i],
                "embedding": embeddings_batch[i],
            })
        upsert_documents_with_embedding(collection_name, docs)
        logger.info(f"[웹검색] web_knowledge 캐싱 완료: {len(ids_batch)}건")


# ════════════════════════════════════════════════════════════
# URL 본문 가져오기
# HTML 태그를 제거하고 텍스트만 추출한다.
# ════════════════════════════════════════════════════════════
def _strip_html(raw_text: str) -> str:
    import re
    text = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', raw_text, flags=re.IGNORECASE)
    text = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ════════════════════════════════════════════════════════════
# urllib로 직접 URL을 가져온다 (MCP fallback용).
# ════════════════════════════════════════════════════════════
def _direct_fetch_url(url: str, timeout: int = 15) -> Dict[str, Any]:
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
        return {"success": False, "text": f"HTTP {e.code}"}
    except Exception as e:
        return {"success": False, "text": str(e)}


# ════════════════════════════════════════════════════════════
# 웹 검색
# 검색 결과 상위 URL의 본문을 자동으로 읽어 결과에 추가한다.
# ════════════════════════════════════════════════════════════
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


# ════════════════════════════════════════════════════════════
# URL의 웹페이지 본문 텍스트를 가져온다.
# MCP fetch → 실패시 urllib 직접 요청으로 fallback.
# ════════════════════════════════════════════════════════════
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
            logger.info(f"[URL본문] MCP fetch 성공 raw_len={len(raw_text)}자")
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
