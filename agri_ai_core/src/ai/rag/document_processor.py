# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 문서 처리 파이프라인 모듈
# PDF, 텍스트 등 다양한 형식의 문서를 파싱하고 처리하여
# LLM이 활용할 수 있는 형태로 변환합니다.
# --->
# detect_document_type: 문서 유형 및 작물명 감지
# llm_document_process: 문서를 처리하여 ChromaDB에 저장
# process_attached_files: 첨부 파일들을 처리하고 학습
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
from datetime import datetime

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.chroma.collections import optimal_collection, document_collection
from agri_ai_core.src.chroma.operations import upsert_collection_data
from agri_ai_core.src.ai.rag.chunker import store_document_with_chunks

logger = setup_logger(__name__)

# 문서 유형 한글 라벨
DOC_TYPE_LABELS = {
    "crop_info": "작물 정보",
    "disease_info": "병해충 정보",
    "general": "일반 문서",
}


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 대화 메시지 목록 → RAG 저장용 텍스트 변환 (공통)
# React(app.py)와 Reflex(state.py) 모두에서 동일하게 호출
# Args:
#   messages: [{"role": "user"|"assistant", "content": str}, ...]  (dict 또는 객체)
#   farm_name: 농장명
#   house_name: 재배사명
# Returns:
#   str: 변환된 텍스트
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def messages_to_text(messages, farm_name=None, house_name=None):
    lines = []
    lines.append(f"[농장: {farm_name or '-'}, 재배사: {house_name or '-'}]")
    lines.append(f"[대화 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    lines.append("")

    for msg in messages:
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "")
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
        role_label = "사용자" if role == "user" else "AI"
        lines.append(f"[{role_label}] {content}")
        lines.append("")

    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# RAG 저장 결과 → 사용자 안내 메시지 포맷팅 (공통)
