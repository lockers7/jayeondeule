# ══════════════════════════════════════════════════════════
# LLM Tool 실행기 — LLM이 요청한 도구(검색, DB, 릴레이 등)를 실행.
# ══════════════════════════════════════════════════════════
import json
import os
import re
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, Any, List, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.tools_search import search_web, fetch_url_content

logger = setup_logger(__name__)

# 시스템/가상 농장 ID (관리자 선택 시 전체 데이터 검색, 일반 사용자는 자기 농장 + 시스템 농장 데이터 검색)
_SYSTEM_FARM_ID = "0"

# farm_id → farm_name 매핑 캐시 (프로세스 내 1회 조회 후 재사용)
_farm_name_cache: Dict[str, str] = {}
_farm_name_cache_loaded = False


def _get_farm_name(farm_id: str) -> str:
    """farm_id에 해당하는 farm_name을 반환. DB 조회 실패 시 farm_id 그대로 반환."""
    global _farm_name_cache, _farm_name_cache_loaded
    if not _farm_name_cache_loaded:
        try:
            from agri_ai_core.src.postgresql.connection import db_session
            from agri_ai_core.src.postgresql.queries import GET_LIST_FARM
            with db_session() as database:
                rows = database.fetch_all(query=GET_LIST_FARM, vals=(), as_dict=True)
            _farm_name_cache = {str(r["farm_id"]): r["farm_name"] for r in (rows or [])}
            _farm_name_cache_loaded = True
        except Exception as e:
            logger.warning(f"[farm_name 캐시] DB 조회 실패: {e}")
    return _farm_name_cache.get(farm_id, farm_id)


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
        return {"success": False, "error": "house_id를 확인할 수 없습니다. '1', '2', '3' 중 하나를 사용하세요."}
    if target_house_id == "0":
        return {"success": False, "error": "house_id='0'(공통 재배사)은 장치 제어 대상이 아닙니다. '1', '2', '3' 중 하나를 사용하세요."}
    target_farm_id = _normalize_id(farm_id)
    if target_farm_id == "0":
        # 시스템 농장(0)으로 제어 요청 시 실제 농장으로 대체
        target_farm_id = None
    if not target_farm_id:
        with db_session() as database:
            farm = database.fetch_one(GET_ONE_FARM)
            if farm and farm.get("farm_id") is not None:
                target_farm_id = str(farm.get("farm_id"))
    if not target_farm_id:
        return {"success": False, "error": "farm_id를 확인할 수 없습니다."}
    return target_house_id, target_farm_id




# json.dumps 기본 직렬화로 처리할 수 없는 타입 변환.
# ══════════════════════════════════════════════════════════
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


