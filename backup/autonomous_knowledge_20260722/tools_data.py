# ══════════════════════════════════════════════════════════════════════════════
# 데이터 조회/삭제 도구 — VectorDB 검색, 농장 실시간 데이터 조회, 학습 데이터 삭제.
# L5 계층 모듈 (tools_executor.py 와 동급).
# --->
# _build_chroma_where_conditions: 검색 대상 farm_id/house_id 조합을 where 조건 리스트로 변환
# delete_farm_knowledge: 학습 데이터 삭제 (파일명/전체, 권한별)
# search_farm_knowledge: ChromaDB VectorDB 검색 + Reranker
# get_farm_realtime_data: 센서/릴레이/임계값/AI판단 실시간 조회
# get_weather_forecast: 농장 소재지 기상청 단기예보 (farm_m_info kma_nx/ny 격자)
# ══════════════════════════════════════════════════════════════════════════════
import os
import re
import time
from datetime import datetime
from typing import Dict, Any

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.farm_cache import get_farm_name as _get_farm_name
from agri_ai_core.src.ai.tools_utils import (
    normalize_id as _normalize_id,
    parse_positive_int as _parse_positive_int,
    parse_positive_float as _parse_positive_float,
    parse_optional_int as _parse_optional_int,
    to_chroma_where as _to_chroma_where,
)

logger = setup_logger(__name__)

# 시스템/가상 농장 ID (관리자 선택 시 전체 데이터 검색, 일반 사용자는 자기 농장 + 시스템 농장 데이터 검색)
_SYSTEM_FARM_ID = "0"

# 메타 질의(파일 목록) 키워드 — Reranker 바이패스 및 시스템 농장 데이터 노출 방지에 사용
_META_QUERY_KEYWORDS = ("파일", "학습", "목록", "리스트", "자료", "문서", "업로드", "RAG", "데이터")


# ═════════════════════════════════════════════════════════════════════
# ChromaDB where 조건 빌더 (순수 함수, 단위테스트 용이)
# ═════════════════════════════════════════════════════════════════════
def _build_chroma_where_conditions(query, farm_id, house_id, auth_farm_id, meta_hint):
    if farm_id is not None and str(farm_id) == _SYSTEM_FARM_ID:
        logger.info("[VectorDB검색] 시스템 농장 모드: 전체 농장 데이터 검색")
        return [None]

    candidates = []

    where_str = {}
    if farm_id is not None:
        where_str["farm_id"] = str(farm_id)
    if house_id is not None:
        where_str["house_id"] = str(house_id)
    if where_str:
        candidates.append(_to_chroma_where(where_str))

    where_int = {}
    farm_id_int = _parse_optional_int(farm_id)
    house_id_int = _parse_optional_int(house_id)
    if farm_id_int is not None:
        where_int["farm_id"] = farm_id_int
    if house_id_int is not None:
        where_int["house_id"] = house_id_int
    chroma_int = _to_chroma_where(where_int)
    if chroma_int and chroma_int not in candidates:
        candidates.append(chroma_int)

    is_meta_query = any(kw in (query or "") for kw in _META_QUERY_KEYWORDS) or bool(meta_hint)
    if farm_id is not None and not (auth_farm_id is not None and is_meta_query):
        sys_str = _to_chroma_where({"farm_id": _SYSTEM_FARM_ID})
        if sys_str not in candidates:
            candidates.append(sys_str)
        sys_farm_int = _parse_optional_int(_SYSTEM_FARM_ID)
        if sys_farm_int is not None:
            sys_int = _to_chroma_where({"farm_id": sys_farm_int})
            if sys_int not in candidates:
                candidates.append(sys_int)
        logger.info(f"[VectorDB검색] 일반 농장 모드: farm_id={farm_id} + 시스템 농장 데이터 검색")
    elif farm_id is not None:
        logger.info(f"[VectorDB검색] 파일목록 질문 — 자기 농장만 검색 (farm_id={farm_id}, 시스템 농장 제외)")

    return candidates if candidates else [None]