# Args:
#   result: llm_document_process() 반환값
#   message_count: 저장된 메시지 수
# Returns:
#   tuple: (success: bool, message: str)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def format_rag_save_result(result, message_count=0):
    if result.get("success"):
        chunks = result.get("chunks_stored", 0)
        doc_type = result.get("document_type", "general")
        crop_name = result.get("crop_name", "")
        structured = result.get("structured_data_stored", False)
        timestamp = result.get("timestamp", "")

        doc_type_label = DOC_TYPE_LABELS.get(doc_type, doc_type)

        summary = f"RAG 저장 완료 — 대화 내용이 VectorDB에 저장되었습니다.\n"
        summary += f"저장 일시: {timestamp}\n\n"
        summary += f"  대화 메시지: {message_count}개\n"
        summary += f"  저장된 청크: {chunks}개\n"
        summary += f"  문서 유형: {doc_type_label}\n"
        if crop_name:
            summary += f"  감지된 작물: {crop_name}\n"
        if structured:
            summary += f"  구조화 데이터: 저장 완료\n"
        summary += "\n저장된 대화 내용으로 질문해보세요!"
        return True, summary
    else:
        error = result.get("error", "알 수 없는 오류")
        return False, f"RAG 저장 실패: {error}"


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 문서 유형 감지
# --->
# 문서 유형 및 작물명 감지
# Args:
# document_content: 문서 내용
# Returns:
# tuple: (document_type, crop_name)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def detect_document_type(document_content):
    document_type = 'general'
    crop_name = None

    # 문서 내용 기반 유형 분류
    first_1000 = document_content[:1000]
    if "상황버섯" in first_1000:
        document_type = 'crop_info'
        crop_name = "상황버섯"
    elif "작약" in first_1000:
        document_type = 'crop_info'
        crop_name = "작약"
    elif "쇠무릎" in first_1000:
        document_type = 'crop_info'
        crop_name = "쇠무릎"
    elif "특용작물" in first_1000 or "약용작물" in first_1000:
        document_type = 'crop_info'
    elif any(term in document_content for term in ["병해충", "병원균", "방제", "흰가루병", "탄저병"]):
        document_type = 'disease_info'

    return document_type, crop_name


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 문서 처리하여 ChromaDB에 저장
# --->
# 문서를 처리하여 ChromaDB에 저장
# Args:
# file_path: 파일 경로
# text_content: 텍스트 내용 (직접 제공시)
# farm_id: 농장 ID
# Returns:
# dict: 처리 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def llm_document_process(file_path=None, text_content=None, farm_id=None):
    result = {
        "success": False,
        "chunks_stored": 0,
        "structured_data_stored": False,
        "file_path": file_path,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    try:
        # 문서 내용 획득
        if text_content:
            # 직접 제공된 텍스트 사용
            document_content = text_content
            filename = os.path.basename(file_path) if file_path else "direct_text"
            file_size = len(text_content)
            logger.debug(f"직접 제공된 텍스트 처리 시작: {filename}, 크기: {file_size} 바이트")
        else:
            # 파일 존재 여부 확인
            if not os.path.exists(file_path):
                logger.error(f"파일이 존재하지 않습니다: {file_path}")
                result["error"] = "파일이 존재하지 않습니다"
                return result

            # 파일 기본 정보 수집
            filename = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)

            # 파일 읽기
            with open(file_path, 'r', encoding='utf-8') as f:
                document_content = f.read()

            logger.debug(f"문서 로드 완료: {filename}, 크기: {file_size/1024:.2f}KB")

        # 문서 유형 감지
        document_type, crop_name = detect_document_type(document_content)

        # 결과에 문서 유형과 작물명 추가
        result["document_type"] = document_type
        if crop_name:
            result["crop_name"] = crop_name

        logger.debug(f"문서 유형 감지: {document_type}" + (f", 작물: {crop_name}" if crop_name else ""))

        # 메타데이터 구성
        metadata = {
            "document_type": document_type,
            "file_name": filename,
            "file_extension": os.path.splitext(filename)[1].lower() if filename else "",
            "file_size": file_size,
            "processing_date": datetime.now().strftime("%Y-%m-%d"),
            "processing_time": datetime.now().strftime("%H:%M:%S"),
            "learning_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        if farm_id is not None:
            metadata["farm_id"] = farm_id

        if crop_name:
            metadata["crop_name"] = crop_name

        # 1. 원문을 청크로 나누어 저장
        chunks_result = store_document_with_chunks(document_content, metadata)
        result["chunks_stored"] = chunks_result["chunks_count"] if isinstance(chunks_result, dict) and "chunks_count" in chunks_result else 0

        if isinstance(chunks_result, dict) and not chunks_result.get("success", False):
            logger.warning(f"문서 청크 저장 실패: {chunks_result.get('error', '알 수 없는 오류')}")

        # 2. 구조화된 정보 추출 및 저장 (extract_structured_information이 필요하면 별도 import)
        # 여기서는 기본 메타데이터만 저장
        try:
            # 안정적 ID: 파일명 기반 (동일 파일 재학습시 upsert)
            doc_id = f"doc_{filename.replace('.', '_')}"
            optimal_metadata = metadata.copy()
            optimal_metadata.update({
                "data_type": "structured_document",
                "is_manual": True,
                "is_learned_flag": True,
                "record_datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            logger.debug(f"생육 최적 집계 데이터 생성 -> {doc_id}")
            upsert_collection_data(
                "update_optimal_collection",
                optimal_collection(),
                doc_id,
                "최종 생성 시간",
                optimal_metadata
            )

            logger.debug(f"문서 학습 데이터 생성 -> {doc_id}")
            upsert_collection_data(
                "llm_document_process",
                document_collection(),
                doc_id,
                document_content[:5000],  # 원문 일부 저장
                metadata
            )

            result["structured_data_stored"] = True
            logger.debug(f"구조화된 정보 저장 완료: {doc_id}")
        except Exception as e:
            logger.warning(f"구조화된 정보 저장 중 오류: {e}")

        # 성공 처리
        result["success"] = True
        result["message"] = f"문서 처리 및 저장 완료: {filename}"

        logger.debug(f"문서 처리 완료: {filename}")
        return result

    except Exception as e:
        logger.error(f"문서 처리 중 오류: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        result["error"] = str(e)
        return result


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 첨부 파일 처리
# --->
# 첨부 파일들을 처리하고 학습
# Args:
# file_paths: 파일 정보 목록
# farm_id: 농장 ID
# Returns:
# str: 처리 결과 메시지
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def process_attached_files(file_paths, farm_id):
    if not file_paths:
        return "처리할 첨부 파일이 없습니다."

    total_files = len(file_paths)
    success_count = 0
    failed_files = []
    results_summary = []

    logger.debug(f"첨부 파일 {total_files}개 처리 시작")

    for file_info in file_paths:
        file_path = file_info["path"]
        filename = file_info["filename"]

        try:
            logger.debug(f"파일 처리 시작: {filename}")

            # 지원하는 파일 형식 확인
            file_ext = os.path.splitext(filename)[1].lower()
            if file_ext not in ['.txt', '.md', '.csv', '.json']:
                msg = f"파일 '{filename}'은 지원하지 않는 형식입니다. txt, md, csv, json 파일만 처리 가능합니다."
                logger.warning(msg)
                failed_files.append({"filename": filename, "error": "지원하지 않는 파일 형식"})
                results_summary.append(msg)
                continue

            result = llm_document_process(file_path=file_path, farm_id=farm_id)

            if result["success"]:
                success_count += 1
                chunks_count = result.get("chunks_stored", 0)
                qa_count = result.get("qa_pairs_generated", 0)
                crop_name = result.get("crop_name", "")
                doc_type = result.get("document_type", "general")
                structured = result.get("structured_data_stored", False)

                # 문서 유형 한글 변환
                doc_type_labels = {
                    "crop_info": "작물 정보",
                    "disease_info": "병해충 정보",
                    "general": "일반 문서",
                }
                doc_type_label = doc_type_labels.get(doc_type, doc_type)

                msg = f"✓ '{filename}' → {chunks_count}개 청크 저장"
                msg += f" | 문서유형: {doc_type_label}"
                if crop_name:
                    msg += f" | 작물: {crop_name}"
                if structured:
                    msg += f" | 구조화 데이터 저장 완료"
                if qa_count > 0:
                    msg += f" | {qa_count}개 QA 쌍 생성"

                logger.debug(msg)
                results_summary.append(msg)
            else:
                error = result.get("error", "알 수 없는 오류")
                msg = f"파일 '{filename}' 처리 실패: {error}"
                logger.error(msg)
                failed_files.append({"filename": filename, "error": error})
                results_summary.append(msg)

        except Exception as e:
            msg = f"파일 '{filename}' 처리 중 예외 발생: {str(e)}"
            logger.error(msg)
            import traceback
            logger.error(traceback.format_exc())
            failed_files.append({"filename": filename, "error": str(e)})
            results_summary.append(msg)

    # 결과 메시지 생성
    learning_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if success_count == total_files:
        result_message = f"📋 RAG 수행 완료 — 파일 {total_files}개 모두 VectorDB에 저장되었습니다.\n"
    else:
        result_message = f"📋 RAG 수행 완료 — 파일 {total_files}개 중 {success_count}개 성공, {len(failed_files)}개 실패\n"
    result_message += f"⏱ 학습 일시: {learning_datetime}\n\n"

    # 상세 결과 추가
    for i, summary in enumerate(results_summary):
        result_message += f"  {i+1}. {summary}\n"

    result_message += "\n처리된 파일의 내용으로 질문해보세요!"

    logger.debug(f"첨부 파일 처리 완료: {success_count}/{total_files} 성공")
    return result_message