# 학습 데이터 삭제
# ══════════════════════════════════════════════════════════
def delete_farm_knowledge(file_name: str, farm_id: str = None) -> Dict[str, Any]:
    t_start = time.time()
    logger.info(f"[학습삭제] 시작 file_name={file_name} farm_id={farm_id}")
    try:
        from agri_ai_core.src.chroma.collections import document_collection, farm_knowledge_collection
        from agri_ai_core.src.chroma.operations import get_documents, delete_document

        if not file_name:
            return {"success": False, "error": "file_name이 필요합니다."}

        # farm_id가 없으면(None) 전체 농장, 있으면(0 포함) 해당 농장만 삭제
        is_admin = not farm_id  # farm_id=None일 때만 전체 삭제 (farm_id="0"은 시스템 농장만)
        _is_delete_all = file_name.strip().lower() in ("all", "*", "전체", "모두")

        # 복수 파일명 지원: 파이프(|) 또는 줄바꿈(\n)으로 구분된 파일명 → 개별 루핑 삭제
        # 주의: 쉼표(,)는 파일명에 포함될 수 있으므로 구분자로 사용하지 않음
        _file_names = []
        if not _is_delete_all:
            for part in file_name.replace("\n", "|").split("|"):
                part = part.strip()
                if part:
                    _file_names.append(part)
            if not _file_names:
                return {"success": False, "error": "file_name이 필요합니다."}

        collections = [document_collection(), farm_knowledge_collection()]
        total_deleted = 0
        deleted_files = []  # 삭제 성공한 파일명 목록
        failed_files = []   # 삭제 실패한 파일명 목록

        def _collect_ids_for_file(coll, target_name):
            """특정 파일명에 대한 삭제 대상 ID 수집 (공백↔밑줄 자동 변환 검색)"""
            ids = set()
            # 원본 + 공백↔밑줄 변환명으로 양쪽 시도
            name_variants = [target_name]
            if " " in target_name:
                name_variants.append(target_name.replace(" ", "_"))
            elif "_" in target_name:
                name_variants.append(target_name.replace("_", " "))
            for name in name_variants:
                for field in ("file_name", "file_name_stored"):
                    if is_admin:
                        wl = [{field: {"$eq": name}}]
                    else:
                        wl = [{"$and": [{field: {"$eq": name}}, {"farm_id": {"$eq": str(farm_id)}}]}]
                        if str(farm_id).isdigit():
                            wl.append({"$and": [{field: {"$eq": name}}, {"farm_id": {"$eq": int(farm_id)}}]})
                    for w in wl:
                        res = get_documents(coll, where=w, include=["metadatas"], limit=10000)
                        for doc_id in (res.get("ids") or []):
                            ids.add(doc_id)
            return ids

        for coll in collections:
            if not coll:
                continue
            all_ids: set = set()

            if _is_delete_all:
                # 전체 삭제: 문서 학습 데이터만 삭제 (growth_rag 등 자동 생성 데이터는 보존)
                if is_admin:
                    where_list = [None]
                else:
                    where_list = [{"farm_id": {"$eq": str(farm_id)}}]
                    if str(farm_id).isdigit():
                        where_list.append({"farm_id": {"$eq": int(farm_id)}})
                for where in where_list:
                    res = get_documents(coll, where=where, include=["metadatas"], limit=10000)
                    for doc_id, meta in zip(res.get("ids") or [], res.get("metadatas") or []):
                        if isinstance(meta, dict) and meta.get("data_type") == "growth_rag":
                            continue
                        all_ids.add(doc_id)
            else:
                # 단일 또는 복수 파일명 루핑 삭제
                for fn in _file_names:
                    fn_ids = _collect_ids_for_file(coll, fn)
                    if fn_ids:
                        all_ids.update(fn_ids)
                        if fn not in deleted_files:
                            deleted_files.append(fn)
                    elif fn not in deleted_files and fn not in failed_files:
                        failed_files.append(fn)

            if not all_ids:
                continue

            del_result = delete_document(coll, ids=list(all_ids))
            if isinstance(del_result, dict) and del_result.get("error"):
                logger.warning(f"[학습삭제] {coll} 삭제 오류: {del_result['error']}")
            else:
                total_deleted += len(all_ids)
                logger.info(f"[학습삭제] {coll}: {len(all_ids)}개 청크 삭제 완료")

        # 복수 파일 삭제 시 실제 삭제 성공 파일에서 failed 제거
        failed_files = [f for f in failed_files if f not in deleted_files]

        elapsed = time.time() - t_start
        if _is_delete_all:
            _label = "전체 문서 학습데이터"
        elif len(_file_names) > 1:
            _label = f"{len(_file_names)}개 파일"
        else:
            _label = f"'{_file_names[0]}'"

        if total_deleted > 0:
            msg = f"{_label} {total_deleted}개 청크를 삭제했습니다."
            if deleted_files:
                msg += f" (삭제: {', '.join(deleted_files)})"
            if failed_files:
                msg += f" (미발견: {', '.join(failed_files)})"
            logger.info(f"[학습삭제] 완료 ({elapsed:.1f}s) {_label} 총 {total_deleted}개 청크 삭제")
            return {
                "success": True,
                "message": msg,
                "deleted_count": total_deleted,
                "deleted_files": deleted_files,
                "failed_files": failed_files,
                "file_name": file_name,
            }
        else:
            logger.info(f"[학습삭제] {_label} 해당 데이터 없음 또는 권한 없음")
            return {
                "success": False,
                "message": f"{_label}을(를) 찾을 수 없습니다.",
                "file_name": file_name,
            }
    except Exception as e:
        logger.error(f"[학습삭제] 오류: {e}")
        return {"success": False, "error": str(e)}


