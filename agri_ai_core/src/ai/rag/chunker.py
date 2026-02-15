# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 텍스트 청킹 모듈
# 긴 텍스트를 의미 단위로 분할하여 임베딩에 적합한 크기의
# 청크로 나누는 다양한 청킹 전략을 제공합니다.
# --->
# chunk_document: 문서를 청크로 분할
# store_document_with_chunks: 문서를 청크로 나누어 벡터 DB에 저장
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import traceback
from datetime import datetime

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.chroma.collections import document_collection
from agri_ai_core.src.chroma.operations import upsert_collection_data

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 문서를 청크로 분할
# --->
# 문서를 청크로 분할
# Args:
# document_content: 문서 내용
# chunk_size: 청크 크기
# chunk_overlap: 청크 오버랩
# Returns:
# list: 청크 목록
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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
                sentences = paragraph.split('. ')
                temp_chunk = ""

                for sentence in sentences:
                    if len(temp_chunk) + len(sentence) + 2 <= chunk_size:
                        if temp_chunk:
                            temp_chunk += ". "
                        temp_chunk += sentence
                    else:
                        if temp_chunk:
                            chunks.append(temp_chunk + ".")
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 문서를 청크로 나누어 저장
# --->
# 문서를 청크로 나누어 벡터 DB에 저장
# Args:
# document_content: 문서 내용
# document_metadata: 문서 메타데이터
# chunk_size: 청크 크기
# chunk_overlap: 청크 오버랩
# Returns:
# dict: 저장 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def store_document_with_chunks(document_content, document_metadata, chunk_size=1000, chunk_overlap=200):
    result = {
        "success": False,
        "chunks_count": 0,
        "error": None
    }

    try:
        # 문서를 청크로 분할
        chunks = chunk_document(document_content, chunk_size, chunk_overlap)

        # 각 청크에 메타데이터와 함께 저장
        success_count = 0

        for i, chunk in enumerate(chunks):
            try:
                doc_id_base = document_metadata.get("file_name", "").replace(".", "_")
                chunk_id = f"{doc_id_base}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{i}"

                chunk_metadata = document_metadata.copy()
                chunk_metadata.update({
                    "chunk_id": i,
                    "total_chunks": len(chunks),
                    "data_kind": "document_chunk",
                    "is_learned_flag": False,
                    "record_datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })

                status = upsert_collection_data(
                    calledby="save_document_chunks",
                    collection=document_collection(),
                    doc_id=chunk_id,
                    document=chunk,
                    metadata=chunk_metadata
                )
                if status in ["added", "updated"]:
                    success_count += 1
                else:
                    logger.warning(f"청크 저장 실패: {chunk_id} - status: {status}")

            except Exception as e:
                logger.error(f"청크 저장 중 예외 발생: {e}")
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
