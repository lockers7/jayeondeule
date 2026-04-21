# ════════════════════════════════════════════════════════════════════
# ChromaDB 데이터 작업 계층 — 문서 저장/조회/삭제/업서트 + 벡터 유사도 검색.
# 임베딩은 필요 시 자동 생성되며, ID/문서/메타데이터는 JSON-safe 로 정제.
# --->
# _http_post                       : ChromaDB POST 통신 래퍼
# set_embed_fn                     : 상위 계층의 임베딩 함수 주입 (의존성 역전)
# _build_embedding_from_text       : 텍스트 → 임베딩 벡터 (embedder 호출)
# add_document                     : 단일 문서 추가 (임베딩 자동 생성)
# get_documents                    : ID 또는 where 조건으로 문서 조회
# delete_document                  : ID 리스트로 문서 삭제
# upsert_collection_data           : 저수준 컬렉션 데이터 업서트 (여러 문서 일괄)
# upsert_documents_with_embedding  : 텍스트 → 임베딩 → 업서트 통합
# query_documents                  : 벡터 유사도 기반 Top-K 검색
# ════════════════════════════════════════════════════════════════════
import os
import time
import traceback

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.utils.validators import is_true
from agri_ai_core.src.utils.http_client import http_json_request
from agri_ai_core.src.chroma.config import CHROMA_API_BASE
from agri_ai_core.src.chroma.client import (
    get_collection_id_from_name,
    get_collection
)
from agri_ai_core.src.chroma.utils import (
    _embedding_dim,
    _sanitize_for_json,
    prepare_metadata_for_chroma,
    clean_metadata,
    restore_metadata_from_chroma,
)

logger = setup_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# ChromaDB POST 통신 래퍼. (status_code, data, raw_text) 반환.
# ────────────────────────────────────────────────────────────────────
def _http_post(url: str, payload: dict, timeout: int = 30):
    logger.debug(f"[ChromaDB-POST] url={url}, payload_keys={list(payload.keys()) if isinstance(payload, dict) else type(payload)}, timeout={timeout}")
    status_code, data, text = http_json_request(
        method="POST",
        url=url,
        json_body=payload,
        timeout=timeout,
    )
    logger.debug(f"[ChromaDB-POST] 응답: status={status_code}, data_type={type(data).__name__}")
    return status_code, data, text


_AUTO_EMBED_ON_UPSERT = is_true(os.getenv("AUTO_EMBED_ON_UPSERT", "true"))

# 임베딩 함수(옵션). 상위 계층(startup.py)에서 주입.
# None이면 자동 임베딩은 비활성 — chroma 패키지가 AI 계층을 역참조하지 않도록.
# 시그니처: (text: str) -> list[float] | None
_embed_fn = None


# ────────────────────────────────────────────────────────────────────
# 상위 계층(startup.py 등)에서 임베딩 함수를 주입 (의존성 역전).
# ────────────────────────────────────────────────────────────────────
def set_embed_fn(fn) -> None:
    global _embed_fn
    _embed_fn = fn


# ────────────────────────────────────────────────────────────────────
# 텍스트 → 임베딩 벡터 변환. 자동 임베딩 비활성/주입 미설정/실패 시 None.
# ────────────────────────────────────────────────────────────────────
def _build_embedding_from_text(text):
    if not _AUTO_EMBED_ON_UPSERT or not text or _embed_fn is None:
        return None
    try:
        embedding = _embed_fn(str(text))
        if isinstance(embedding, list) and len(embedding) == _embedding_dim():
            return embedding
    except Exception as e:
        logger.debug(f"[임베딩] 자동 임베딩 생성 실패: {e}")
    return None


# ────────────────────────────────────────────────────────────────────
# 단일 문서 추가. embedding 미지정 시 제로벡터 사용 (실서비스에선 주입 권장).
# ────────────────────────────────────────────────────────────────────
def add_document(collection_name, doc_id, text, metadata, embedding=None):
    logger.debug(f" add_document: collection_name: {collection_name}, doc_id: {doc_id}")

    collection_id = get_collection_id_from_name(collection_name)
    if not collection_id:
        return {"error": "컬렉션 ID 조회 실패"}

    if metadata is None:
        metadata = {}
    else:
        metadata = prepare_metadata_for_chroma(metadata)

    metadata["doc_id"] = doc_id

    if embedding is None:
        embedding = [0.0] * _embedding_dim()
    if not isinstance(embedding, list) or len(embedding) != _embedding_dim():
        return {"error": "임베딩 오류"}

    url = f"{CHROMA_API_BASE}/collections/{collection_id}/add"
    payload = {
        "ids": [doc_id],
        "documents": [text],
        "metadatas": [metadata],
        "embeddings": [embedding]
    }

    status_code, _, text = _http_post(url, payload, timeout=20)
    if status_code in [200, 201]:
        logger.info(f"[add_document] 문서 추가 성공: doc_id={doc_id}")
        return {"success": True}
    else:
        return {"error": f"{status_code}: {text}"}


