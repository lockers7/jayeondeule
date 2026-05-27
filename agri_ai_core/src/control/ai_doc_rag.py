# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 도메인 지식 RAG 검색·저장 모듈 (M12 동반)
# setup/load_domain_knowledge.py 로 적재된 document_collection
# 에서 현재 상황·결정 사유와 관련된 매뉴얼/논문 청크를 1~2건 검색해 LLM 에 제공.
# save_domain_knowledge — 사용자가 AI 채팅으로 알려주는 운영
# 노하우/룰을 도구 호출 1번으로 같은 컬렉션에 영속 저장. 다음 사이클부터 자동
# 검색되어 LLM 결정에 반영. 사용자 ↔ Claude 중계 없이 LLM 이 직접 학습 보유.
#
# 호출 룰:
#   • query_domain_knowledge / format_doc_block — control_ai_environment 에서만.
#   • save_domain_knowledge — tools_data 의 LLM 도구 핸들러에서 호출.
# --->
# query_domain_knowledge: 검색 텍스트 → 상위 N건 dict list
# format_doc_block:       user prompt 한 블록
# save_domain_knowledge:  사용자 채팅 입력을 도메인 지식 RAG 에 영속 저장
# ══════════════════════════════════════════════════════════════════════════════
import time
import uuid
from typing import Any, Dict, List, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_DOC_TOP_K = 2
_DOC_PREVIEW = 220

# TTL 캐시 금지 (실시간 데이터 정책) — 매 호출 임베딩 + 검색.
# document_collection 의 사용자 추가 도메인 지식이 즉시 반영됨.