# ══════════════════
# 학습 데이터 삭제
# ══════════════════
def delete_farm_knowledge(file_name: str, farm_id: str = None, auth_farm_id: str = None) -> Dict[str, Any]:
    t_start = time.time()
    logger.info(f"[학습삭제] 시작 file_name={file_name} farm_id={farm_id} auth_farm_id={auth_farm_id}")
    try:
        from agri_ai_core.src.chroma.collections import document_collection, farm_knowledge_collection
        from agri_ai_core.src.chroma.operations import get_documents, delete_document

        if not file_name:
            return {"success": False, "error": "file_name이 필요합니다."}

        # 시스템관리자: auth_farm_id=None → 전체 농장 삭제 가능
        # 농장관리자: auth_farm_id=자기농장 → 자기 농장만 삭제 가능
        is_admin = auth_farm_id is None
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
        deleted_files = []
        failed_files = []

        # ────────────────────────────────────────────────────────────────────
        # 특정 파일명에 대한 삭제 대상 ID 수집
        # (공백↔밑줄 자동 변환 + str/int farm_id + 시스템 농장 폴백)
        # ────────────────────────────────────────────────────────────────────
        def _collect_ids_for_file(coll, target_name):
            ids = set()
            name_variants = [target_name]
            if " " in target_name:
                name_variants.append(target_name.replace(" ", "_"))
            elif "_" in target_name:
                name_variants.append(target_name.replace("_", " "))

            farm_id_wheres = []
            if is_admin and not farm_id:
                farm_id_wheres.append(None)
            elif farm_id:
                farm_id_wheres.append({"farm_id": {"$eq": str(farm_id)}})
                if str(farm_id).isdigit():
                    farm_id_wheres.append({"farm_id": {"$eq": int(farm_id)}})
            else:
                farm_id_wheres.append(None)

            from itertools import product
            for name, field, fw in product(name_variants, ("file_name", "file_name_stored"), farm_id_wheres):
                file_cond = {field: {"$eq": name}}
                w = file_cond if fw is None else {"$and": [file_cond, fw]}
                res = get_documents(coll, where=w, include=["metadatas"], limit=10000)
                ids.update(res.get("ids") or [])
            return ids

        for coll in collections:
            if not coll:
                continue
            all_ids: set = set()

            if _is_delete_all:
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