# ────────────────────────────────────────────────────────────────────
# 문서 조회 — ids 또는 where 조건으로 복수 문서 가져오기.
# 메타데이터의 _is_json 플래그를 자동 복원하여 원형 dict/list 반환.
# ────────────────────────────────────────────────────────────────────
def get_documents(collection_name, ids=None, where=None, limit=None, offset=None, sort=None, where_document=None, include=None):
    collection_id = get_collection_id_from_name(collection_name)
    if not collection_id:
        return {"error": "컬렉션 ID를 찾을 수 없습니다."}

    if ids is not None and isinstance(ids, str):
        ids = [ids]

    payload = {
        "include": include or ["documents", "metadatas"]
    }

    if ids:
        payload["ids"] = ids
    if where:
        payload["where"] = _sanitize_for_json(where)
    if where_document:
        payload["where_document"] = _sanitize_for_json(where_document)
    if limit is not None:
        payload["limit"] = limit
    if offset is not None:
        payload["offset"] = offset
    if sort is not None:
        payload["sort"] = sort

    try:
        url = f"{CHROMA_API_BASE}/collections/{collection_id}/get"
        status_code, result, text = _http_post(url, payload, timeout=20)
        if status_code != 200:
            return {"error": f"{status_code}: {text}"}
        if not isinstance(result, dict):
            return {"error": "Chroma get 응답 파싱 실패"}

        # ────────────────────────────────────────────────────────────
        # 단일 쿼리 결과의 [[...]] 중첩을 [...] 로 평탄화.
        # ────────────────────────────────────────────────────────────
        def flatten(field_name):
            value = result.get(field_name)
            if isinstance(value, list) and len(value) == 1 and isinstance(value[0], list):
                return value[0]
            return value or []

        documents = flatten("documents")
        raw_metadatas = flatten("metadatas")
        returned_ids = flatten("ids")

        restored_metadatas = []
        for raw_metadata in raw_metadatas:
            if isinstance(raw_metadata, dict):
                restored_metadatas.append(restore_metadata_from_chroma(raw_metadata))
            else:
                restored_metadatas.append(raw_metadata)

        return {
            "documents": documents,
            "metadatas": restored_metadatas,
            "ids": returned_ids
        }

    except Exception as e:
        logger.error(f"[get_documents] 예외 발생: {e}")
        logger.error(traceback.format_exc())
        return {"error": str(e)}


# ────────────────────────────────────────────────────────────────────
# 문서 삭제 — ID 리스트(단일 str 도 허용)로 컬렉션에서 제거.
# ────────────────────────────────────────────────────────────────────
def delete_document(collection_name, ids):
    logger.debug(f" delete_document: collection_name: {collection_name}, ids: {ids}")

    if isinstance(ids, str):
        ids = [ids]
    elif isinstance(ids, list):
        if len(ids) == 1 and isinstance(ids[0], list):
            ids = ids[0]
    else:
        return {"error": f"delete_document: 예상치 못한 ids 타입: {type(ids)}"}

    collection_id = get_collection_id_from_name(collection_name)
    if not collection_id:
        return {"error": "컬렉션 ID 조회 실패"}

    url = f"{CHROMA_API_BASE}/collections/{collection_id}/delete"
    payload = {"ids": ids}

    try:
        status_code, _, text = _http_post(url, payload, timeout=20)
        if status_code in [200, 204]:
            return {"success": True}
        return {"error": f"{status_code}: {text}"}
    except Exception as e:
        return {"error": str(e)}


