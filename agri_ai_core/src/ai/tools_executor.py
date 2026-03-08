# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM Tool 실행기
# LLM이 요청한 도구를 실제로 실행하는 모듈
# --->
# _is_korean_query: 웹 검색 API 모듈 (Naver / Brave)
# _search_via_naver_api: Naver 검색 API를 통한 검색 (블로그 + 웹)
# _search_via_brave_api: Brave Search API를 통한 검색
# _search_via_searxng: SearXNG 자체 호스팅 메타 검색 엔진을 통한 검색
# _search_via_api: API 검색 통합 라우터
# _json_default: json.dumps 기본 직렬화로 처리할 수 없는 타입 변환.
# search_farm_knowledge: 농장 지식 검색
# get_farm_realtime_data: 농장 실시간 데이터 가져오기
# control_relay: 릴레이(장치) 제어
# _auto_fetch_urls: 웹 검색
# search_web: MCP를 통한 웹 검색 + 상위 URL 본문 자동 읽기
# _cache_web_results_to_vectordb: 웹 검색 결과를 web_knowledge 컬렉션에 임베딩 저장 (URL 해시 기반 중복 방지)
# _strip_html: URL 본문 가져오기
# _direct_fetch_url: urllib로 직접 URL을 가져온다 (MCP fallback용).
# fetch_url_content: URL의 웹페이지 본문 텍스트를 가져온다.
# execute_tool: 도구 실행기 (메인)
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import json
import os
import re
import time
import threading
import urllib.request
import urllib.parse
import urllib.error
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, Any, List, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)


def _normalize_id(value):
    """LLM이 전달한 ID에서 숫자만 추출. 숫자가 없으면 None 반환.
    예: '자연들에 농장' → None, '1' → '1', '상황버섯1호재배사' → '1'
    """
    if value is None:
        return None
    s = str(value).strip()
    # 이미 순수 숫자면 그대로
    try:
        int(s)
        return s
    except (ValueError, TypeError):
        pass
    # 한글 등이 섞여 있으면 숫자만 추출
    digits = re.findall(r'\d+', s)
    return digits[0] if digits else None


def _resolve_relay_ids(house_id, farm_id):
    """릴레이 제어용 house_id/farm_id를 정규화하고 검증한다. (house_id, farm_id) 또는 에러 dict 반환."""
    from agri_ai_core.src.postgresql.connection import db_session
    from agri_ai_core.src.postgresql.queries import GET_ONE_FARM
    target_house_id = _normalize_id(house_id)
    if not target_house_id:
        return {"success": False, "error": "house_id를 확인할 수 없습니다."}
    target_farm_id = _normalize_id(farm_id)
    if not target_farm_id:
        with db_session() as database:
            farm = database.fetch_one(GET_ONE_FARM)
            if farm and farm.get("farm_id") is not None:
                target_farm_id = str(farm.get("farm_id"))
    if not target_farm_id:
        return {"success": False, "error": "farm_id를 확인할 수 없습니다."}
    return target_house_id, target_farm_id


_WEB_SEARCH_RESULT_LIMIT = max(3, int(os.getenv("WEB_SEARCH_RESULT_LIMIT", "8")))
_WEB_SEARCH_AUTO_FETCH_MAX = max(1, int(os.getenv("WEB_SEARCH_AUTO_FETCH_MAX", "3")))
_WEB_SEARCH_CONTENT_MAX_CHARS = max(500, int(os.getenv("WEB_SEARCH_CONTENT_MAX_CHARS", "2000")))


# ============================================================
# 웹 검색 API 모듈 (Naver / Brave)
# API 키가 설정되면 JSON API 우선 사용, 실패 시 MCP fallback
# 쿼리에 한국어가 포함되어 있는지 판별
# ============================================================

def _is_korean_query(query: str) -> bool:
    korean_chars = sum(1 for c in query if '\uac00' <= c <= '\ud7a3' or '\u3131' <= c <= '\u3163')
    return korean_chars > 0


# ============================================================
# Naver 검색 API를 통한 검색 (블로그 + 웹)
# Returns: 검색 결과 리스트 또는 None (API 키 없음/실패)
# ============================================================
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


# ============================================================
# Brave Search API를 통한 검색
# Returns: 검색 결과 리스트 또는 None (API 키 없음/실패)
# ============================================================
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


