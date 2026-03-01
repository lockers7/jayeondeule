# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ChromaDB 데이터 작업 모듈
# 벡터 임베딩 추가, 유사도 검색, 데이터 업데이트/삭제 등
# 실제 데이터 작업을 수행하는 함수들을 제공합니다.
# --->
# _http_post: ChromaDB REST API POST 요청
# _build_embedding_from_text: 텍스트로부터 임베딩 벡터 생성
# add_document: 문서 추가 (단일 문서)
# get_documents: 문서 읽기 (복수 문서)
# delete_document: 문서 삭제
# upsert_collection_data: 문서 업서트 (있으면 업데이트, 없으면 추가)
# upsert_documents_with_embedding: 복수 문서 업서트 (임베딩 포함)
# query_documents: 벡터 검색
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import time
import traceback

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.mcp_client import mcp_http_request
from agri_ai_core.src.utils.validators import is_true
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


def _http_post(url: str, payload: dict, timeout: int = 30):
    return mcp_http_request(
        method="POST",
        url=url,
        json_body=payload,
        timeout=timeout,
    )


_AUTO_EMBED_ON_UPSERT = is_true(os.getenv("AUTO_EMBED_ON_UPSERT", "true"))


def _build_embedding_from_text(text):
    if not _AUTO_EMBED_ON_UPSERT:
        return None
    if not text:
        return None
    try:
        from agri_ai_core.src.ai.rag.embedder import embed_text
        embedding = embed_text(str(text))
        if isinstance(embedding, list) and len(embedding) == _embedding_dim():
            return embedding
    except Exception as e:
        logger.debug(f"[임베딩] 자동 임베딩 생성 실패: {e}")
    return None


#
# Returns:
#     dict: 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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
        logger.debug(f"[add_document] 문서 추가 성공: doc_id={doc_id}")
        return {"success": True}
    else:
        return {"error": f"{status_code}: {text}"}


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 문서 읽기 (복수 문서)
# 문서 조회
#
# Args:
#     collection_name: 컬렉션 이름
#     ids: 문서 ID 목록
#     where: 필터 조건
#     limit: 최대 결과 수
#     offset: 시작 위치
#     sort: 정렬 조건
#     where_document: 문서 필터
#     include: 포함할 필드
#
# Returns:
#     dict: 조회 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 문서 삭제
# 문서 삭제
#
# Args:
#     collection_name: 컬렉션 이름
#     ids: 삭제할 문서 ID 또는 ID 목록
#
# Returns:
#     dict: 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 문서 업서트 (있으면 업데이트, 없으면 추가)
# 문서 업서트
#
# Args:
#     calledby: 호출자 정보
#     collection: 컬렉션 이름
#     doc_id: 문서 ID
#     document: 문서 내용
#     metadata: 메타데이터
#
# Returns:
#     str: 결과 ("added", "updated", "failed")
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 복수 문서 업서트 (임베딩 포함)
# 복수 문서 업서트 (임베딩 포함)
#
# Args:
#     collection_name: 컬렉션 이름
#     docs: 문서 목록
#
# Returns:
#     dict: 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 벡터 검색
# 벡터 검색
#
# Args:
#     collection_name: 컬렉션 이름
#     query_embeddings: 쿼리 임베딩
#     n_results: 결과 수
#     where: 필터 조건
#     include: 포함할 필드
#     where_document: 문서 필터
#
# Returns:
#     dict: 검색 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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

        def _flatten(result_dict, field_name):
            value = result_dict.get(field_name)
            if isinstance(value, list) and len(value) == 1 and isinstance(value[0], list):
                return value[0]
            return value or []

        _RETRY_EMPTY = {"matches": [], "ids": [], "documents": [], "metadatas": [], "distances": []}

        for retry in range(3):
            try:
                status_code, result, text = _http_post(url, payload, timeout=30)
                if status_code == 200:
                    if not isinstance(result, dict):
                        logger.warning("[query_documents] 응답 JSON 파싱 실패")
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
                    logger.warning(f"[query_documents] 쿼리 실패: {status_code} - {text}")
                    time.sleep(1.5 ** retry)
            except Exception as e:
                logger.warning(f"[query_documents] 요청 예외 발생: {e}")
                time.sleep(1.5 ** retry)

        logger.warning("[query_documents] 최대 재시도 초과")
        return dict(_RETRY_EMPTY)

    except Exception as e:
        logger.error(f"[query_documents] 예외 발생: {e}")
        logger.error(traceback.format_exc())
        return {"matches": [], "ids": [], "documents": [], "metadatas": [], "distances": []}