# ══════════════════════════════
# VectorDB 검색 + LLM Reranker
# ══════════════════════════════
def search_farm_knowledge(
    query: str,
    n_results: int = 5,
    file_name: str = None,
    farm_id: str = None,
    house_id: str = None,
    auth_farm_id: str = None,
    _meta_hint: bool = False,
) -> Dict[str, Any]:
    t_start = time.time()
    logger.info(
        f"[VectorDB검색] 시작 query=\"{(query or '')[:80]}\" "
        f"n_results={n_results} file_name={file_name} farm_id={farm_id} house_id={house_id}"
    )
    try:
        from agri_ai_core.src.ai.embedder import embed_text
        from agri_ai_core.src.chroma.collections import document_collection, farm_knowledge_collection, web_knowledge_collection
        from agri_ai_core.src.chroma.operations import query_documents

        max_results = _parse_positive_int(n_results, 5)
        if file_name:
            max_results = max(max_results, 30)

        source_where_candidates = _build_chroma_where_conditions(
            query=query, farm_id=farm_id, house_id=house_id,
            auth_farm_id=auth_farm_id, meta_hint=_meta_hint,
        )

        t_embed = time.time()
        logger.debug(f"[VectorDB검색] 임베딩 생성 시작 query=\"{(query or '')[:60]}\"")
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
            doc_where = None
            if file_name:
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
            # farm_id/house_id 필터가 있을 때 필터 없는 폴백도 추가
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

        # LLM 기반 Reranker 적용
        # file_name 또는 메타 질문 시 Reranker 바이패스
        _is_meta_query = any(kw in (query or "") for kw in _META_QUERY_KEYWORDS) or bool(_meta_hint)
        if _meta_hint and not any(kw in (query or "") for kw in _META_QUERY_KEYWORDS):
            logger.info(f"[VectorDB검색] _meta_hint로 메타 쿼리 활성화 (원본 query에 키워드 없음)")
        if file_name or _is_meta_query:
            if _is_meta_query:
                logger.info(f"[VectorDB검색] 메타 질문 감지 → Reranker 바이패스 (query=\"{query[:40]}\")")
                # 메타 쿼리 시 web_knowledge 및 growth_rag 결과 제외
                before_count = len(deduped_results)
                deduped_results = [
                    r for r in deduped_results
                    if r.get("collection") != "web_knowledge"
                    and (r.get("metadata") or {}).get("data_type") != "growth_rag"
                ]
                excluded = before_count - len(deduped_results)
                if excluded:
                    logger.info(f"[VectorDB검색] 메타 쿼리: web_knowledge/growth_rag {excluded}건 제외")
            doc_results = [r for r in deduped_results if r.get("collection") == "document"]
            if doc_results:
                deduped_results = doc_results[:max_results]
                logger.info(f"[VectorDB검색] document 결과 우선 반환 {len(deduped_results)}건")
            else:
                deduped_results = deduped_results[:max_results]
                logger.info(f"[VectorDB검색] document 결과 없음, 전체 {len(deduped_results)}건 폴백")
        else:
            try:
                from agri_ai_core.src.ai.reranker import rerank_results
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

        # 메타 질문 시 ChromaDB 직접 조회로 완전한 파일 목록 추출
        _file_list = None
        if _is_meta_query:
            try:
                from agri_ai_core.src.chroma.operations import get_documents
                from agri_ai_core.src.chroma.collections import document_collection, farm_knowledge_collection

                _is_admin_list = (auth_farm_id is None)
                _seen_files: set = set()
                _file_entries = []

                for _coll_name, _coll_label in [
                    (document_collection(), "document"),
                    (farm_knowledge_collection(), "farm_knowledge"),
                ]:
                    if not _coll_name:
                        continue
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
                            if not _is_admin_list and _raw_fid in ("0", "", _SYSTEM_FARM_ID):
                                continue
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
                _is_admin_list = (auth_farm_id is None)
                _seen_files = set()
                _file_entries = []
                for item in formatted_results:
                    _meta = item.get("metadata") or {}
                    _fn = _meta.get("file_name") or _meta.get("file_name_stored") or ""
                    if not _is_admin_list:
                        _file_fid = str(_meta.get("farm_id", ""))
                        if _file_fid != str(farm_id):
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
        if _is_meta_query:
            result_data["file_list"] = _file_list or []
            result_data["file_count"] = len(_file_list or [])
            if not _file_list:
                result_data["file_list_message"] = "선택된 농장에 학습된 파일이 없습니다."
                # 비관리자 파일목록 질문에서 file_list=[]이면 results도 비워 LLM 혼동 방지
                if auth_farm_id is not None:
                    result_data["results"] = []
                    result_data["count"] = 0
        elif _file_list:
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