# ────────────────────────────────────────────────────────────────────
# document_collection 에서 query_text 로 상위 N건 검색 → list[dict].
# 컬렉션 미설정/실패 시 [].
# ────────────────────────────────────────────────────────────────────
def query_domain_knowledge(query_text: str, top_k: int = _DOC_TOP_K,
                           farm_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if not query_text:
        return []
    # 캐시 없음 — 매 호출 임베딩 + chroma 검색 (실시간 데이터 정책).
    try:
        from agri_ai_core.src.ai.embedder import embed_text
        from agri_ai_core.src.chroma.collections import document_collection
        from agri_ai_core.src.chroma.operations import query_documents

        coll = document_collection()
        if not coll:
            logger.info("[AI도메인RAG] document_collection 미설정 — 스킵")
            return []
        emb = embed_text(query_text)
        if not emb:
            logger.info("[AI도메인RAG] 임베딩 실패 — 스킵")
            return []
        logger.info(
            f"[AI도메인RAG] 검색 시작 collection={coll} top_k={top_k} "
            f"query=\"{query_text[:60]}...\""
        )
        # 농장 스코프: 해당 농장 지식 + 전역(farm_id='0' — 모든 농장 공통) 만 매칭.
        # farm_id 미전달 시 기존과 동일하게 전체 검색 (호환).
        _fid = str(farm_id).strip() if farm_id is not None else ""
        if _fid and _fid != "0":
            _where = {"$and": [
                {"data_type": {"$eq": "domain_knowledge"}},
                {"$or": [{"farm_id": {"$eq": _fid}}, {"farm_id": {"$eq": "0"}}]},
            ]}
        else:
            _where = {"data_type": "domain_knowledge"}
        result = query_documents(
            coll,
            query_embeddings=[emb],
            n_results=int(top_k),
            where=_where,
            include=["documents", "metadatas", "distances"],
        )
        if not result:
            return []
        # ⚠ query_documents 는 이미 [[...]]→[...] 평탄화해 반환 — 추가 [0] 벗기기 금지
        #   (이중 평탄화 시 docs 가 문자열, metas 가 dict 가 되어 KeyError(0) 발생).
        # 중첩/평탄 양쪽 형태를 모두 수용한다.
        def _rows(field):
            v = result.get(field) or []
            return v[0] if (isinstance(v, list) and v and isinstance(v[0], list)) else v
        docs = _rows("documents")
        metas = _rows("metadatas")
        dists = _rows("distances")
        out = []
        for i, d in enumerate(docs):
            out.append({
                "document": d or "",
                "metadata": metas[i] if i < len(metas) else {},
                "distance": dists[i] if i < len(dists) else None,
            })
        logger.info(f"[AI도메인RAG] 검색 완료 → {len(out)}건")
        return out
    except Exception as e:
        # 근본원인 추적을 위해 traceback 포함 로깅.
        logger.warning(f"[AI도메인RAG] 검색 실패: {e!r}", exc_info=True)
        return []


# ────────────────────────────────────────────────────────────────────
# 사용자가 AI 채팅으로 알려주는 운영 노하우·룰을 도메인 지식 RAG 에 저장.
# 같은 document_collection / data_type=domain_knowledge / source=user_chat 메타.
# query_domain_knowledge 가 그대로 검색하므로 다음 AI 사이클부터 즉시 반영.
# title 은 식별·중복 회피용 키, content 는 임베딩 대상 본문.
# ────────────────────────────────────────────────────────────────────
def save_domain_knowledge(title: str, content: str, *,
                          category: str = "운영노하우",
                          farm_id: Optional[str] = None,
                          house_id: Optional[str] = None,
                          tags: Optional[List[str]] = None,
                          auth_farm_id: Optional[str] = None) -> Dict[str, Any]:
    if not title or not content:
        return {"success": False, "error": "title 과 content 는 필수입니다."}

    # 세션 범위 룰(농장주 명세): 농장관리자의 저장은 자기 농장으로 자동 귀속(타 농장/
    # 전역 지정은 무시하고 강제). 시스템관리자는 지정값 허용 — farm_id='0' 은 전역
    # (모든 농장 공통) 지식으로 저장되어 전 농장 검색에 포함된다.
    _scope_note = None
    _auth = str(auth_farm_id).strip() if auth_farm_id is not None else None
    if _auth and _auth != "0":
        if farm_id is not None and str(farm_id).strip() not in ("", _auth):
            _scope_note = (f"요청한 farm_id={farm_id} 는 권한 범위 밖 — "
                           f"본인 농장(farm_id={_auth})으로 저장했습니다.")
        farm_id = _auth
    try:
        from agri_ai_core.src.chroma.collections import document_collection
        from agri_ai_core.src.chroma.operations import add_document

        coll = document_collection()
        if not coll:
            return {"success": False, "error": "document_collection 미설정"}

        # chunk_id: 사용자 정의 지식임을 표기 + 시각·UUID 단편으로 고유성 확보
        ts = time.strftime("%Y%m%d_%H%M%S")
        short = uuid.uuid4().hex[:6]
        chunk_id = f"user_knowledge_{ts}_{short}"

        # 본문에 title 도 포함시켜 검색 정확도 향상
        text = f"[{category}] {title}\n\n{content.strip()}"
        metadata = {
            "data_type": "domain_knowledge",   # query_domain_knowledge where 와 일치
            "source": "user_chat",             # 사용자 채팅 입력 표시
            "category": category,
            "title": title,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if farm_id:
            metadata["farm_id"] = str(farm_id)
        if house_id:
            metadata["house_id"] = str(house_id)
        if tags:
            metadata["tags"] = ",".join(t for t in tags if t)

        # ⚠ 임베딩 명시 생성 필수 (0벡터 저장 방지) — 미전달 시 add_document 가
        #   0벡터로 저장해 의미 검색에서 영구 누락됨. embed_fn 미주입 프로세스
        #   (독립 스크립트 등)에서도 동작하도록 embedder 직접 폴백.
        embedding = None
        try:
            from agri_ai_core.src.chroma.operations import _build_embedding_from_text
            embedding = _build_embedding_from_text(text)
            if embedding is None:
                from agri_ai_core.src.ai.embedder import embed_text
                embedding = embed_text(text)
        except Exception as _ee:
            logger.warning(f"[AI도메인RAG] 임베딩 생성 실패(0벡터 저장 — 검색 불가 위험): {_ee}")

        ok = add_document(
            collection_name=coll,
            doc_id=chunk_id,
            text=text,
            metadata=metadata,
            embedding=embedding,
        )
        if ok:
            logger.info(f"[AI도메인RAG] 사용자 입력 저장 완료 chunk={chunk_id} title=\"{title[:40]}\"")
            return {
                "success": True,
                "message": ("도메인 지식 저장 완료 — 다음 AI 제어 사이클부터 자동 참조됩니다."
                            + (f" ({_scope_note})" if _scope_note else "")),
                "chunk_id": chunk_id,
                "title": title,
            }
        return {"success": False, "error": "ChromaDB add_document 실패"}
    except Exception as e:
        logger.warning(f"[AI도메인RAG] 저장 실패 title=\"{title[:40]}\": {e}")
        return {"success": False, "error": str(e)}


# ────────────────────────────────────────────────────────────────────
# 도메인 지식 검색 결과 list 를 user prompt 한 블록 텍스트로 변환.
# ────────────────────────────────────────────────────────────────────
def format_doc_block(items: List[Dict[str, Any]]) -> str:
    if not items:
        return ""
    lines = [f"[도메인 지식 RAG — 적재 매뉴얼/논문 {len(items)}건 발췌]"]
    for i, it in enumerate(items, 1):
        m = it.get("metadata") or {}
        cat = m.get("category", "-")
        fn = m.get("file_name", "-")
        dist = it.get("distance")
        dist_s = f"{dist:.3f}" if isinstance(dist, (int, float)) else "-"
        lines.append(f"  ({i}) [{cat}] {fn} (거리={dist_s})")
        preview = (it.get("document") or "").replace('\n', ' ').strip()
        if preview:
            lines.append(f"      └ {preview[:_DOC_PREVIEW]}{'…' if len(preview) > _DOC_PREVIEW else ''}")
    return "\n".join(lines)