def search_farm_knowledge(
    query: str,
    n_results: int = 5,
    file_name: str = None,
    farm_id: str = None,
    house_id: str = None,
    _meta_hint: bool = False,
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

        max_results = _parse_positive_int(n_results, 5)
        # 파일명이 지정된 경우: 해당 파일의 청크를 최대한 많이 가져옴 (상세 답변 지원)
        if file_name:
            max_results = max(max_results, 30)
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

        if farm_id is not None and str(farm_id) == _SYSTEM_FARM_ID:
            # 시스템 농장 선택 (관리자): farm_id 필터 없이 모든 농장 데이터 검색
            source_where_candidates = [None]
            logger.info("[VectorDB검색] 시스템 농장 모드: 전체 농장 데이터 검색")
        else:
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

            # 일반 농장 사용자: 시스템 농장(farm_id=0) 학습 데이터도 함께 검색
            if farm_id is not None:
                sys_where_str = _to_chroma_where({"farm_id": _SYSTEM_FARM_ID})
                if sys_where_str not in source_where_candidates:
                    source_where_candidates.append(sys_where_str)
                sys_farm_int = _parse_optional_int(_SYSTEM_FARM_ID)
                if sys_farm_int is not None:
                    sys_where_int = _to_chroma_where({"farm_id": sys_farm_int})
                    if sys_where_int not in source_where_candidates:
                        source_where_candidates.append(sys_where_int)
                logger.info(f"[VectorDB검색] 일반 농장 모드: farm_id={farm_id} + 시스템 농장 데이터 검색")

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
            # [FIX] farm_id/house_id 필터가 있을 때 필터 없는 폴백도 추가
            # → 파일 학습 데이터 등 farm_id 메타가 없는 문서도 검색 가능하도록
            if source_where_candidates and source_where_candidates != [None]:
                collection_plans.append({
                    "label": "farm_knowledge",
                    "name": farm_knowledge_name,
                    "where": None,
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
        # [FIX] 메타 질문(파일/학습/목록/리스트/자료 등) 감지 시 Reranker 바이패스
        # → "학습한 자료 리스트" 같은 질문은 문서 내용과 직접 관련이 없어 Reranker가 모두 1점 처리하는 문제 방지
        _meta_query_keywords = ("파일", "학습", "목록", "리스트", "자료", "문서", "업로드", "RAG", "데이터")
        _is_meta_query = any(kw in (query or "") for kw in _meta_query_keywords) or bool(_meta_hint)
        if _meta_hint and not any(kw in (query or "") for kw in _meta_query_keywords):
            logger.info(f"[VectorDB검색] _meta_hint로 메타 쿼리 활성화 (원본 query에 키워드 없음)")
        if file_name or _is_meta_query:
            if _is_meta_query:
                logger.info(f"[VectorDB검색] 메타 질문 감지 → Reranker 바이패스 (query=\"{query[:40]}\")")
                # 메타 쿼리 시 web_knowledge 및 growth_rag 결과 제외 (file_name 유무 무관)
                # — 파일 목록 질문에 생육 RAG 센서 데이터나 웹 검색 결과가 혼입되어 LLM 오인 방지
                before_count = len(deduped_results)
                deduped_results = [
                    r for r in deduped_results
                    if r.get("collection") != "web_knowledge"
                    and (r.get("metadata") or {}).get("data_type") != "growth_rag"
                ]
                excluded = before_count - len(deduped_results)
                if excluded:
                    logger.info(f"[VectorDB검색] 메타 쿼리: web_knowledge/growth_rag {excluded}건 제외")
            # file_name 필터로 검색한 document_collection 결과를 우선 반환
            doc_results = [r for r in deduped_results if r.get("collection") == "document"]
            if doc_results:
                deduped_results = doc_results[:max_results]
                logger.info(f"[VectorDB검색] document 결과 우선 반환 {len(deduped_results)}건")
            else:
                deduped_results = deduped_results[:max_results]
                logger.info(f"[VectorDB검색] document 결과 없음, 전체 {len(deduped_results)}건 폴백")
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

        # 메타 질문(파일/학습/목록/리스트/자료 등) 시 ChromaDB 직접 조회로 완전한 파일 목록 추출
        # 농장관리자: 자기 농장 파일만, 시스템관리자: 전체 파일
        _file_list = None
        if _is_meta_query:
            try:
                from agri_ai_core.src.chroma.operations import get_documents
                from agri_ai_core.src.chroma.collections import document_collection, farm_knowledge_collection

                _is_admin_list = (not farm_id or str(farm_id) == _SYSTEM_FARM_ID)
                _seen_files: set = set()
                _file_entries = []

                for _coll_name, _coll_label in [
                    (document_collection(), "document"),
                    (farm_knowledge_collection(), "farm_knowledge"),
                ]:
                    if not _coll_name:
                        continue
                    # 비관리자: 자기 농장만 (str/int 양쪽 시도), 관리자: 전체
                    if _is_admin_list:
                        _where_list = [None]
                    else:
                        _where_list = [{"farm_id": {"$eq": str(farm_id)}}]
                        if str(farm_id).isdigit():
                            _where_list.append({"farm_id": {"$eq": int(farm_id)}})

                    for _where in _where_list:
                        _res = get_documents(_coll_name, where=_where, include=["metadatas"], limit=2000)
                        for _meta in (_res.get("metadatas") or []):
                            if not isinstance(_meta, dict):
                                continue
                            _fn = _meta.get("file_name") or _meta.get("file_name_stored") or ""
                            _raw_fid = str(_meta.get("farm_id", "")) if _meta.get("farm_id") is not None else ""
                            # 동일 파일이 여러 농장에 학습된 경우 각각 표시 (파일명+farm_id로 중복 판정)
                            _dedup_key = f"{_fn}|{_raw_fid}"
                            if _fn and _dedup_key not in _seen_files:
                                _seen_files.add(_dedup_key)
                                _farm_scope = "시스템 농장" if _raw_fid in ("0", "") else f"{_get_farm_name(_raw_fid)}({_raw_fid})"
                                _file_entries.append({
                                    "file_name": _fn,
                                    "collection": _coll_label,
                                    "document_type": _meta.get("document_type", ""),
                                    "learning_date": _meta.get("learning_date", ""),
                                    "farm_scope": _farm_scope,
                                })

                if _file_entries:
                    _file_list = _file_entries
                    logger.info(
                        f"[VectorDB검색] 파일 목록 {len(_file_entries)}건 추출 "
                        f"({'전체농장' if _is_admin_list else f'farm_id={farm_id}'})"
                    )
            except Exception as _e:
                logger.warning(f"[VectorDB검색] 파일 목록 직접조회 실패: {_e} → formatted_results 폴백")
                _is_admin_list = (not farm_id or str(farm_id) == _SYSTEM_FARM_ID)
                _seen_files = set()
                _file_entries = []
                for item in formatted_results:
                    _meta = item.get("metadata") or {}
                    _fn = _meta.get("file_name") or _meta.get("file_name_stored") or ""
                    if not _is_admin_list and str(_meta.get("farm_id", "")) != str(farm_id):
                        continue
                    _raw_fid = str(_meta.get("farm_id", "")) if _meta.get("farm_id") is not None else ""
                    _dedup_key = f"{_fn}|{_raw_fid}"
                    if _fn and _dedup_key not in _seen_files:
                        _seen_files.add(_dedup_key)
                        _farm_scope = "시스템 농장" if _raw_fid in ("0", "") else f"{_get_farm_name(_raw_fid)}({_raw_fid})"
                        _file_entries.append({
                            "file_name": _fn,
                            "collection": item.get("collection", ""),
                            "document_type": _meta.get("document_type", ""),
                            "farm_scope": _farm_scope,
                        })
                if _file_entries:
                    _file_list = _file_entries

        result_data = {
            "success": True,
            "query": query,
            "count": len(deduped_results),
            "data_retrieved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "results": deduped_results,
        }
        if _file_list:
            result_data["file_list"] = _file_list
            result_data["file_count"] = len(_file_list)
        return result_data

    except Exception as e:
        elapsed = time.time() - t_start
        logger.error(f"[VectorDB검색] 오류 ({elapsed:.1f}s): {e}")
        return {
            "success": False,
            "error": str(e),
            "results": []
        }


# 농장 실시간 데이터 가져오기 (센서+릴레이+임계값+AI판단)
# ══════════════════════════════════════════════════════════
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

        # 시스템 농장(farm_id=0)은 센서/릴레이 없음 → 첫 번째 실제 농장으로 자동 대체
        if target_farm_id == "0":
            try:
                from agri_ai_core.src.postgresql.queries import GET_LIST_FARM
                with db_session() as database:
                    farms = database.fetch_all(GET_LIST_FARM)
                    real_farm = next((f for f in (farms or []) if str(f.get("farm_id", "0")) != "0"), None)
                    if real_farm:
                        target_farm_id = str(real_farm["farm_id"])
                        logger.info(f"[PostgreSQL조회] farm_id=0 → 실제 농장 자동 대체: farm_id={target_farm_id}")
                    else:
                        return {
                            "success": False,
                            "error": "시스템 농장(farm_id=0)은 센서 데이터가 없고, 등록된 실제 농장도 없어요.",
                            "house_id": house_id, "farm_id": "0"
                        }
            except Exception as e:
                logger.warning(f"[PostgreSQL조회] 실제 농장 조회 실패: {e}")
                return {
                    "success": False,
                    "error": "시스템 농장(farm_id=0)은 센서 데이터가 없어요. 실제 농장을 선택해 주세요.",
                    "house_id": house_id, "farm_id": "0"
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

        # 환경 제어 임계값 + AI 판단 포함 (LLM이 센서값 적정 여부를 판단할 수 있도록)
        if data_type in ["sensor", "all"]:
            from agri_ai_core.src.control.control_common import (
                TEMP_LOW, TEMP_HIGH, TEMP_CRITICAL_LOW, TEMP_CRITICAL_HIGH,
                HUMIDITY_LOW, HUMIDITY_HIGH, HUMIDITY_CRITICAL_LOW, HUMIDITY_CRITICAL_HIGH,
                CO2_LOW, CO2_HIGH, CO2_CRITICAL_HIGH,
                WATER_TEMP_LOW, WATER_TEMP_HIGH, WATER_TEMP_CRITICAL_LOW, WATER_TEMP_CRITICAL_HIGH,
            )
            result["environment_thresholds"] = {
                "indoor_temperature": {"low": TEMP_LOW, "high": TEMP_HIGH, "critical_low": TEMP_CRITICAL_LOW, "critical_high": TEMP_CRITICAL_HIGH, "unit": "°C"},
                "indoor_humidity": {"low": HUMIDITY_LOW, "high": HUMIDITY_HIGH, "critical_low": HUMIDITY_CRITICAL_LOW, "critical_high": HUMIDITY_CRITICAL_HIGH, "unit": "%"},
                "co2": {"low": CO2_LOW, "high": CO2_HIGH, "critical_high": CO2_CRITICAL_HIGH, "unit": "ppm"},
                "water_temperature": {"low": WATER_TEMP_LOW, "high": WATER_TEMP_HIGH, "critical_low": WATER_TEMP_CRITICAL_LOW, "critical_high": WATER_TEMP_CRITICAL_HIGH, "unit": "°C"},
            }
            # AI 환경 판단 (알고리즘이 현재 센서값에 대해 권장하는 릴레이 상태)
            try:
                from agri_ai_core.src.control.manual_control import get_ai_environment_judgment
                ai_judgment = get_ai_environment_judgment(target_farm_id, target_house_id)
                if ai_judgment:
                    result["ai_environment_judgment"] = ai_judgment
            except Exception as e:
                logger.debug(f"[PostgreSQL조회] AI 환경 판단 조회 실패: {e}")

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


# 릴레이(장치) 제어
# LLM이 호출하여 특정 재배사의 장치를 켜거나 끈다.
# relay_manager.set_relay_value를 통해 실제 DB에 릴레이 값을 설정한다.
# ══════════════════════════════════════════════════════════
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


def _control_relay_all_houses(device_name: str = None, action: str = None, farm_id: str = None,
                               mode: str = None, devices: list = None) -> Dict[str, Any]:
    """house_id='all' 요청 시 모든 재배사(hous_id!=0)에 대해 일괄 제어."""
    from agri_ai_core.src.postgresql.connection import db_session
    from agri_ai_core.src.postgresql.queries import GET_ONE_FARM, GET_ALL_HOUSES
    t_start = time.time()
    # farm_id 확인
    target_farm_id = _normalize_id(farm_id)
    if not target_farm_id or target_farm_id == "0":
        target_farm_id = None
    if not target_farm_id:
        with db_session() as database:
            farm = database.fetch_one(GET_ONE_FARM)
            if farm and farm.get("farm_id") is not None:
                target_farm_id = str(farm.get("farm_id"))
    if not target_farm_id:
        return {"success": False, "error": "farm_id를 확인할 수 없습니다."}
    # 모든 재배사 조회 (dict 형식으로 반환)
    with db_session() as database:
        houses = database.fetch_all(GET_ALL_HOUSES, vals=(target_farm_id,), as_dict=True)
    if not houses:
        return {"success": False, "error": "재배사 정보를 조회할 수 없습니다."}
    # device_name이 있으면 mode 무시 — 특정 장치만 제어 (mode는 전체 장치 대상)
    # mode='all_off'/'all_on'에서 action 유추 (device_name과 함께 쓰인 경우)
    eff_action = action
    eff_mode = mode
    if device_name and mode in ("all_off", "all_on"):
        eff_action = "off" if mode == "all_off" else "on"
        eff_mode = None
    results = []
    for house in houses:
        h_id = str(house.get("hous_id", ""))
        if not h_id or h_id == "0":
            continue
        # devices 배열이 있으면 일괄 제어 (다중 장치 1회 DB 쓰기)
        if devices and isinstance(devices, list) and len(devices) > 0:
            r = control_relays_batch(house_id=h_id, devices=devices,
                                     farm_id=target_farm_id, mode=eff_mode)
        else:
            r = control_relay(house_id=h_id, device_name=device_name, action=eff_action,
                              farm_id=target_farm_id, mode=eff_mode)
        results.append({"house_id": h_id, "result": r})
    success_count = sum(1 for r in results if r["result"].get("success"))
    total = len(results)
    elapsed = time.time() - t_start
    logger.info(f"[릴레이전체제어] 완료 ({elapsed:.1f}s) {success_count}/{total}개 재배사 성공")
    # 첫 번째 성공 결과에서 ai_judgment/ai_conflict 추출 (LLM 답변용)
    _first_ok = next((r["result"] for r in results if r["result"].get("success")), {})
    ret = {
        "success": success_count == total and total > 0,
        "message": f"전체 {total}개 재배사({', '.join(r['house_id']+'호' for r in results if r['result'].get('success'))}) 제어 완료.",
        "farm_id": target_farm_id,
        "controlled_houses": [r["house_id"] for r in results if r["result"].get("success")],
        "results": [{"house_id": r["house_id"], "success": r["result"].get("success"),
                     "message": r["result"].get("message", "")} for r in results],
    }
    if _first_ok.get("ai_judgment"):
        ret["ai_judgment"] = _first_ok["ai_judgment"]
    if _first_ok.get("ai_conflict"):
        ret["ai_conflict"] = _first_ok["ai_conflict"]
    return ret


def control_relay(house_id: str, device_name: str = None, action: str = None,
                   farm_id: str = None, mode: str = None) -> Dict[str, Any]:
    # house_id='all' → 전 재배사 일괄 제어
    if str(house_id or "").strip().lower() in ("all", "전체", "모든"):
        return _control_relay_all_houses(device_name=device_name, action=action,
                                         farm_id=farm_id, mode=mode)
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
        if action not in ("on", "off", "reverse"):
            return {"success": False, "error": f"잘못된 action입니다: {action} (on/off/reverse만 가능)"}

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

        # action='reverse': 현재 상태 조회 후 반전
        if action == "reverse":
            from agri_ai_core.src.postgresql.reader import read_latest_relay_info
            from agri_ai_core.src.control.control_common import get_pin_map
            current = read_latest_relay_info(target_farm_id, target_house_id)
            pin_map = get_pin_map(target_house_id)
            pin_key = pin_map.get(device_name)
            current_value = bool(current.get(pin_key, False)) if (current and pin_key) else False
            relay_value = not current_value
        else:
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


# 릴레이 다중 일괄 제어
# 여러 장치를 한 번에 제어한다 (LLM의 반복 tool call 횟수 절감).
# ══════════════════════════════════════════════════════════
def control_relays_batch(house_id: str, devices: List[Dict[str, str]] = None,
                         farm_id: str = None, mode: str = None) -> Dict[str, Any]:
    t_start = time.time()
    logger.info(f"[릴레이일괄제어] 시작 farm_id={farm_id} house_id={house_id} mode={mode} devices={len(devices or [])}건")
    try:
        from agri_ai_core.src.control.relay_manager import set_relay_value
        from agri_ai_core.src.control.control_common import (
            SEMANTIC_LABELS, set_llm_relay_lock, reverse_pin_map,
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



# Opinet 유가정보 API 조회
# 전국/시도/시군구 평균 유가, 최저가 주유소 등 조회
# ══════════════════════════════════════════════════════════
_OPINET_API_KEY = os.getenv("OPNET_API", "")
_OPINET_BASE = "http://www.opinet.co.kr/api"

# 시도 코드 매핑 (Opinet 코드)
_SIDO_MAP = {
    "서울": "01", "경기": "02", "강원": "03", "충북": "04", "충남": "05",
    "전북": "06", "전남": "07", "경북": "08", "경남": "09", "부산": "10",
    "제주": "11", "대구": "14", "인천": "15", "광주": "16", "대전": "17",
    "울산": "18", "세종": "19",
}

# 유종 코드 매핑
_PROD_MAP = {
    "휘발유": "B027", "경유": "D047", "고급휘발유": "B034",
    "등유": "C004", "LPG": "K015", "부탄": "K015",
}

def _opinet_api_call(endpoint: str, params: dict = None) -> Optional[List[Dict]]:
    """Opinet 실시간 API 호출 (실패 시 None)"""
    import requests as _req
    url = f"{_OPINET_BASE}/{endpoint}.do"
    p = {"out": "json", "code": _OPINET_API_KEY}
    if params:
        p.update(params)
    try:
        r = _req.get(url, params=p, timeout=10)
        if r.status_code != 200:
            return None
        text = r.text.strip()
        if text.startswith("<") or "not available" in text:
            return None
        return r.json().get("RESULT", {}).get("OIL", [])
    except Exception:
        return None


def _opinet_db_fallback(query_type: str, prodcd: str, sido_cd: str = None,
                        sigun: str = None) -> Optional[Dict]:
    """DB 폴백: 가장 최근 저장된 데이터 조회"""
    try:
        from agri_ai_core.src.postgresql.reader import db_session
        with db_session() as db:
            if query_type == "low_price":
                area = sido_cd or "00"
                rows = db.fetch_all(
                    "SELECT os_nm, price, new_adr, poll_div_cd, trade_dt "
                    "FROM opinet_low_price WHERE area_cd=%s AND prod_cd=%s "
                    "AND trade_dt=(SELECT MAX(trade_dt) FROM opinet_low_price WHERE area_cd=%s AND prod_cd=%s) "
                    "ORDER BY price LIMIT 20",
                    (area, prodcd, area, prodcd), as_dict=True
                )
                if rows:
                    return {
                        "success": True, "source": "DB(폴백)", "기준일": str(rows[0]["trade_dt"]),
                        "query_type": "최저가 주유소", "count": len(rows),
                        "stations": [{"주유소명": r["os_nm"], "가격": f"{r['price']}원",
                                      "주소": r["new_adr"] or ""} for r in rows],
                    }
            elif query_type == "avg_sido":
                rows = db.fetch_all(
                    "SELECT a.area_nm as sido_nm, p.price, p.diff, p.trade_dt "
                    "FROM opinet_avg_price p JOIN opinet_area_code a ON p.area_cd=a.area_cd "
                    "WHERE p.prod_cd=%s AND a.parent_cd IS NULL AND p.area_cd!='00' "
                    "AND p.trade_dt=(SELECT MAX(trade_dt) FROM opinet_avg_price WHERE prod_cd=%s AND area_cd!='00') "
                    "ORDER BY a.area_cd",
                    (prodcd, prodcd), as_dict=True
                )
                if sido_cd:
                    rows = [r for r in rows if sido_cd in str(r.get("sido_nm", ""))]
                if rows:
                    return {
                        "success": True, "source": "DB(폴백)", "기준일": str(rows[0]["trade_dt"]),
                        "query_type": "시도별 평균가격", "count": len(rows),
                        "prices": [{"시도": r["sido_nm"], "가격": f"{r['price']}원",
                                    "전일대비": f"{r['diff']}원"} for r in rows],
                    }
            elif query_type == "avg_sigun":
                q = ("SELECT a.area_nm as sigun_nm, p.price, p.diff, p.trade_dt "
                     "FROM opinet_avg_price p JOIN opinet_area_code a ON p.area_cd=a.area_cd "
                     "WHERE p.prod_cd=%s AND a.parent_cd=%s "
                     "AND p.trade_dt=(SELECT MAX(trade_dt) FROM opinet_avg_price WHERE prod_cd=%s) "
                     "ORDER BY p.price")
                rows = db.fetch_all(q, (prodcd, sido_cd, prodcd), as_dict=True)
                if rows:
                    return {
                        "success": True, "source": "DB(폴백)", "기준일": str(rows[0]["trade_dt"]),
                        "query_type": "시군구별 평균가격", "count": len(rows),
                        "prices": [{"시군구": r["sigun_nm"], "가격": f"{r['price']}원",
                                    "전일대비": f"{r['diff']}원"} for r in rows],
                    }
            else:  # avg_national
                rows = db.fetch_all(
                    "SELECT prod_nm, price, diff, trade_dt FROM opinet_avg_price "
                    "WHERE area_cd='00' AND trade_dt=(SELECT MAX(trade_dt) FROM opinet_avg_price WHERE area_cd='00') "
                    "ORDER BY prod_cd",
                    as_dict=True
                )
                if rows:
                    return {
                        "success": True, "source": "DB(폴백)", "기준일": str(rows[0]["trade_dt"]),
                        "query_type": "전국 평균 유가", "count": len(rows),
                        "prices": [{"유종": r["prod_nm"], "가격": f"{r['price']}원",
                                    "전일대비": f"{r['diff']}원"} for r in rows],
                    }
    except Exception as e:
        logger.warning(f"[유가정보] DB 폴백 실패: {e}")
    return None


def search_gas_price(query_type: str = "avg_national", sido: str = None,
                     sigun: str = None, prodcd: str = "B027",
                     fuel_name: str = None) -> Dict[str, Any]:
    """Opinet 유가정보 조회 — 실시간 API 우선, 실패 시 DB 폴백"""
    if not _OPINET_API_KEY:
        return {"success": False, "error": "OPNET_API 키가 설정되지 않았습니다."}

    # 유종명 → 코드 변환
    if fuel_name:
        prodcd = _PROD_MAP.get(fuel_name, prodcd)

    # 시도명 → 코드 변환
    sido_cd = None
    if sido:
        for name, code in _SIDO_MAP.items():
            if name in sido or sido in name:
                sido_cd = code
                break
        if not sido_cd:
            sido_cd = sido

    fuel_label = fuel_name or prodcd
    api_result = None

    try:
        if query_type == "low_price":
            params = {"prodcd": prodcd, "cnt": "20"}
            if sido_cd:
                params["area"] = sido_cd
            oils = _opinet_api_call("lowTop10", params)
            if oils:
                stations = [{"주유소명": o.get("OS_NM", ""), "가격": f"{o.get('PRICE', '')}원",
                             "주소": o.get("NEW_ADR") or o.get("VAN_ADR", ""),
                             "상표": o.get("POLL_DIV_CD", "")} for o in oils[:20]]
                api_result = {"success": True, "source": "실시간", "query_type": "최저가 주유소",
                              "유종": fuel_label, "지역": sido or "전국",
                              "count": len(stations), "stations": stations}

        elif query_type == "avg_sido":
            oils = _opinet_api_call("avgSidoPrice", {"prodcd": prodcd})
            if oils:
                prices = []
                for o in oils:
                    if sido_cd and o.get("SIDOCD") != sido_cd:
                        continue
                    prices.append({"시도": o.get("SIDONM", ""), "가격": f"{o.get('PRICE', '')}원",
                                   "전일대비": f"{o.get('DIFF', '')}원"})
                api_result = {"success": True, "source": "실시간", "query_type": "시도별 평균가격",
                              "유종": fuel_label, "count": len(prices), "prices": prices}

        elif query_type == "avg_sigun":
            if not sido_cd:
                return {"success": False, "error": "시도를 지정해주세요 (예: sido='전북')"}
            params = {"prodcd": prodcd, "sido": sido_cd}
            if sigun:
                params["sigun"] = sigun
            oils = _opinet_api_call("avgSigunPrice", params)
            if oils:
                prices = [{"시군구": o.get("SIGUNNM", ""),
                           "가격": f"{o.get('PRICE', '')}원" if o.get("PRICE") else "정보없음",
                           "전일대비": f"{o.get('DIFF', '')}원" if o.get("DIFF") else ""}
                          for o in oils]
                api_result = {"success": True, "source": "실시간", "query_type": "시군구별 평균가격",
                              "유종": fuel_label, "count": len(prices), "prices": prices}

        else:  # avg_national
            oils = _opinet_api_call("avgAllPrice")
            if oils:
                prices = [{"유종": o.get("PRODNM", ""), "가격": f"{o.get('PRICE', '')}원",
                           "전일대비": f"{o.get('DIFF', '')}원",
                           "기준일": o.get("TRADE_DT", "")} for o in oils]
                api_result = {"success": True, "source": "실시간", "query_type": "전국 평균 유가",
                              "count": len(prices), "prices": prices}

    except Exception as e:
        logger.warning(f"[유가정보] 실시간 API 실패: {e}")

    # 실시간 성공 시 반환
    if api_result:
        logger.info(f"[유가정보] 실시간 API 성공: {query_type} {api_result.get('count', 0)}건")
        return api_result

    # DB 폴백
    logger.info(f"[유가정보] 실시간 API 실패 → DB 폴백: {query_type}")
    db_result = _opinet_db_fallback(query_type, prodcd, sido_cd, sigun)
    if db_result:
        return db_result

    return {"success": False, "error": "유가 정보를 조회할 수 없습니다 (API 장애 + DB 데이터 없음)"}


# 도구 실행기 (메인)
# ══════════════════════════════════════════════════════════
def execute_tool(tool_name: str, tool_args: Dict[str, Any]) -> str:
    t_start = time.time()
    logger.info(f"[도구실행] 시작 tool={tool_name} args={tool_args}")

    try:
        if tool_name == "delete_farm_knowledge":
            result = delete_farm_knowledge(
                file_name=tool_args.get("file_name"),
                farm_id=tool_args.get("farm_id"),
            )

        elif tool_name == "search_farm_knowledge":
            result = search_farm_knowledge(
                query=tool_args.get("query"),
                n_results=tool_args.get("n_results", 5),
                file_name=tool_args.get("file_name"),
                farm_id=tool_args.get("farm_id"),
                house_id=tool_args.get("house_id"),
                _meta_hint=bool(tool_args.get("_meta_hint")),
            )

        elif tool_name == "get_farm_realtime_data":
            result = get_farm_realtime_data(
                house_id=tool_args.get("house_id"),
                farm_id=tool_args.get("farm_id"),
                data_type=tool_args.get("data_type", "all")
            )

        elif tool_name == "control_relay":
            devices = tool_args.get("devices")
            h_id = tool_args.get("house_id")
            f_id = tool_args.get("farm_id")
            # house_id='all' + devices 배열 → 전 재배사 다중 장치 일괄 제어
            if devices and isinstance(devices, list) and len(devices) > 0:
                if str(h_id or "").strip().lower() in ("all", "전체", "모든"):
                    result = _control_relay_all_houses(
                        farm_id=f_id, devices=devices, mode=tool_args.get("mode"),
                    )
                else:
                    result = control_relays_batch(
                        house_id=h_id, devices=devices,
                        farm_id=f_id, mode=tool_args.get("mode"),
                    )
            else:
                result = control_relay(
                    house_id=h_id,
                    device_name=tool_args.get("device_name"),
                    action=tool_args.get("action"),
                    farm_id=f_id,
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

        elif tool_name == "search_gas_price":
            result = search_gas_price(
                query_type=tool_args.get("query_type", "avg_national"),
                sido=tool_args.get("sido"),
                sigun=tool_args.get("sigun"),
                prodcd=tool_args.get("prodcd", "B027"),
                fuel_name=tool_args.get("fuel_name"),
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