# ═══════════════════════════════════════════════════════
# 농장 실시간 데이터 가져오기 (센서+릴레이+임계값+AI판단)
# ═══════════════════════════════════════════════════════
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

        # 시스템 농장(farm_id=0)은 센서/릴레이 없음 → GET_ONE_FARM으로 첫 번째 실제 농장 대체
        if target_farm_id == "0":
            try:
                from agri_ai_core.src.postgresql.queries import GET_ONE_FARM
                with db_session() as database:
                    real_farm = database.fetch_one(GET_ONE_FARM)
                if real_farm and real_farm.get("farm_id") is not None:
                    target_farm_id = str(real_farm["farm_id"])
                    # 명시적 유효 재배사 ID(숫자)는 유지 — None/"0"/"all" 만 초기화
                    if not house_id or house_id in ("0", "all"):
                        house_id = None
                    logger.info(f"[PostgreSQL조회] farm_id=0(시스템농장) → 실제 농장 자동 대체: farm_id={target_farm_id}, house_id={house_id or '(자동조회)'}")
                else:
                    return {
                        "success": False,
                        "error": "시스템 농장(farm_id=0)은 센서 데이터가 없고, 등록된 실제 농장도 없어요.",
                        "house_id": house_id, "farm_id": "0"
                    }
            except Exception as e:
                logger.warning(f"[PostgreSQL조회] 시스템 농장 → 실제 농장 대체 실패: {e}")
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

            # 릴레이 시멘틱 매핑 — LLM 혼동 방지 위해 "현재 적용 상태" 라벨 명시
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
                result["relay_mapping_meta"] = {
                    "label": "현재 실제 적용된 릴레이 상태 (read-only snapshot)",
                    "source": "sensor_l_relay 최신 row",
                }

        # 환경 제어 임계값 + AI 판단 포함 — 재배사별 DB(SENSOR_M_SETTING) 실시간 값
        if data_type in ["sensor", "all"]:
            from agri_ai_core.src.control.ai_thresholds import get_thresholds as _get_ts
            _t = _get_ts(farm_id, house_id)
            result["environment_thresholds"] = {
                "indoor_temperature": {"low": _t.temp_low, "high": _t.temp_high, "critical_low": _t.temp_critical_low, "critical_high": _t.temp_critical_high, "unit": "°C"},
                "indoor_humidity": {"low": _t.humidity_low, "high": _t.humidity_high, "critical_low": _t.humidity_critical_low, "critical_high": _t.humidity_critical_high, "unit": "%"},
                "co2": {"low": _t.co2_low, "high": _t.co2_high, "critical_high": _t.co2_critical_high, "unit": "ppm"},
                "water_temperature": {"low": _t.water_temp_low, "high": _t.water_temp_high, "critical_low": _t.water_temp_critical_low, "critical_high": _t.water_temp_critical_high, "unit": "°C"},
            }
            # AI/알고리즘 모드 분리 — AI 모드 호기에 알고리즘 64케이스 결과가
            # 권장으로 노출되면 농장주 채팅 답변이 현재상태(relay_mapping) 와 모순되므로
            # AI 모드 호기에는 algorithm_judgment 차단, 알고리즘 모드는 라벨 명시 후 유지.
            try:
                ctrl_type = "algorithm"
                with db_session() as database:
                    row = database.fetch_one(
                        query="SELECT ctrl_type FROM farmhouse_m_info "
                              "WHERE farm_id=%s AND hous_id=%s",
                        vals=(target_farm_id, target_house_id),
                    )
                    if row and row.get("ctrl_type"):
                        ctrl_type = str(row.get("ctrl_type"))
                result["control_mode"] = ctrl_type

                if ctrl_type != "ai":
                    from agri_ai_core.src.control.manual_control import get_ai_environment_judgment
                    ai_judgment = get_ai_environment_judgment(target_farm_id, target_house_id)
                    if ai_judgment:
                        # 기존 키 (llm_response.py 후방호환) + 명료한 신규 키 둘 다 채움
                        result["ai_environment_judgment"] = ai_judgment
                        result["algorithm_proposed_next_cycle"] = ai_judgment
                        result["algorithm_proposed_meta"] = {
                            "label": "알고리즘 모드 64케이스 제안값 (아직 미적용)",
                            "warning": "현재 적용 상태는 relay_mapping 을 참조. 이 값과 혼동 금지.",
                        }
                else:
                    result["algorithm_proposed_skipped"] = (
                        "AI 모드 호기 — 알고리즘 제안값 노출 차단 (현재 상태는 relay_mapping 참조)"
                    )
            except Exception as e:
                logger.info(f"[PostgreSQL조회] AI 환경 판단 조회 실패: {e}")

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



# ══════════════════════════════════════════════════════════════════════════════
# get_system_status — LLM이 자신의 시스템을 파악할 수 있는 종합 조회
# ══════════════════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 재배사의 실제 최신 센서 수신 시각 — sensor_l_recording 실데이터.
# farmhouse_m_info.last_get_dttm 은 갱신되지 않는 죽은 컬럼이라 쓰지 않는다.
# ────────────────────────────────────────────────────────────────────
def _last_sensor_time(db, farm_id, house_id):
    try:
        row = db.fetch_one(
            query=("SELECT max(recd_dttm) t FROM sensor_l_recording "
                   "WHERE farm_id=%s AND hous_id=%s"),
            vals=(farm_id, house_id))
        t = (row or {}).get("t")
        return t.isoformat() if t else None
    except Exception:
        return None