# ============================================================
# SearXNG 자체 호스팅 메타 검색 엔진을 통한 검색
# 무료, API 키 불필요, 다중 검색엔진 (Google/Naver/Bing/DuckDuckGo) 통합
# Returns: 검색 결과 리스트 또는 None (SearXNG 미실행/실패)
# ============================================================
def _search_via_searxng(query: str, count: Optional[int] = None) -> Optional[List[Dict[str, Any]]]:
    searxng_url = os.getenv("SEARXNG_URL", "").strip()
    if not searxng_url:
        return None
    if count is None:
        count = _WEB_SEARCH_RESULT_LIMIT

    # 한국어 쿼리 감지 → 언어 설정
    lang = "ko-KR" if _is_korean_query(query) else "en-US"

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

        engines_used = list(set(item.get("engine", "") for item in data.get("results", []) if item.get("engine")))
        logger.info(f"[SearXNG] {len(results)}건 검색 완료 engines={engines_used[:5]} query=\"{query[:50]}\"")
        return results if results else None

    except urllib.error.URLError as e:
        logger.warning(f"[SearXNG] 연결 실패 (SearXNG 미실행?): {e}")
        return None
    except Exception as e:
        logger.warning(f"[SearXNG] 오류: {e}")
        return None


# ============================================================
# API 검색 통합 라우터
# 우선순위: SearXNG(무료) → Naver/Brave(API키) → None(MCP fallback)
# 한국어 → Naver 우선, 영어 → Brave 우선
# ============================================================
def _search_via_api(query: str, count: Optional[int] = None) -> Optional[Dict[str, Any]]:
    t_start = time.time()
    is_korean = _is_korean_query(query)

    target_count = max(3, int(count or _WEB_SEARCH_RESULT_LIMIT))
    naver_display = min(10, target_count)
    brave_count = min(20, target_count)

    # SearXNG: 무료, API 키 불필요 → 항상 최우선 시도
    search_order = [("searxng", lambda: _search_via_searxng(query, count=target_count))]

    if is_korean:
        search_order.extend([
            ("naver", lambda: _search_via_naver_api(query, display=naver_display)),
            ("brave", lambda: _search_via_brave_api(query, count=brave_count)),
        ])
    else:
        search_order.extend([
            ("brave", lambda: _search_via_brave_api(query, count=brave_count)),
            ("naver", lambda: _search_via_naver_api(query, display=naver_display)),
        ])

    from agri_ai_core.src.ai.stats_collector import get_stats_collector

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


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# json.dumps 기본 직렬화로 처리할 수 없는 타입 변환.
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return str(value)
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 농장 지식 검색
# ChromaDB에서 농장 지식 검색
# Args: query: 검색 질의
#       n_results: 결과 개수
# Returns: dict: 검색 결과
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def search_farm_knowledge(
    query: str,
    n_results: int = 3,
    file_name: str = None,
    farm_id: str = None,
    house_id: str = None,
) -> Dict[str, Any]:
    t_start = time.time()
    logger.info(
        f"[VectorDB검색] 시작 query=\"{(query or '')[:80]}\" "
        f"n_results={n_results} file_name={file_name} farm_id={farm_id} house_id={house_id}"
    )
    try:
        from agri_ai_core.src.ai.rag.embedder import embed_text
        from agri_ai_core.src.chroma.collections import document_collection, farm_knowledge_collection, web_knowledge_collection
        from agri_ai_core.src.chroma.operations import query_documents

        def _parse_positive_int(value, default):
            try:
                parsed = int(value)
                return parsed if parsed > 0 else default
            except Exception:
                return default

        def _parse_positive_float(value, default):
            try:
                parsed = float(value)
                return parsed if parsed > 0 else default
            except Exception:
                return default

        max_results = _parse_positive_int(n_results, 3)
        def _parse_optional_int(value):
            if value in (None, ""):
                return None
            try:
                return int(str(value))
            except Exception:
                return None

        # ============================================================
        # 다중 키 where 딕셔너리를 ChromaDB $and 형식으로 변환
        # ============================================================
        def _to_chroma_where(where_dict):
            if not where_dict:
                return None
            if len(where_dict) == 1:
                k, v = next(iter(where_dict.items()))
                return {k: {"$eq": v}} if not isinstance(v, dict) else where_dict
            conditions = []
            for k, v in where_dict.items():
                if isinstance(v, dict):
                    conditions.append({k: v})
                else:
                    conditions.append({k: {"$eq": v}})
            return {"$and": conditions}

        source_where_candidates = []
        source_where_str = {}
        if farm_id is not None:
            source_where_str["farm_id"] = str(farm_id)
        if house_id is not None:
            source_where_str["house_id"] = str(house_id)
        if source_where_str:
            source_where_candidates.append(_to_chroma_where(source_where_str))

        source_where_int = {}
        farm_id_int = _parse_optional_int(farm_id)
        house_id_int = _parse_optional_int(house_id)
        if farm_id_int is not None:
            source_where_int["farm_id"] = farm_id_int
        if house_id_int is not None:
            source_where_int["house_id"] = house_id_int
        chroma_int = _to_chroma_where(source_where_int)
        if chroma_int and chroma_int not in source_where_candidates:
            source_where_candidates.append(chroma_int)

        if not source_where_candidates:
            source_where_candidates = [None]

        t_embed = time.time()
        query_embedding = embed_text(query)
        embed_elapsed = time.time() - t_embed
        if not query_embedding:
            logger.warning(f"[VectorDB검색] 임베딩 생성 실패 ({embed_elapsed:.1f}s)")
            return {
                "success": False,
                "error": "검색 임베딩 생성에 실패했습니다.",
                "results": [],
            }
        logger.info(f"[VectorDB검색] 임베딩 생성 완료 ({embed_elapsed:.1f}s) dim={len(query_embedding)}")
        logger.debug(f"[PERF:대화] VectorDB검색-임베딩={embed_elapsed * 1000:.0f}ms")

        collection_plans = []
        doc_collection_name = document_collection()
        if doc_collection_name:
            # file_name이 지정된 경우 해당 파일 청크만 검색하는 where 필터 적용
            doc_where = None
            if file_name:
                # UUID 접두사(8자리hex_) 제거하여 원본 파일명으로 검색
                _fn = file_name
                _fn_match = re.match(r'^[0-9a-f]{8}_(.+)$', file_name)
                if _fn_match:
                    _fn = _fn_match.group(1)
                doc_where = {"file_name": {"$eq": _fn}}
                logger.info(f"[VectorDB검색] file_name 필터 적용: {_fn} (입력: {file_name})")
            collection_plans.append({
                "label": "document",
                "name": doc_collection_name,
                "where": doc_where,
                "max_distance": _parse_positive_float(os.getenv("DOC_VECTOR_MAX_DISTANCE", "22.0"), 22.0),
            })

        farm_knowledge_name = farm_knowledge_collection()
        if farm_knowledge_name:
            for where in source_where_candidates:
                collection_plans.append({
                    "label": "farm_knowledge",
                    "name": farm_knowledge_name,
                    "where": where,
                    "max_distance": _parse_positive_float(os.getenv("SOURCE_VECTOR_MAX_DISTANCE", "24.0"), 24.0),
                })

        web_knowledge_name = web_knowledge_collection()
        if web_knowledge_name:
            collection_plans.append({
                "label": "web_knowledge",
                "name": web_knowledge_name,
                "where": None,
                "max_distance": _parse_positive_float(os.getenv("WEB_VECTOR_MAX_DISTANCE", "20.0"), 20.0),
            })

        if not collection_plans:
            logger.warning("[VectorDB검색] 사용 가능한 컬렉션이 없습니다.")
            return {
                "success": False,
                "error": "지식 데이터베이스 컬렉션을 찾을 수 없습니다.",
                "results": [],
            }

        formatted_results = []
        skipped_count = 0
        per_collection_count = max(6, max_results * 3)
        query_total_elapsed = 0.0

        for plan in collection_plans:
            t_query = time.time()
            results = query_documents(
                collection_name=plan["name"],
                query_embeddings=[query_embedding],
                n_results=per_collection_count,
                where=plan["where"],
            )
            query_elapsed = time.time() - t_query
            query_total_elapsed += query_elapsed

            if "error" in results:
                logger.warning(
                    f"[VectorDB검색] {plan['label']} 쿼리 실패 ({query_elapsed:.1f}s): {results['error']}"
                )
                continue

            documents = results.get("documents", []) or []
            metadatas = results.get("metadatas", []) or []
            distances = results.get("distances", []) or []

            for idx, (doc, meta) in enumerate(zip(documents, metadatas)):
                dist = distances[idx] if idx < len(distances) else None
                if dist is not None and dist > plan["max_distance"]:
                    skipped_count += 1
                    continue

                # TTL 페널티: farm_knowledge의 90일+ 오래된 데이터에 distance 페널티 부여
                if dist is not None and plan["label"] == "farm_knowledge" and isinstance(meta, dict):
                    record_dt = meta.get("record_datetime")
                    if record_dt and isinstance(record_dt, str):
                        try:
                            rec_date = datetime.strptime(record_dt[:10], "%Y-%m-%d")
                            age_days = (datetime.now() - rec_date).days
                            if age_days > 90:
                                # 90일 초과 시 10일마다 distance에 0.5 페널티 부여
                                penalty = ((age_days - 90) / 10) * 0.5
                                dist = dist + penalty
                        except (ValueError, TypeError):
                            pass

                formatted_results.append({
                    "content": str(doc or "")[:700],
                    "metadata": meta if isinstance(meta, dict) else {},
                    "distance": dist,
                    "collection": plan["label"],
                })

        # 거리 기준 정렬 + 중복 제거 (벡터 유사도 검색만 사용, 관련성 판단은 Reranker(LLM)에 위임)
        formatted_results.sort(
            key=lambda item: (
                item.get("distance") is None,
                item.get("distance") if item.get("distance") is not None else float("inf"),
            )
        )
        deduped_results = []
        seen_keys = set()
        for item in formatted_results:
            metadata = item.get("metadata") or {}
            key = (
                metadata.get("doc_id"),
                metadata.get("record_datetime"),
                item.get("content", "")[:120],
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped_results.append(item)

        # LLM 기반 Reranker 적용 (관련성 판단을 LLM에 위임, 무관한 결과 필터링)
        # file_name 필터 시 Reranker 바이패스 (파일명 쿼리는 내용과 관련성 낮아 Reranker가 오판)
        if file_name:
            # file_name 필터로 검색한 document_collection 결과를 우선 반환
            doc_results = [r for r in deduped_results if r.get("collection") == "document"]
            if doc_results:
                deduped_results = doc_results[:max_results]
                logger.info(f"[VectorDB검색] file_name 필터 → Reranker 바이패스, document 결과 {len(deduped_results)}건")
            else:
                deduped_results = deduped_results[:max_results]
                logger.info(f"[VectorDB검색] file_name 필터 → document 결과 없음, 전체 {len(deduped_results)}건 폴백")
        else:
            try:
                from agri_ai_core.src.ai.rag.reranker import rerank_results
                deduped_results = rerank_results(query, deduped_results, top_k=max_results)
            except Exception as e:
                logger.warning(f"[VectorDB검색] Reranker 예외: {e} → 거리 기반 상위 {max_results}건 폴백")
                deduped_results = deduped_results[:max_results]

        total_elapsed = time.time() - t_start
        skip_info = f" (거리필터 제외={skipped_count}건)" if skipped_count else ""
        logger.info(
            f"[VectorDB검색] 완료 {len(deduped_results)}건{skip_info} "
            f"(쿼리합={query_total_elapsed:.1f}s, 총={total_elapsed:.1f}s)"
        )
        for idx, fr in enumerate(deduped_results, start=1):
            dist_str = f"{fr['distance']:.4f}" if fr['distance'] is not None else "-"
            logger.info(
                f"[VectorDB검색] 결과[{idx}] collection={fr.get('collection')} "
                f"distance={dist_str} content_len={len(fr.get('content',''))}자"
            )

        # 검색 품질 메트릭 로깅
        try:
            import hashlib as _hl
            query_hash = _hl.md5(query.encode()).hexdigest()[:8]
            distances = [r.get("distance") for r in deduped_results if r.get("distance") is not None]
            avg_dist = sum(distances) / len(distances) if distances else 0
            collections_used = list(set(r.get("collection", "") for r in deduped_results))
            logger.info(
                f"[검색품질] hash={query_hash} "
                f"요청={max_results}건 반환={len(deduped_results)}건 "
                f"평균distance={avg_dist:.4f} "
                f"임베딩={embed_elapsed:.2f}s 쿼리합={query_total_elapsed:.1f}s 총={total_elapsed:.1f}s "
                f"컬렉션={collections_used}"
            )
        except Exception:
            pass

        return {
            "success": True,
            "query": query,
            "count": len(deduped_results),
            "data_retrieved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "results": deduped_results,
        }

    except Exception as e:
        elapsed = time.time() - t_start
        logger.error(f"[VectorDB검색] 오류 ({elapsed:.1f}s): {e}")
        return {
            "success": False,
            "error": str(e),
            "results": []
        }


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 농장 실시간 데이터 가져오기
# PostgreSQL에서 농장 실시간 데이터 조회
# Args: house_id: 재배사 ID
#       farm_id: 농장 ID (선택)
#       data_type: 데이터 유형 (sensor/relay/all)
# Returns: dict: 실시간 데이터
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_farm_realtime_data(house_id: str = None, farm_id: str = None, data_type: str = "all") -> Dict[str, Any]:
    t_start = time.time()
    logger.info(f"[PostgreSQL조회] 시작 farm_id={farm_id} house_id={house_id} data_type={data_type}")
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        from agri_ai_core.src.postgresql.queries import GET_ONE_FARM, GET_ONE_HOUSE
        from agri_ai_core.src.postgresql.reader import (
            read_current_sensor_info,
            read_latest_relay_info,
        )

        target_farm_id = _normalize_id(farm_id)
        if not target_farm_id:
            t_farm = time.time()
            with db_session() as database:
                farm = database.fetch_one(GET_ONE_FARM)
                if farm and farm.get("farm_id") is not None:
                    target_farm_id = str(farm.get("farm_id"))
            logger.info(f"[PostgreSQL조회] farm_id 자동조회={target_farm_id} ({time.time() - t_farm:.1f}s)")

        if not target_farm_id:
            return {
                "success": False,
                "error": "farm_id를 확인할 수 없습니다.",
                "house_id": house_id
            }

        target_house_id = _normalize_id(house_id)
        if not target_house_id:
            t_house = time.time()
            with db_session() as database:
                house = database.fetch_one(GET_ONE_HOUSE, vals=(target_farm_id,))
                if house and house.get("hous_id") is not None:
                    target_house_id = str(house.get("hous_id"))
            logger.info(
                f"[PostgreSQL조회] house_id 자동조회={target_house_id} ({time.time() - t_house:.1f}s)"
            )

        if not target_house_id:
            return {
                "success": False,
                "error": "house_id를 확인할 수 없습니다.",
                "farm_id": str(target_farm_id),
                "house_id": house_id,
            }

        now = datetime.now()
        result = {
            "success": True,
            "farm_id": str(target_farm_id),
            "house_id": str(target_house_id),
            "timestamp": now.isoformat(),
            "data_retrieved_at": now.strftime("%Y-%m-%d %H:%M"),
            "auto_selected": bool(not house_id),
        }

        if data_type in ["sensor", "all"]:
            t_sensor = time.time()
            sensor = read_current_sensor_info(target_farm_id, target_house_id)
            sensor_elapsed = time.time() - t_sensor
            result["sensor"] = sensor or {}
            sensor_keys = list((sensor or {}).keys())[:8]
            logger.info(f"[PostgreSQL조회] 센서데이터 ({sensor_elapsed:.1f}s) keys={sensor_keys}")

        if data_type in ["relay", "all"]:
            t_relay = time.time()
            relay = read_latest_relay_info(target_farm_id, target_house_id)
            relay_elapsed = time.time() - t_relay
            result["relay"] = relay or {}
            relay_keys = list((relay or {}).keys())[:8]
            logger.info(f"[PostgreSQL조회] 릴레이데이터 ({relay_elapsed:.1f}s) keys={relay_keys}")

            # 릴레이 시멘틱 매핑 정보 추가 (LLM이 각 릴레이의 실제 기능을 알 수 있도록)
            if relay:
                from agri_ai_core.src.control.control_common import reverse_pin_map, SEMANTIC_LABELS
                rev_map = reverse_pin_map(target_house_id)
                relay_mapping = {}
                for pin_key, value in relay.items():
                    if pin_key.startswith("relay_") and pin_key.endswith("_flag"):
                        semantic_name = rev_map.get(pin_key)
                        if semantic_name:
                            label = SEMANTIC_LABELS.get(semantic_name, semantic_name)
                            relay_mapping[pin_key] = {
                                "value": bool(value),
                                "device": semantic_name,
                                "name": label,
                            }
                result["relay_mapping"] = relay_mapping

        if (
            (data_type in ["sensor", "all"] and not result.get("sensor"))
            and (data_type in ["relay", "all"] and not result.get("relay"))
        ):
            result["note"] = "조회된 실시간 데이터가 없습니다."
            logger.warning("[PostgreSQL조회] 조회된 실시간 데이터 없음")

        total_elapsed = time.time() - t_start
        logger.info(
            f"[PostgreSQL조회] 완료 ({total_elapsed:.1f}s) "
            f"farm={target_farm_id} house={target_house_id}"
        )
        return result

    except Exception as e:
        elapsed = time.time() - t_start
        logger.error(f"[PostgreSQL조회] 오류 ({elapsed:.1f}s): {e}")
        return {
            "success": False,
            "error": str(e),
            "house_id": house_id
        }


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 릴레이(장치) 제어
# LLM이 호출하여 특정 재배사의 장치를 켜거나 끈다.
# relay_manager.set_relay_value를 통해 실제 DB에 릴레이 값을 설정한다.
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _get_ai_judgment_safe(farm_id, house_id):
    """AI 환경 판단을 안전하게 호출 (실패해도 None 반환)"""
    try:
        from agri_ai_core.src.control.manual_control import get_ai_environment_judgment
        return get_ai_environment_judgment(farm_id, house_id)
    except Exception as e:
        logger.warning(f"[AI판단] 조회 실패: {e}")
        return None


def _build_ai_conflict(ai_judgment, user_relay_settings):
    """사용자 수동 제어와 AI 권장 사이의 차이점을 비교하여 반환"""
    if not ai_judgment or not user_relay_settings:
        return None
    ai_devices = ai_judgment.get("devices") or {}
    if not ai_devices:
        return None

    from agri_ai_core.src.control.control_common import SEMANTIC_LABELS
    conflicts = []
    for device_name, user_value in user_relay_settings.items():
        if device_name in ai_devices:
            ai_value = ai_devices[device_name]
            if bool(user_value) != bool(ai_value):
                label = SEMANTIC_LABELS.get(device_name, device_name)
                user_str = "ON" if user_value else "OFF"
                ai_str = "ON" if ai_value else "OFF"
                conflicts.append(f"{label}: 수동={user_str}, AI권장={ai_str}")

    if not conflicts:
        return None
    return conflicts


def control_relay(house_id: str, device_name: str = None, action: str = None,
                   farm_id: str = None, mode: str = None) -> Dict[str, Any]:
    # mode가 지정된 경우 일괄 제어로 위임
    if mode in ("reverse_all", "all_on", "all_off"):
        return control_relays_batch(house_id=house_id, farm_id=farm_id, mode=mode)

    t_start = time.time()
    logger.info(f"[릴레이제어] 시작 farm_id={farm_id} house_id={house_id} device={device_name} action={action}")
    try:
        from agri_ai_core.src.control.relay_manager import set_relay_value
        from agri_ai_core.src.control.control_common import SEMANTIC_LABELS, set_llm_relay_lock, resolve_device_alias

        ids = _resolve_relay_ids(house_id, farm_id)
        if isinstance(ids, dict):
            return ids
        target_house_id, target_farm_id = ids

        # action 검증
        if action not in ("on", "off"):
            return {"success": False, "error": f"잘못된 action입니다: {action} (on 또는 off만 가능)"}

        # device_name 별칭 해소 및 검증
        device_name = resolve_device_alias(device_name)
        valid_devices = set(SEMANTIC_LABELS.keys())
        if device_name not in valid_devices:
            return {
                "success": False,
                "error": f"잘못된 device_name입니다: {device_name}",
                "valid_devices": list(valid_devices),
            }

        # ── AI 환경 판단 (제어 전 센서 기반) ──
        ai_judgment = _get_ai_judgment_safe(target_farm_id, target_house_id)

        # 릴레이 값 설정
        relay_value = (action == "on")
        relay_settings = {device_name: relay_value}
        result = set_relay_value(target_farm_id, target_house_id, relay_settings)

        elapsed = time.time() - t_start
        device_label = SEMANTIC_LABELS.get(device_name, device_name)
        action_label = "켜기(ON)" if relay_value else "끄기(OFF)"

        # ── AI 판단과 수동 제어 차이점 비교 ──
        ai_conflict = _build_ai_conflict(ai_judgment, relay_settings)

        if result.get("success"):
            # LLM 제어 잠금 설정 (자동제어 스케줄러 충돌 방지)
            set_llm_relay_lock(target_farm_id, target_house_id)
            logger.info(f"[릴레이제어] 완료 ({elapsed:.1f}s) {device_label} → {action_label} (LLM 잠금 설정)")
            return {
                "success": True,
                "message": f"{target_house_id}호 재배사의 {device_label}을(를) {action_label} 처리했습니다.",
                "farm_id": target_farm_id,
                "house_id": target_house_id,
                "device_name": device_name,
                "device_label": device_label,
                "action": action,
                "applied_value": relay_value,
                "ai_judgment": ai_judgment,
                "ai_conflict": ai_conflict,
            }
        else:
            logger.warning(f"[릴레이제어] 실패 ({elapsed:.1f}s): {result.get('message')}")
            return {
                "success": False,
                "error": result.get("message", "릴레이 값 설정에 실패했습니다."),
                "farm_id": target_farm_id,
                "house_id": target_house_id,
                "device_name": device_name,
            }

    except Exception as e:
        elapsed = time.time() - t_start
        logger.error(f"[릴레이제어] 오류 ({elapsed:.1f}s): {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"success": False, "error": str(e)}


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 릴레이 다중 일괄 제어
# 여러 장치를 한 번에 제어한다 (LLM의 반복 tool call 횟수 절감).
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def control_relays_batch(house_id: str, devices: List[Dict[str, str]] = None,
                         farm_id: str = None, mode: str = None) -> Dict[str, Any]:
    t_start = time.time()
    logger.info(f"[릴레이일괄제어] 시작 farm_id={farm_id} house_id={house_id} mode={mode} devices={len(devices or [])}건")
    try:
        from agri_ai_core.src.control.relay_manager import set_relay_value
        from agri_ai_core.src.control.control_common import (
            SEMANTIC_LABELS, set_llm_relay_lock, get_pin_map, reverse_pin_map,
        )
        from agri_ai_core.src.postgresql.reader import read_latest_relay_info

        ids = _resolve_relay_ids(house_id, farm_id)
        if isinstance(ids, dict):
            return ids
        target_house_id, target_farm_id = ids

        valid_devices = set(SEMANTIC_LABELS.keys())
        relay_settings = {}
        results_detail = []

        # mode 기반 자동 제어 (reverse_all / all_on / all_off)
        if mode in ("reverse_all", "all_on", "all_off"):
            current = read_latest_relay_info(target_farm_id, target_house_id)
            if not current:
                return {"success": False, "error": "현재 릴레이 상태를 조회할 수 없습니다."}

            rev_map = reverse_pin_map(target_house_id)
            for pin_key, semantic_name in rev_map.items():
                if semantic_name not in valid_devices:
                    continue
                current_value = bool(current.get(pin_key, False))
                label = SEMANTIC_LABELS.get(semantic_name, semantic_name)

                if mode == "reverse_all":
                    new_value = not current_value
                elif mode == "all_on":
                    new_value = True
                else:  # all_off
                    new_value = False

                relay_settings[semantic_name] = new_value
                prev_status = "ON(작동중)" if current_value else "OFF(미작동)"
                new_status = "ON(작동중)" if new_value else "OFF(미작동)"
                action_label = "켜기(ON)" if new_value else "끄기(OFF)"
                results_detail.append({
                    "device": semantic_name,
                    "label": label,
                    "pin": pin_key,
                    "action": action_label,
                    "prev_status": prev_status,
                    "new_status": new_status,
                    "success": True,
                })
            logger.info(f"[릴레이일괄제어] mode={mode} → {len(relay_settings)}개 장치 설정 생성")

        # devices 배열 기반 개별 제어
        elif devices and isinstance(devices, list):
            for item in devices:
                device_name = item.get("device_name", "")
                action = item.get("action", "")

                if device_name not in valid_devices:
                    results_detail.append({"device": device_name, "success": False, "error": "잘못된 device_name"})
                    continue
                if action not in ("on", "off"):
                    results_detail.append({"device": device_name, "success": False, "error": "잘못된 action"})
                    continue

                relay_settings[device_name] = (action == "on")
                label = SEMANTIC_LABELS.get(device_name, device_name)
                action_label = "켜기(ON)" if action == "on" else "끄기(OFF)"
                results_detail.append({"device": device_name, "label": label, "action": action_label, "success": True})
        else:
            return {"success": False, "error": "mode 또는 devices 파라미터가 필요합니다."}

        if not relay_settings:
            return {"success": False, "error": "유효한 장치 설정이 없습니다.", "details": results_detail}

        # ── AI 환경 판단 (제어 전 센서 기반) ──
        ai_judgment = _get_ai_judgment_safe(target_farm_id, target_house_id)

        result = set_relay_value(target_farm_id, target_house_id, relay_settings)

        # ── AI 판단과 수동 제어 차이점 비교 ──
        ai_conflict = _build_ai_conflict(ai_judgment, relay_settings)

        elapsed = time.time() - t_start
        if result.get("success"):
            set_llm_relay_lock(target_farm_id, target_house_id)
            controlled_labels = [d["label"] for d in results_detail if d.get("success")]
            logger.info(f"[릴레이일괄제어] 완료 ({elapsed:.1f}s) {len(controlled_labels)}건 (LLM 잠금 설정)")
            return {
                "success": True,
                "message": f"{target_house_id}호 재배사의 {len(controlled_labels)}개 장치를 일괄 제어했습니다.",
                "farm_id": target_farm_id,
                "house_id": target_house_id,
                "controlled_count": len(controlled_labels),
                "details": results_detail,
                "ai_judgment": ai_judgment,
                "ai_conflict": ai_conflict,
            }
        else:
            logger.warning(f"[릴레이일괄제어] 실패 ({elapsed:.1f}s): {result.get('message')}")
            return {
                "success": False,
                "error": result.get("message", "릴레이 일괄 설정에 실패했습니다."),
                "details": results_detail,
            }

    except Exception as e:
        elapsed = time.time() - t_start
        logger.error(f"[릴레이일괄제어] 오류 ({elapsed:.1f}s): {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"success": False, "error": str(e)}


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 웹 검색
# 검색 결과 상위 URL의 본문을 자동으로 읽어 결과에 추가한다.
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 웹 검색 결과 관련성 필터
# 쿼리 키워드와 무관한 검색 결과를 제거합니다.
# 검색 엔진이 복합어(예: "상황버섯")를 분리("상황"+"버섯")하여 무관한 결과를 반환하는 문제를 방지합니다.
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _filter_relevant_results(query: str, results: list) -> list:
    if not query or not results:
        return results

    # 쿼리에서 2글자 이상 키워드 추출
    keywords = [w for w in query.split() if len(w) >= 2]
    if not keywords:
        return results

    filtered = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").lower()
        desc = (item.get("description") or item.get("snippet") or "").lower()
        text = f"{title} {desc}"

        # 키워드 중 최소 1개 이상이 제목+설명에 포함되어야 함
        matched = sum(1 for kw in keywords if kw.lower() in text)
        if matched >= 1:
            filtered.append(item)
        else:
            logger.debug(f"[웹검색] 관련성 필터 제거: {item.get('title', '')[:50]}")

    # 필터 후 결과가 너무 적으면 원본 반환 (안전장치)
    if len(filtered) < 2 and len(results) >= 2:
        return results

    return filtered


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# MCP를 통한 웹 검색 + 상위 URL 본문 자동 읽기
# Args: query: 검색 키워드
# Returns: dict: 검색 결과 (page_content 포함)
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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

        # LLM 지시: 본문 데이터 기반으로 답변하라
        result["instruction"] = (
            "page_content 필드에 각 URL의 본문이 포함되어 있습니다. "
            "반드시 이 본문 내용을 꼼꼼히 읽고, 여러 출처의 정보를 종합하여 "
            "구체적이고 자세한 답변을 작성하세요. "
            "핵심 요약 + 세부 항목 정리 + 출처 링크 형식으로 답변하세요. "
            "단답형이나 URL만 나열하는 것은 금지합니다."
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


# ============================================================
# 웹 검색 결과를 web_knowledge 컬렉션에 임베딩 저장 (URL 해시 기반 중복 방지)
# ============================================================
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


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# URL 본문 가져오기
# HTML 태그를 제거하고 텍스트만 추출한다.
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _strip_html(raw_text: str) -> str:
    import re
    text = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', raw_text, flags=re.IGNORECASE)
    text = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# urllib로 직접 URL을 가져온다 (MCP fallback용).
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# URL의 웹페이지 본문 텍스트를 가져온다.
# MCP fetch → 실패시 urllib 직접 요청으로 fallback.
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 도구 실행기 (메인)
# LLM이 요청한 도구를 실행하고 결과를 JSON 문자열로 반환
# Args: tool_name: 도구 이름
#       tool_args: 도구 인자
# Returns: str: 실행 결과 (JSON 문자열)
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def execute_tool(tool_name: str, tool_args: Dict[str, Any]) -> str:
    t_start = time.time()
    logger.info(f"[도구실행] 시작 tool={tool_name} args={tool_args}")

    try:
        if tool_name == "search_farm_knowledge":
            result = search_farm_knowledge(
                query=tool_args.get("query"),
                n_results=tool_args.get("n_results", 3),
                file_name=tool_args.get("file_name"),
                farm_id=tool_args.get("farm_id"),
                house_id=tool_args.get("house_id"),
            )

        elif tool_name == "get_farm_realtime_data":
            result = get_farm_realtime_data(
                house_id=tool_args.get("house_id"),
                farm_id=tool_args.get("farm_id"),
                data_type=tool_args.get("data_type", "all")
            )

        elif tool_name == "control_relay":
            result = control_relay(
                house_id=tool_args.get("house_id"),
                device_name=tool_args.get("device_name"),
                action=tool_args.get("action"),
                farm_id=tool_args.get("farm_id"),
                mode=tool_args.get("mode"),
            )

        elif tool_name == "search_web":
            result = search_web(
                query=tool_args.get("query"),
                n_results=tool_args.get("n_results"),
                auto_fetch_max=tool_args.get("auto_fetch_max"),
            )

        elif tool_name == "fetch_url_content":
            result = fetch_url_content(
                url=tool_args.get("url", "")
            )

        else:
            result = {
                "success": False,
                "error": f"알 수 없는 도구: {tool_name}"
            }

        elapsed = time.time() - t_start
        success = result.get("success", True) if isinstance(result, dict) else True
        json_result = json.dumps(result, ensure_ascii=False, indent=2, default=_json_default)
        logger.info(f"[도구실행] 완료 tool={tool_name} ({elapsed:.1f}s) success={success} 결과길이={len(json_result)}자")
        return json_result

    except Exception as e:
        elapsed = time.time() - t_start
        logger.error(f"[도구실행] 오류 tool={tool_name} ({elapsed:.1f}s): {e}")
        import traceback
        logger.error(traceback.format_exc())

        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False, default=_json_default)
