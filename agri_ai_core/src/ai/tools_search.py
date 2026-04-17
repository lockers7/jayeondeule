# ════════════════════════════════════════════════════════════════════════════════
# LLM Tool — 웹 검색 진입점 + 결과 관련성 필터 + VectorDB 캐싱
# 엔진 구현은 web_search_engines.py, URL 본문 수집은 web_url_fetcher.py에 분리됨.
# --->
# _is_location: 지역명 여부 판별 (행정구역 접미사 + 광역시도 약칭)
# _filter_relevant_results: 쿼리와의 유사도 기반 결과 필터링 (노이즈 제거)
# _build_retry_query: 검색 실패 시 재시도용 쿼리 재구성
# search_web: 메인 진입점 — 캐시 조회→검색→URL 본문→VectorDB 캐시 저장
# _cache_web_results_to_vectordb: 검색 결과를 web_knowledge 컬렉션에 저장
# fetch_url_content: 공개 API (web_url_fetcher에서 re-export, 하위호환)
# ════════════════════════════════════════════════════════════════════════════════
import os
import re
import time
import threading
from datetime import datetime
from typing import Dict, Any, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.web_search_engines import (
    _search_via_searxng,
    _search_via_api,
)
from agri_ai_core.src.ai.web_url_fetcher import (
    _auto_fetch_urls,
    fetch_url_content,   # 하위 호환 re-export — tools_executor가 tools_search에서 import
)

logger = setup_logger(__name__)

_WEB_SEARCH_RESULT_LIMIT = max(3, int(os.getenv("WEB_SEARCH_RESULT_LIMIT", "8")))
_WEB_SEARCH_AUTO_FETCH_MAX = max(1, int(os.getenv("WEB_SEARCH_AUTO_FETCH_MAX", "3")))


# ════════════════════════
# 웹 검색 결과 관련성 필터
# ════════════════════════
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


# ════════════════════════════════════════════
# MCP를 통한 웹 검색 + 상위 URL 본문 자동 읽기
# Args: query: 검색 키워드
# Returns: dict: 검색 결과 (page_content 포함)
# ════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════════════════════
# 웹 검색 결과를 web_knowledge 컬렉션에 임베딩 저장 (URL 해시 기반 중복 방지)
# ═══════════════════════════════════════════════════════════════════════════
def _cache_web_results_to_vectordb(query: str, results: list) -> None:
    import hashlib
    from agri_ai_core.src.ai.embedder import embed_text
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