# ────────────────────────────────────────────────────────────────────
# 현재 카메라 프레임을 촬영·판독해 반환 (LLM 채팅용).
#   capture_image(4소스 자동) → analyze_heuristics(색상/곰팡이 휴리스틱)
#   → analyze_vision_llm(gemma3 멀티모달 판독) 을 get_camera_context 가 일괄 수행.
#   ⛔ 제어 모듈(ai_camera_vision)은 지연 import — 채팅 경로에 결합하지 않는다.
#   촬영 실패(원격 보드 미응답) 시 환각 없이 정직하게 실패 사유를 반환한다.
# ────────────────────────────────────────────────────────────────────
def get_camera_view(farm_id: str = None, house_id: str = None) -> Dict[str, Any]:
    from agri_ai_core.src.ai.tools_utils import normalize_id as _normalize_id
    from agri_ai_core.src.ai.tools_auth import require_non_zero_house

    tf = _normalize_id(farm_id) or "1"
    th = _normalize_id(house_id)
    zero_err = require_non_zero_house(th)   # None/0/'all' 거부 — 카메라는 특정 재배사 필요
    if zero_err:
        return zero_err
    try:
        from agri_ai_core.src.control.ai_camera_vision import (
            get_camera_context, format_camera_block,
        )
        ctx = get_camera_context(int(tf), int(th))
        if not ctx:
            return {"success": False, "farm_id": tf, "house_id": th, "captured": False,
                    "message": "카메라 촬영 실패 — 카메라(원격 보드) 미응답. "
                               "5199 원격 보드가 셋업 검증 중이면 정상적으로 내려가 "
                               "있을 수 있습니다. 보드 상태를 확인해 주세요."}
        # 웹 접근 가능한 스냅샷 URL — nginx /camera/{farm}/{house}/ 프록시(→ RPi 스트리머).
        # 채팅창에 실제 영상 표시용(answer_generator 가 답변에 확정 첨부).
        image_url = f"/camera/{tf}/{th}/snapshot"
        return {"success": True, "farm_id": tf, "house_id": th, "captured": True,
                "image_url": image_url,
                "heuristics": ctx.get("heuristics"),
                "vision": ctx.get("vision_text") or "(비전 모델 미설정 — 휴리스틱만)",
                "summary": format_camera_block(ctx)}
    except Exception as e:
        logger.error(f"[get_camera_view] 오류 farm={tf} house={th}: {e}")
        return {"success": False, "error": str(e)}


# 현재 릴레이의 semantic ON/OFF 라벨 리스트 — LLM 이 raw SQL 없이 릴레이 상태를
# 모드와 함께 한 번에 받도록 get_system_status 각 재배사에 포함(릴레이 SQL 오작성 방지).
def _house_relay_state(farm_id, house_id):
    try:
        from agri_ai_core.src.postgresql.reader import read_latest_relay_info
        from agri_ai_core.src.control.control_common import reverse_pin_map, SEMANTIC_LABELS
        relay = read_latest_relay_info(farm_id, house_id) or {}
        rev = reverse_pin_map(house_id)
        on, off = [], []
        for pin_key, value in relay.items():
            if not (pin_key.startswith("relay_") and pin_key.endswith("_flag")):
                continue
            sem = rev.get(pin_key)
            if not sem:
                continue
            (on if bool(value) else off).append(SEMANTIC_LABELS.get(sem, sem))
        return on, off
    except Exception as e:
        logger.warning(f"[get_system_status] 릴레이 상태 조회 실패 farm={farm_id} house={house_id}: {e}")
        return [], []


# 최근 AI 제어 결정(사유 포함) — LLM 이 ai_decision_log 를 raw SQL(잘못된 컬럼 device_name 등)
# 로 조회하다 실패하는 것을 방지. get_system_status 각 재배사에 최신 1건을 실어 준다.
def _house_last_decision(farm_id, house_id):
    try:
        from agri_ai_core.src.postgresql.connection import db
        rows = db.fetch_all(
            query=("SELECT to_char(decided_at,'MM-DD HH24:MI') t, action, circulation, reason "
                   "FROM ai_decision_log WHERE farm_id=%s AND house_id=%s "
                   "ORDER BY decided_at DESC LIMIT 1"),
            vals=(int(farm_id), int(house_id)), as_dict=True) or []
        if rows:
            d = rows[0]
            return {"time": d.get("t"), "action": d.get("action"),
                    "circulation": d.get("circulation"), "reason": (d.get("reason") or "")[:250]}
    except Exception as e:
        logger.warning(f"[get_system_status] 최근결정 조회 실패 farm={farm_id} house={house_id}: {e}")
    return None