# ────────────────────────────────────────────────────────────────────
# 저수준 컬렉션 업서트 라우터 — document 형식(str/list[str]/list[dict])별
# 정규화 + delete-then-add 또는 upsert_documents_with_embedding 으로 위임.
# ────────────────────────────────────────────────────────────────────
def upsert_collection_data(calledby, collection, doc_id, document, metadata):
    logger.info(f" upsert_collection_data: calledby: {calledby}, collection: {collection}, doc_id: {doc_id}")

    collection_name = collection if isinstance(collection, str) else str(collection)

    if document is None:
        return {"error": "문서가 제공되지 않았습니다"}

    if isinstance(document, list) and all(isinstance(d, dict) for d in document):
        valid_docs = []
        for doc in document:
            if "doc_id" in doc and "text" in doc:
                meta = clean_metadata(doc.get("metadata", {}))
                meta["doc_id"] = doc["doc_id"]
                valid_docs.append({
                    "doc_id": doc["doc_id"],
                    "text": doc["text"],
                    "metadata": meta
                })
        if not valid_docs:
            return {"error": "문서 형식 오류 - list 내 유효 문서 없음"}
        return upsert_documents_with_embedding(collection_name, valid_docs)

    elif isinstance(document, str):
        try:
            check = get_documents(collection_name, where={"doc_id": {"$eq": doc_id}}, limit=1)
            exists = isinstance(check, dict) and check.get("documents")
            if exists:
                delete_result = delete_document(collection_name, ids=[doc_id])
                if isinstance(delete_result, dict) and delete_result.get("error"):
                    logger.error(f"[{calledby}] 기존 문서 삭제 실패 - doc_id={doc_id}, error: {delete_result['error']}")
                    return "failed"

            embedding = _build_embedding_from_text(document)
            result = add_document(collection_name, doc_id, text=document, metadata=metadata, embedding=embedding)
            if isinstance(result, dict) and not result.get("error"):
                return "added" if not exists else "updated"
            else:
                logger.error(f"[{calledby}] add_document 실패 - doc_id={doc_id}, error: {result.get('error')}")
                return "failed"
        except Exception as e:
            logger.error(f"[{calledby}] 예외 발생 - doc_id={doc_id}, error: {e}")
            logger.error(traceback.format_exc())
            return "failed"

    elif isinstance(document, list) and all(isinstance(d, str) for d in document):
        if not (isinstance(doc_id, list) and isinstance(metadata, list)):
            return {"error": "doc_id와 metadata는 반드시 리스트여야 합니다"}

        if not (len(document) == len(doc_id) == len(metadata)):
            return {"error": "문서, ID, 메타데이터 길이 불일치"}

        valid_docs = []
        for i in range(len(document)):
            meta = clean_metadata(metadata[i])
            meta["doc_id"] = doc_id[i]
            valid_docs.append({
                "doc_id": doc_id[i],
                "text": document[i],
                "metadata": meta,
                "embedding": _build_embedding_from_text(document[i]),
            })
        return upsert_documents_with_embedding(collection_name, valid_docs)

    else:
        return {"error": "문서 형식 오류 - str, list[str], list[dict] 중 하나여야 함"}


# ────────────────────────────────────────────────────────────────────
# 복수 문서 업서트 (임베딩 포함). docs 의 각 항목은 doc_id/text/metadata
# /embedding(옵션) 키를 가져야 하며, 임베딩 누락 시 자동 생성/제로벡터 폴백.
# ────────────────────────────────────────────────────────────────────
def upsert_documents_with_embedding(collection_name, docs):
    logger.info(f" upsert_documents_with_embedding: collection_name: {collection_name}")

    collection_id = get_collection_id_from_name(collection_name)
    if not collection_id:
        return {"error": "컬렉션 ID 조회 실패"}

    ids, texts, metadatas, embeddings = [], [], [], []

    for doc in docs:
        doc_id = doc["doc_id"]
        text = doc["text"]
        raw_metadata = doc.get("metadata", {})

        metadata = prepare_metadata_for_chroma(raw_metadata)

        embedding = doc.get("embedding")
        if not embedding:
            embedding = _build_embedding_from_text(text)
        if not isinstance(embedding, list) or len(embedding) != _embedding_dim():
            logger.warning(f"[upsert_documents_with_embedding] 임베딩 형식 오류 -> 제로벡터 사용: {doc_id}")
            embedding = [0.0] * _embedding_dim()

        ids.append(doc_id)
        texts.append(text)
        metadatas.append(metadata)
        embeddings.append(embedding)

    logger.debug(f"[upsert_documents_with_embedding] upsert 대상 문서 수: {len(ids)}")

    if not ids:
        return {"error": "업서트할 유효한 문서 없음"}

    payload = {
        "ids": ids,
        "documents": texts,
        "metadatas": metadatas,
        "embeddings": embeddings
    }

    try:
        url = f"{CHROMA_API_BASE}/collections/{collection_id}/upsert"
        status_code, _, text = _http_post(url, payload, timeout=30)
        if status_code in [200, 201]:
            return {"success": True, "count": len(ids)}
        return {"error": f"{status_code}: {text}"}
    except Exception as e:
        return {"error": str(e)}


