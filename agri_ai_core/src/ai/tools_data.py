# ══════════════════════════════════════════════════════════════════════════════
# 데이터 조회/삭제 도구 — VectorDB 검색, 농장 실시간 데이터 조회, 학습 데이터 삭제.
# tools_executor.py에서 분리된 L5 계층 모듈.
# --->
# _build_chroma_where_conditions: 검색 대상 farm_id/house_id 조합을 where 조건 리스트로 변환
# delete_farm_knowledge: 학습 데이터 삭제 (파일명/전체, 권한별)
# search_farm_knowledge: ChromaDB VectorDB 검색 + Reranker
# get_farm_realtime_data: 센서/릴레이/임계값/AI판단 실시간 조회
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
            # [FIX] farm_id/house_id 필터가 있을 때 필터 없는 폴백도 추가
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

        # 환경 제어 임계값 + AI 판단 포함
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
            try:
                from agri_ai_core.src.control.manual_control import get_ai_environment_judgment
                ai_judgment = get_ai_environment_judgment(target_farm_id, target_house_id)
                if ai_judgment:
                    result["ai_environment_judgment"] = ai_judgment
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
# [Phase 1-3] get_system_status — LLM이 자신의 시스템을 파악할 수 있는 종합 조회
# ══════════════════════════════════════════════════════════════════════════════
def get_system_status(farm_id: str = None) -> Dict[str, Any]:
    from agri_ai_core.src.postgresql.connection import db_session
    from agri_ai_core.src.ai.tools_utils import normalize_id as _normalize_id

    target_farm = _normalize_id(farm_id) or "1"
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
                houses.append({
                    "house_id": str(r["hous_id"]),
                    "name": r.get("hous_name"),
                    "ctrl_type": r.get("ctrl_type") or "algorithm",
                    "mnul_ctrl_flag": bool(r.get("mnul_ctrl_flag")),
                    "growth_stage": _STAGE_NAME.get(lvel, "미설정") if lvel else "미설정",
                    "growth_stage_code": lvel,
                    "crop_kind": r.get("crop_kind"),
                    "sensor_refresh_sec": r.get("snsr_rfrs_itvl"),
                    "last_sensor_time": r["last_get_dttm"].isoformat() if r.get("last_get_dttm") else None,
                })
            result["houses"] = houses

        # AI 순환 루프 상태 (manual_control._ai_loop_running 플래그 조회)
        try:
            from agri_ai_core.src.control import manual_control as mc
            ai_loop_running = bool(getattr(mc, "_ai_loop_running", False))
            ai_delay = int(getattr(mc, "_AI_LOOP_DELAY_SEC", 10))
            ai_houses = [h for h in houses if h["ctrl_type"] == "ai"]
            result["ai_control_loop"] = {
                "running": ai_loop_running,
                "delay_sec_between_houses": ai_delay,
                "target_houses": [h["house_id"] for h in ai_houses],
                "note": "ctrl_type='ai' 재배사만 순환 대상. 각 재배사 간 delay_sec_between_houses 초 대기.",
            }
        except Exception as _e:
            result["ai_control_loop"] = {"error": str(_e)}

        # APScheduler 등록 Job 조회
        try:
            from agri_ai_core.src.control.task_scheduler import _scheduler as _sch
            jobs = []
            if _sch is not None:
                for j in _sch.get_jobs():
                    jobs.append({
                        "id": j.id,
                        "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
                        "trigger": str(j.trigger),
                    })
            result["scheduler"] = {"running": _sch.running if _sch else False, "jobs": jobs}
        except Exception as _e:
            result["scheduler"] = {"error": str(_e)}

        return result

    except Exception as e:
        logger.error(f"[get_system_status] 오류: {e}")
        return {"success": False, "error": str(e)}
