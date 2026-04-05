# ══════════════════════════════════════════════════════════
# 텍스트 청킹: 문서를 의미 단위 청크로 분할하여 VectorDB에 저장.
# ══════════════════════════════════════════════════════════
import re
import traceback
from datetime import datetime

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.chroma.collections import document_collection
from agri_ai_core.src.chroma.operations import upsert_documents_with_embedding, get_documents, delete_document
from agri_ai_core.src.ai.rag.embedder import embed_text

logger = setup_logger(__name__)


# 문서를 청크로 분할
# ══════════════════════════════════════════════════════════
def chunk_document(document_content, chunk_size=1000, chunk_overlap=200):
    # 문단 단위로 분리 시도
    paragraphs = document_content.split('\n\n')
    chunks = []
    current_chunk = ""

    for paragraph in paragraphs:
        # 빈 문단 건너뛰기
        if not paragraph.strip():
            continue

        # 현재 청크에 문단 추가했을 때 크기가 청크 크기를 초과하는지 확인
        if len(current_chunk) + len(paragraph) + 2 <= chunk_size:
            if current_chunk:
                current_chunk += "\n\n"
            current_chunk += paragraph
        else:
            # 현재 청크 저장하고 새 청크 시작
            if current_chunk:
                chunks.append(current_chunk)

            # 새 문단이 너무 길면 더 작은 단위로 분할
            if len(paragraph) > chunk_size:
                # 한국어 종결어미 + 구두점 / 영문 마침표 기준 문장 분리
                sentences = re.split(
                    r'(?<=[다요죠까지음임함됨렵])[.]\s+|(?<=[?!])\s+|(?<=\.)\s+',
                    paragraph,
                )
                temp_chunk = ""

                for sentence in sentences:
                    sentence = sentence.strip()
                    if not sentence:
                        continue
                    if len(temp_chunk) + len(sentence) + 1 <= chunk_size:
                        if temp_chunk:
                            temp_chunk += " "
                        temp_chunk += sentence
                    else:
                        if temp_chunk:
                            chunks.append(temp_chunk)
                        temp_chunk = sentence

                if temp_chunk:
                    current_chunk = temp_chunk
            else:
                current_chunk = paragraph

    # 마지막 청크 저장
    if current_chunk:
        chunks.append(current_chunk)

    # 청크가 너무 적으면 단순 크기 기반 분할로 전환
    if len(chunks) < 3:
        logger.debug("문단 기반 분할 결과가 불충분하여 크기 기반 분할로 전환")
        chunks = []
        for i in range(0, len(document_content), chunk_size - chunk_overlap):
            chunk = document_content[i:i + chunk_size]
            if len(chunk) < 100:  # 너무 작은 청크는 건너뜀
                continue
            chunks.append(chunk)

    return chunks


# 문서를 청크로 나누어 벡터 DB에 저장
# ══════════════════════════════════════════════════════════
def store_document_with_chunks(document_content, document_metadata, chunk_size=1000, chunk_overlap=200):
    result = {
        "success": False,
        "chunks_count": 0,
        "error": None
    }

    try:
        # 문서를 청크로 분할
        chunks = chunk_document(document_content, chunk_size, chunk_overlap)

        # 동일 파일의 기존 청크 삭제 (중복 방지)
        file_name = document_metadata.get("file_name", "")
        if file_name:
            try:
                existing = get_documents(
                    document_collection(),
                    where={"file_name": {"$eq": file_name}},
                    include=["metadatas"]
                )
                existing_ids = existing.get("ids", []) if isinstance(existing, dict) else []
                if existing_ids:
                    delete_document(document_collection(), existing_ids)
                    logger.info(f"[청크저장] 기존 '{file_name}' 청크 {len(existing_ids)}건 삭제 (재학습)")
            except Exception as e:
                logger.warning(f"[청크저장] 기존 청크 삭제 중 오류 (무시): {e}")

        # 각 청크에 메타데이터와 임베딩 생성하여 배치 저장
        doc_id_base = file_name.replace(".", "_") if file_name else "unknown"
        success_count = 0

        batch_docs = []
        for i, chunk in enumerate(chunks):
            try:
                chunk_id = f"{doc_id_base}_{i}"

                chunk_metadata = document_metadata.copy()
                chunk_metadata.update({
                    "chunk_id": i,
                    "total_chunks": len(chunks),
                    "data_kind": "document_chunk",
                    "is_learned_flag": False,
                    "record_datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })

                # 파일명을 청크 텍스트에 포함하여 임베딩 (파일명 기반 검색 지원)
                chunk_text = f"[파일: {file_name}]\n{chunk}" if file_name else chunk

                embedding = embed_text(chunk_text)
                if not embedding:
                    logger.warning(f"[청크저장] 청크 {chunk_id} 임베딩 실패 → 스킵")
                    continue

                batch_docs.append({
                    "doc_id": chunk_id,
                    "text": chunk_text,
                    "metadata": chunk_metadata,
                    "embedding": embedding,
                })

            except Exception as e:
                logger.error(f"청크 임베딩 중 예외 발생: {e}")
                logger.error(traceback.format_exc())

        # 배치 upsert
        if batch_docs:
            try:
                batch_result = upsert_documents_with_embedding(document_collection(), batch_docs)
                if isinstance(batch_result, dict) and batch_result.get("success"):
                    reported_count = batch_result.get("count", len(batch_docs))
                    if reported_count != len(batch_docs):
                        logger.warning(
                            f"[청크저장] 배치 upsert 부분 성공: "
                            f"요청={len(batch_docs)}건, 처리={reported_count}건"
                        )
                    success_count = reported_count
                    logger.info(f"[청크저장] 배치 upsert 성공: {success_count}건 (임베딩 포함)")
                else:
                    error = batch_result.get("error", "알 수 없는 오류") if isinstance(batch_result, dict) else str(batch_result)
                    logger.warning(f"[청크저장] 배치 upsert 실패: {error}")
            except Exception as e:
                logger.error(f"[청크저장] 배치 upsert 예외: {e}")
                logger.error(traceback.format_exc())

        result["success"] = success_count > 0
        result["chunks_count"] = success_count
        logger.debug(f"문서 '{document_metadata.get('file_name', 'doc')}' {success_count}개 청크로 저장 완료")

        return result

    except Exception as e:
        logger.error(f"문서 청크 저장 중 오류: {e}")
        logger.error(traceback.format_exc())
        result["error"] = str(e)
        return result