# ────────────────────────────────────────────────────────────────────
# 벡터 유사도 기반 Top-K 검색. 재시도 2회·타임아웃 10초.
# query_embeddings 단일 리스트도 자동 [[...]] 형태로 변환.
# ────────────────────────────────────────────────────────────────────
def query_documents(collection_name, query_embeddings=None, n_results=5, where=None, include=None, where_document=None):
    try:
        collection = get_collection(collection_name)
        if "error" in collection:
            return collection

        collection_id = collection.get("id")
        if not collection_id:
            return {"error": f"컬렉션 ID를 가져올 수 없습니다: {collection_name}"}

        if query_embeddings is None:
            return {"error": "query_embeddings 는 필수입니다."}

        if isinstance(query_embeddings, list) and query_embeddings and isinstance(query_embeddings[0], (int, float)):
            query_embeddings = [query_embeddings]

        url = f"{CHROMA_API_BASE}/collections/{collection_id}/query"

        payload = {
            "n_results": n_results,
            "query_embeddings": query_embeddings,
            "include": include or ["metadatas", "documents", "distances"]
        }
        if where:
            sanitized_where = _sanitize_for_json(where)
            payload["where"] = sanitized_where
        if where_document:
            payload["where_document"] = _sanitize_for_json(where_document)

        # ────────────────────────────────────────────────────────────
        # 단일 쿼리 결과의 [[...]] 중첩을 [...] 로 평탄화 (내부 헬퍼).
        # ────────────────────────────────────────────────────────────
        def _flatten(result_dict, field_name):
            value = result_dict.get(field_name)
            if isinstance(value, list) and len(value) == 1 and isinstance(value[0], list):
                return value[0]
            return value or []

        _RETRY_EMPTY = {"matches": [], "ids": [], "documents": [], "metadatas": [], "distances": []}

        # 재시도 2회, 타임아웃 10초 — 기존 30초x3회(=90초 블로킹)에서 10초x2회(=20초)로 축소
        for retry in range(2):
            try:
                status_code, result, text = _http_post(url, payload, timeout=10)
                if status_code == 200:
                    if not isinstance(result, dict):
                        logger.error("[query_documents] 응답 JSON 파싱 실패")
                        time.sleep(1.5 ** retry)
                        continue

                    restored_metadatas = [
                        restore_metadata_from_chroma(m) if isinstance(m, dict) else m
                        for m in _flatten(result, "metadatas")
                    ]
                    result["metadatas"] = restored_metadatas

                    documents = _flatten(result, "documents")
                    result["documents"] = documents

                    ids = _flatten(result, "ids")
                    result["ids"] = ids

                    distances = _flatten(result, "distances")
                    result["distances"] = distances

                    matches = []
                    for idx, doc_id in enumerate(ids):
                        match = {
                            "id": doc_id,
                            "metadata": restored_metadatas[idx] if idx < len(restored_metadatas) else {},
                        }
                        if idx < len(documents):
                            match["document"] = documents[idx]
                        if idx < len(distances):
                            match["distance"] = distances[idx]
                        matches.append(match)
                    result["matches"] = matches

                    logger.info(f"[query_documents] '{collection_name}' 검색 성공: {len(ids)}건")
                    return result
                else:
                    logger.error(f"[query_documents] 쿼리 실패: {status_code} - {text}")
                    time.sleep(1.5 ** retry)
            except Exception as e:
                logger.error(f"[query_documents] 요청 예외 발생: {e}")
                time.sleep(1.5 ** retry)

        logger.error("[query_documents] 최대 재시도 초과")
        return dict(_RETRY_EMPTY)

    except Exception as e:
        logger.error(f"[query_documents] 예외 발생: {e}")
        logger.error(traceback.format_exc())
        return {"matches": [], "ids": [], "documents": [], "metadatas": [], "distances": []}
