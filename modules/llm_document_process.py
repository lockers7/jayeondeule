import os
import sys
sys.path.append("/workspace/llm")
import json

from datetime import datetime

import config                  as cfg
import modules.chroma_rest_api as cra

from modules.chorma_handler      import store_document_with_chunks
from modules.llm_rag_analysis    import extract_structured_information
from modules.llm_rag_training    import generate_crop_qa_pairs, store_crop_qa_pairs
from modules.llm_query_analyzer  import analyze_query_unified
from modules.llm_processor       import get_llm_response

from modules.log_handler      import setup_logger
logger = setup_logger(__name__)

# ---------------------------------------------------------
# 문서를 처리하여 ChromaDB에 저장하는 함수
# ---------------------------------------------------------
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
            filename = os.path.basename(file_path)
            file_size = len(text_content)
            logger.info(f"직접 제공된 텍스트 처리 시작: {filename}, 크기: {file_size} 바이트")
        else:
            # 파일 존재 여부 확인
            if not os.path.exists(file_path):
                logger.error(f"파일이 존재하지 않습니다: {file_path}")
                result["error"] = "파일이 존재하지 않습니다"
                return result
            
            # 파일 기본 정보 수집
            filename = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            file_ext = os.path.splitext(filename)[1].lower()
            
            # 파일 읽기
            with open(file_path, 'r', encoding='utf-8') as f:
                document_content = f.read()
            
            logger.info(f"문서 로드 완료: {filename}, 크기: {file_size/1024:.2f}KB")
        
        # 문서 유형 감지
        document_type = 'general'
        crop_name = None
        
        # 문서 내용 기반 유형 분류
        if "상황버섯" in document_content[:1000]:
            document_type = 'crop_info'
            crop_name = "상황버섯"
        elif "작약" in document_content[:1000]:
            document_type = 'crop_info'
            crop_name = "작약"
        elif "쇠무릎" in document_content[:1000]:
            document_type = 'crop_info'
            crop_name = "쇠무릎"
        elif "특용작물" in document_content[:1000] or "약용작물" in document_content[:1000]:
            document_type = 'crop_info'
        elif any(term in document_content for term in ["병해충", "병원균", "방제", "흰가루병", "탄저병"]):
            document_type = 'disease_info'
        
        # 결과에 문서 유형과 작물명 추가
        result["document_type"] = document_type
        if crop_name:
            result["crop_name"] = crop_name
            
        logger.info(f"문서 유형 감지: {document_type}" + (f", 작물: {crop_name}" if crop_name else ""))
        
        # 메타데이터 구성
        metadata = {
            "document_type": document_type,
            "file_name": filename, 
            "file_extension": os.path.splitext(filename)[1].lower(),
            "file_size": file_size,
            "processing_date": datetime.now().strftime("%Y-%m-%d"),
            "processing_time": datetime.now().strftime("%H:%M:%S"),
            "learning_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")            
        }
        
        if crop_name:
            metadata["crop_name"] = crop_name
        
        # 1. 원문을 청크로 나누어 저장
        chunks_result = store_document_with_chunks(document_content, metadata)
        result["chunks_stored"] = chunks_result["chunks_count"] if isinstance(chunks_result, dict) and "chunks_count" in chunks_result else 0
        
        if isinstance(chunks_result, dict) and not chunks_result.get("success", False):
            logger.warning(f"문서 청크 저장 실패: {chunks_result.get('error', '알 수 없는 오류')}")
        
        # 2. 구조화된 정보 추출 및 저장
        structured_info = extract_structured_information(document_content, document_type)
        
        # 구조화된 정보가 있으면 optimal_collection에 저장
        if structured_info and "extracted_data" in structured_info and structured_info["extracted_data"]:
            doc_id = cra._doc_id_generator("document", farm_id)
            # 메타데이터에 구조화 정보 추가
            optimal_metadata = metadata.copy()
            optimal_metadata.update({
                "data_type": "structured_document",
                "is_manual": True,
                "is_learned_flag": True,
                "record_datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            logger(f" 생육 최적 집계 데이터 생성 -> {doc_id} ")
            result = cra.upsert_collection_data("update_optimal_collection", cfg.optimal_collection(), doc_id, "최종 생성 시간", optimal_metadata)            
            for key, value in structured_info["extracted_data"].items():
                if isinstance(value, str):
                    if len(value) > 500:
                        optimal_metadata[key] = value[:500] + "..."
                    else:
                        optimal_metadata[key] = value
                elif isinstance(value, (list, dict)):
                    optimal_metadata[key] = json.dumps(value, ensure_ascii=False)
            
            logger(f" 문서 학습 데이터 생성 -> {doc_id} ")
            cra.upsert_collection_data("llm_document_process", cfg.document_collection, doc_id, json.dumps(structured_info, ensure_ascii=False), optimal_metadata)
            
            result["structured_data_stored"] = True
            logger.info(f"구조화된 정보 저장 완료: {doc_id}")
        
        if document_type == 'crop_info' and crop_name:
            logger.info(f"{crop_name} 관련 QA 쌍 생성 시작")
            try:
                qa_pairs = generate_crop_qa_pairs(crop_name, document_content, filename)
                
                if qa_pairs:
                    stored_count = store_crop_qa_pairs(qa_pairs, metadata.get("farm_id"))
                    result["qa_pairs_generated"] = stored_count
                    logger.info(f"{crop_name} 관련 QA 쌍 {stored_count}개 생성 및 저장 완료")
            except Exception as e:
                logger.warning(f"QA 쌍 생성 및 저장 중 오류: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        # 성공 처리 및 추가 정보 설정
        result["success"] = True
        result["message"] = f"문서 처리 및 저장 완료: {filename}"
        result["chunks_stored"] = chunks_result["chunks_count"] if isinstance(chunks_result, dict) and "chunks_count" in chunks_result else 0
        result["structured_data_stored"] = structured_info and "extracted_data" in structured_info and structured_info["extracted_data"]
        
        # 작물 정보 문서의 경우 QA 쌍 생성 결과 추가
        if document_type == 'crop_info' and crop_name and "qa_pairs_generated" in result:
            logger.info(f"{crop_name} 관련 QA 쌍 {result['qa_pairs_generated']}개 생성됨")
        
        logger.info(f"문서 처리 완료: {filename}")
        return result
        
    except Exception as e:
        logger.error(f"문서 처리 중 오류: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        result["error"] = str(e)
        return result


# -------------------------------------------------
# 첨부 파일을 처리하고 학습하는 함수
# -------------------------------------------------
def process_attached_files(file_paths, farm_id):
    if not file_paths:
        return "처리할 첨부 파일이 없습니다."
    
    total_files = len(file_paths)
    success_count = 0
    failed_files = []
    results_summary = []
    
    logger.info(f" 첨부 파일 {total_files}개 처리 시작")
    
    for file_info in file_paths:
        file_path = file_info["path"]
        filename = file_info["filename"]
        
        try:
            logger.info(f" 파일 처리 시작: {filename}")
            
            # 지원하는 파일 형식 확인
            file_ext = os.path.splitext(filename)[1].lower()
            if file_ext not in ['.txt', '.md', '.csv', '.json']:
                msg = f"파일 '{filename}'은 지원하지 않는 형식입니다. txt, md, csv, json 파일만 처리 가능합니다."
                logger.warning(msg)
                failed_files.append({"filename": filename, "error": "지원하지 않는 파일 형식"})
                results_summary.append(msg)
                continue
            
            result = llm_document_process(file_path, farm_id)
            
            if result["success"]:
                success_count += 1
                chunks_count = result.get("chunks_stored", 0)
                qa_count = result.get("qa_pairs_generated", 0)
                
                # 문서 유형과 작물명 확인
                doc_type = result.get("document_type", "일반")
                crop_name = result.get("crop_name", "")
                
                msg = f"파일 '{filename}' 처리 완료: {chunks_count}개 청크 저장"
                if qa_count > 0:
                    msg += f", {qa_count}개 QA 쌍 생성"
                if crop_name:
                    msg += f", 작물: {crop_name}"
                
                logger.info(msg)
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
        result_message = f"첨부된 파일 {total_files}개를 모두 성공적으로 처리했습니다. (학습 일시: {learning_datetime})\n\n"
    else:
        result_message = f"첨부된 파일 {total_files}개 중 {success_count}개 처리 성공, {len(failed_files)}개 실패했습니다. (학습 일시: {learning_datetime})\n\n"    

    # 상세 결과 추가
    result_message += "처리 결과:\n"
    for i, summary in enumerate(results_summary):
        result_message += f"{i+1}. {summary}\n"
    
    result_message += "\n처리된 파일의 내용으로 질문해보세요!"
    
    logger.info(f" 첨부 파일 처리 완료: {success_count}/{total_files} 성공")
    return result_message