def get_system_status(farm_id: str = None) -> Dict[str, Any]:
    from agri_ai_core.src.postgresql.connection import db_session
    from agri_ai_core.src.ai.tools_utils import normalize_id as _normalize_id

    target_farm = _normalize_id(farm_id) or "1"

    # 세션 범위 룰: 시스템 농장(farm_id=0) 세션은 "전체 실농장" 대상이다.
    # 농장 0 자체(개발용 재배사)는 농장주 응답에 노출하지 않는다.
    if target_farm == "0":
        try:
            with db_session() as db:
                frows = db.fetch_all(
                    query="SELECT farm_id FROM farm_m_info WHERE farm_id > 0 ORDER BY farm_id",
                    as_dict=True,
                ) or []
            farms_out = []
            for fr in frows:
                sub = get_system_status(str(fr["farm_id"]))
                sub.pop("scheduler", None)   # 전역 항목은 농장별 반복 제외
                farms_out.append(sub)
            return {"success": True, "scope": "all_farms",
                    "note": "시스템 세션 — 등록된 전체 농장의 요약",
                    "farms": farms_out}
        except Exception as e:
            logger.error(f"[get_system_status] 전체 농장 순회 오류: {e}")
            return {"success": False, "error": str(e)}

    result: Dict[str, Any] = {"success": True, "farm_id": target_farm}

    try:
        with db_session() as db:
            # 농장 정보
            farm_row = db.fetch_one(
                query="SELECT farm_id, farm_name, addr, main_prdt, rmks, tel_no FROM farm_m_info WHERE farm_id=%s",
                vals=(target_farm,),
            )
            if farm_row:
                result["farm_info"] = {
                    "name": farm_row.get("farm_name"),
                    "address": farm_row.get("addr"),
                    "main_product": farm_row.get("main_prdt"),
                    "tel": farm_row.get("tel_no"),
                    "memo": farm_row.get("rmks"),
                }

            # 재배사별 제어 상태
            _STAGE_NAME = {1: "발아기", 2: "생육기", 3: "수확기", 4: "휴지기"}
            rows = db.fetch_all(
                query=("SELECT farm_id, hous_id, hous_name, mnul_ctrl_flag, ctrl_type, "
                       "crop_lvel, crop_kind, snsr_rfrs_itvl, last_get_dttm "
                       "FROM farmhouse_m_info "
                       "WHERE farm_id=%s AND hous_id>0 AND COALESCE(dlte_yn,'N')<>'Y' "
                       "ORDER BY hous_id"),
                vals=(target_farm,),
                as_dict=True,
            )
            houses = []
            for r in rows:
                lvel = int(r.get("crop_lvel") or 0)
                # 유효 운용방식 — 화면(운용방식)과 동일 3값. ⛔ 판정 규칙 주의:
                # mnul_ctrl_flag=False 가 "수동(사용자 직접입력)" (필드명과 반대 의미,
                # manual_control 판정과 동일). True 일 때만 ctrl_type 이 유효.
                if not r.get("mnul_ctrl_flag"):
                    _op_mode = "수동(사용자 직접입력)"
                elif (r.get("ctrl_type") or "algorithm") == "ai":
                    _op_mode = "AI"
                else:
                    _op_mode = "알고리즘"
                _r_on, _r_off = _house_relay_state(target_farm, r["hous_id"])
                houses.append({
                    "house_id": str(r["hous_id"]),
                    "name": r.get("hous_name"),
                    "operation_mode": _op_mode,
                    "relay_on": _r_on,
                    "relay_off": _r_off,
                    "last_decision": _house_last_decision(target_farm, r["hous_id"]),
                    "ctrl_type": r.get("ctrl_type") or "algorithm",
                    "mnul_ctrl_flag": bool(r.get("mnul_ctrl_flag")),
                    "growth_stage": _STAGE_NAME.get(lvel, "미설정") if lvel else "미설정",
                    "growth_stage_code": lvel,
                    "crop_kind": r.get("crop_kind"),
                    "sensor_refresh_sec": r.get("snsr_rfrs_itvl"),
                    # ⛔ last_get_dttm 은 갱신 코드가 0건이라 2025-12-02 에 멈춘
                    #   죽은 컬럼이다(2026-07-17 실측). 이 값을 주면 LLM 이
                    #   "센서가 7개월째 안 들어온다"고 오보한다 → 실데이터 사용.
                    "last_sensor_time": _last_sensor_time(db, target_farm, r["hous_id"]),
                })
            result["houses"] = houses

        # ⛔ AI 순환 루프·스케줄러 가동 여부는 프로세스 경계를 넘어야 한다
        #   (2026-07-17 실측 사고). 과거엔 manual_control._ai_loop_running 과
        #   task_scheduler._scheduler 를 getattr 로 읽었는데, 이는 **스케줄러
        #   프로세스의 메모리 변수**다. 이 도구는 FastAPI 프로세스에서 실행되므로
        #   그 변수를 볼 수 없어 항상 running=false / jobs=[] 를 반환했고,
        #   LLM 이 "AI 제어 루프가 실행 중이지 않다"고 농장주에게 거짓 보고했다.
        #   → 프로세스 존재 여부(tools_service._health)로 실측한다.
        try:
            from agri_ai_core.src.ai.tools_service import _health
            from agri_ai_core.src.control import manual_control as mc
            running = _health(("proc", "agri_ai_core.scheduler"))
            ai_houses = [h for h in houses if h["operation_mode"] == "AI"]
            result["ai_control_loop"] = {
                "running": running,
                "delay_sec_between_houses": int(getattr(mc, "_AI_LOOP_DELAY_SEC", 10)),
                "target_houses": [h["house_id"] for h in ai_houses],
                "note": ("ctrl_type='ai' 재배사만 순환 대상. running 은 스케줄러 "
                         "프로세스 가동 여부(실측). 실제 제어 반영 여부는 "
                         "last_sensor_time / ai_decision_log 로 확인."),
            }
        except Exception as _e:
            result["ai_control_loop"] = {"error": str(_e)}

        # 스케줄러 — 위와 동일 사유로 프로세스 실측. Job 목록은 다른 프로세스의
        # APScheduler 인스턴스라 조회 불가하므로 넘기지 않는다(빈 배열을 주면
        # LLM 이 "등록된 작업이 없다"고 오보한다).
        try:
            from agri_ai_core.src.ai.tools_service import _health
            result["scheduler"] = {
                "running": _health(("proc", "agri_ai_core.scheduler")),
                "note": ("스케줄러 프로세스 가동 여부(실측). 등록 Job 목록은 별도 "
                         "프로세스라 여기서 조회 불가 — 실제 동작 확인은 "
                         "search_logs 또는 list_services 사용."),
            }
        except Exception as _e:
            result["scheduler"] = {"error": str(_e)}

        return result

    except Exception as e:
        logger.error(f"[get_system_status] 오류: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# get_weather_forecast — 농장 소재지 기상청 단기예보
#   farm_m_info 의 주소·KMA 격자(kma_nx/ny)로 내부 KMA 예보를 1초 내 반환.
#   농장 추가시 코드 변경 없음.
#   ai_weather_forecast 는 외부 API 수집 전용 인프라성 모듈(제어 로직 없음)이라
#   제어/대화 모드 분리 룰의 예외(인프라성 import 허용)에 해당.
# ═══════════════════════════════════════════════════════════════════════════════
def get_weather_forecast(farm_id: str = None, house_id: str = None) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.control.ai_weather_forecast import get_forecast, format_forecast_block
        from agri_ai_core.src.postgresql.connection import db_session
        from agri_ai_core.src.postgresql.queries import GET_ONE_FARM

        fid = str(farm_id or "1").strip()
        if fid == "0":
            # 시스템 농장(0) → 첫 실제 농장 대체 (타 도구와 동일 규칙)
            with db_session() as database:
                real = database.fetch_one(GET_ONE_FARM)
            if real and real.get("farm_id") is not None:
                fid = str(real["farm_id"])

        hid = str(house_id or "0").strip()
        if not hid.isdigit():
            hid = "0"

        payload = get_forecast(int(fid), int(hid))
        block = format_forecast_block(payload)
        if not block or "온도" not in block:
            return {"success": False,
                    "error": "기상청 예보 조회 실패 — 잠시 후 재시도하거나 search_web 으로 대체하세요."}

        with db_session() as database:
            row = database.fetch_one(
                "SELECT farm_name, addr FROM farm_m_info WHERE farm_id = %s", (fid,))
        head = (f"[{row['farm_name']} 소재지 기상청 예보 — {row['addr']}]"
                if row else f"[farm {fid} 기상청 예보]")
        return {"success": True, "message": f"{head}\n{block}"}
    except Exception as e:
        logger.error(f"[날씨예보 도구] 조회 실패: {e}")
        return {"success": False, "error": str(e)}
