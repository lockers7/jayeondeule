# ═════════════════════════════════════════════════════════════════
# 문서 처리 파이프라인: 파싱, 유형 감지, 청크 저장, LLM enrichment.
# ═════════════════════════════════════════════════════════════════
import os
import traceback
from datetime import datetime

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.chroma.collections import farm_knowledge_collection, document_collection
from agri_ai_core.src.chroma.operations import upsert_collection_data
from agri_ai_core.src.ai.rag.chunker import store_document_with_chunks

logger = setup_logger(__name__)

# 문서 유형 한글 라벨
from agri_ai_core.src.ai.rag.constants import DOC_TYPE_LABELS

# 작물 키워드 사전 (문서 유형 자동 감지용)
_CROP_KEYWORDS = {
    # 버섯류
    "상황버섯": "상황버섯", "상황": "상황버섯", "Phellinus": "상황버섯",
    "표고버섯": "표고버섯", "표고": "표고버섯",
    "느타리버섯": "느타리버섯", "느타리": "느타리버섯",
    "영지버섯": "영지버섯", "영지": "영지버섯",
    "새송이버섯": "새송이버섯", "새송이": "새송이버섯",
    "팽이버섯": "팽이버섯", "팽이": "팽이버섯",
    "송이버섯": "송이버섯",
    "목이버섯": "목이버섯", "목이": "목이버섯",
    "동충하초": "동충하초",
    "노루궁뎅이": "노루궁뎅이버섯",
    # 약용작물
    "작약": "작약", "쇠무릎": "쇠무릎", "우슬": "쇠무릎",
    "당귀": "당귀", "황기": "황기", "인삼": "인삼",
    "천궁": "천궁", "감초": "감초", "구기자": "구기자",
    "오미자": "오미자", "산수유": "산수유",
    # 일반 농작물
    "딸기": "딸기", "토마토": "토마토", "고추": "고추",
    "오이": "오이", "상추": "상추", "파프리카": "파프리카",
    "멜론": "멜론", "수박": "수박", "참외": "참외",
}

# 병해충 키워드 목록
_DISEASE_KEYWORDS = [
    "병해충", "병원균", "방제", "흰가루병", "탄저병", "잿빛곰팡이병",
    "노균병", "역병", "세균성", "바이러스병", "해충", "진딧물",
    "응애", "나방", "선충", "균핵병", "시들음병", "무름병",
]


# ═════════════════════════════════════════════════════════════════════════════════
# 대화 메시지 목록 → RAG 저장용 텍스트 변환 (공통)
# React(app.py)에서 REST API를 통해 호출
# Args:
#   messages: [{"role": "user"|"assistant", "content": str}, ...]  (dict 또는 객체)
#   farm_name: 농장명
#   house_name: 재배사명
# Returns:
#   str: 변환된 텍스트
# ═════════════════════════════════════════════════════════════════════════════════
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


# ════════════════════════════════════════════════
# RAG 저장 결과 → 사용자 안내 메시지 포맷팅 (공통)
# Args:
#   result: llm_document_process() 반환값
#   message_count: 저장된 메시지 수
# Returns:
#   tuple: (success: bool, message: str)
# ════════════════════════════════════════════════
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
        if result.get("summary_stored"):
            summary += f"  문서 요약: LLM 생성 완료\n"
        qa_count = result.get("qa_pairs_generated", 0)
        if qa_count > 0:
            summary += f"  QA 쌍: {qa_count}개 생성\n"
        summary += "\n저장된 대화 내용으로 질문해보세요!"
        return True, summary
    else:
        error = result.get("error", "알 수 없는 오류")
        return False, f"RAG 저장 실패: {error}"


# ══════════════════
# 문서 유형 감지
# ══════════════════
def detect_document_type(document_content, filename=None):
    document_type = 'general'
    crop_name = None

    # 검색 대상: 문서 앞부분 + 파일명
    search_text = document_content[:2000]
    if filename:
        search_text = f"{filename} {search_text}"

    # 1. 작물 키워드 매칭 (빈도 기반: 가장 많이 등장하는 작물)
    crop_counts = {}
    for keyword, name in _CROP_KEYWORDS.items():
        count = search_text.count(keyword)
        if count > 0:
            crop_counts[name] = crop_counts.get(name, 0) + count

    if crop_counts:
        document_type = 'crop_info'
        crop_name = max(crop_counts, key=crop_counts.get)
    elif "특용작물" in search_text or "약용작물" in search_text or "재배" in search_text:
        document_type = 'crop_info'
    # 2. 병해충 키워드 매칭
    elif any(term in search_text for term in _DISEASE_KEYWORDS):
        document_type = 'disease_info'

    return document_type, crop_name


# ════════════════════════════════════════════════════════════════════
# 작물/병해충 문서를 farm_knowledge_collection에 이중 저장
# document_collection에 이미 저장된 청크를 farm_knowledge에도 저장하여
# farm_id/house_id 기반 검색에서도 작물 관련 문서가 검색되도록 함
# ════════════════════════════════════════════════════════════════════
def _store_crop_chunks_to_farm_knowledge(document_content, metadata, document_type, crop_name, filename, farm_id):
    from agri_ai_core.src.ai.rag.embedder import embed_text
    from agri_ai_core.src.ai.rag.chunker import chunk_document
    from agri_ai_core.src.chroma.operations import upsert_documents_with_embedding

    chunks = chunk_document(document_content, chunk_size=1000, chunk_overlap=200)
    if not chunks:
        return

    doc_id_base = filename.replace(".", "_") if filename else "crop_unknown"
    batch_docs = []

    for i, chunk in enumerate(chunks):
        chunk_id = f"fk_{doc_id_base}_{i}"
        chunk_text = f"[파일: {filename}]\n{chunk}" if filename else chunk

        embedding = embed_text(chunk_text)
        if not embedding:
            continue

        chunk_metadata = {
            "document_type": document_type,
            "file_name": filename,
            "data_kind": "crop_document_chunk",
            "chunk_id": i,
            "total_chunks": len(chunks),
            "record_datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if crop_name:
            chunk_metadata["crop_name"] = crop_name
        if farm_id is not None:
            chunk_metadata["farm_id"] = str(farm_id)

        batch_docs.append({
            "doc_id": chunk_id,
            "text": chunk_text,
            "metadata": chunk_metadata,
            "embedding": embedding,
        })

    if batch_docs:
        result = upsert_documents_with_embedding(farm_knowledge_collection(), batch_docs)
        stored = result.get("count", len(batch_docs)) if isinstance(result, dict) and result.get("success") else 0
        logger.info(
            f"[문서학습] farm_knowledge 이중 저장 완료: {filename} "
            f"type={document_type} crop={crop_name or '-'} chunks={stored}건"
        )


# ══════════════════════════════════════════════════════════════
# LLM enrichment 백그라운드 실행 (요약 + QA 쌍 생성)
# 청크 저장 완료 후 비동기로 실행되어 API 응답을 블로킹하지 않음
# ══════════════════════════════════════════════════════════════
def _background_enrich(document_content, metadata, document_type, crop_name, filename):
    try:
        from agri_ai_core.src.ai.rag.document_enricher import enrich_document

        enrich_result = enrich_document(
            document_content=document_content,
            metadata=metadata,
            document_type=document_type,
            crop_name=crop_name,
        )

        if enrich_result.get("success"):
            logger.info(
                f"[문서학습] LLM enrichment 백그라운드 완료: {filename} "
                f"요약={'O' if enrich_result.get('summary_stored') else 'X'}, "
                f"QA={enrich_result.get('qa_pairs_generated', 0)}쌍"
            )
        else:
            logger.warning(
                f"[문서학습] LLM enrichment 백그라운드 실패 (청크 저장은 유지): {filename} "
                f"{enrich_result.get('error', '')}"
            )
    except Exception as e:
        logger.warning(f"[문서학습] LLM enrichment 백그라운드 예외 (청크 저장은 유지): {filename} {e}")


# ═════════════════════════════
# 문서 처리하여 ChromaDB에 저장
# ═════════════════════════════
def llm_document_process(file_path=None, text_content=None, farm_id=None, original_name=None):
    import time as _time
    _t_doc_start = _time.time()

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
            file_ext = os.path.splitext(filename)[1].lower()

            # 파일 읽기 (PDF는 바이너리이므로 별도 처리)
            if file_ext == '.pdf':
                from agri_ai_core.src.ai.file_processor import read_pdf_file
                document_content = read_pdf_file(file_path)
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    document_content = f.read()

            logger.debug(f"문서 로드 완료: {filename}, 크기: {file_size/1024:.2f}KB")

        # 문서 유형 감지 (파일명도 함께 분석)
        document_type, crop_name = detect_document_type(document_content, filename)

        # 결과에 문서 유형과 작물명 추가
        result["document_type"] = document_type
        if crop_name:
            result["crop_name"] = crop_name

        logger.debug(f"문서 유형 감지: {document_type}" + (f", 작물: {crop_name}" if crop_name else ""))

        # UUID 접두사 제거하여 원본 파일명 추출 (8자리hex_원본명 패턴)
        _orig_name = original_name
        if not _orig_name and filename:
            import re as _re
            _m = _re.match(r'^[0-9a-f]{8}_(.+)$', filename)
            _orig_name = _m.group(1) if _m else filename

        # 파일명 공백 → 밑줄 정규화 (검색/삭제 시 공백·밑줄 불일치 방지)
        _orig_name = _orig_name.replace(" ", "_") if _orig_name else _orig_name

        # 메타데이터 구성
        metadata = {
            "document_type": document_type,
            "file_name": _orig_name or filename,
            "file_name_stored": filename,
            "file_extension": os.path.splitext(filename)[1].lower() if filename else "",
            "file_size": file_size,
            "processing_date": datetime.now().strftime("%Y-%m-%d"),
            "processing_time": datetime.now().strftime("%H:%M:%S"),
            "learning_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        if farm_id is not None:
            metadata["farm_id"] = farm_id
            # 문서 학습 데이터는 house_id 없음 (농장 단위 관리, 요건: farm_id만 존재)

        if crop_name:
            metadata["crop_name"] = crop_name

        # 1. 원문을 청크로 나누어 저장
        chunks_result = store_document_with_chunks(document_content, metadata)
        result["chunks_stored"] = chunks_result["chunks_count"] if isinstance(chunks_result, dict) and "chunks_count" in chunks_result else 0

        if isinstance(chunks_result, dict) and not chunks_result.get("success", False):
            logger.warning(f"문서 청크 저장 실패: {chunks_result.get('error', '알 수 없는 오류')}")

        # 청크가 0개이면 텍스트 추출 실패 (이미지 PDF 등) — 메타데이터도 저장하지 않고 조기 반환
        if result["chunks_stored"] == 0:
            logger.warning(f"[문서학습] 청크 0개 — 텍스트 추출 실패 (이미지 PDF일 수 있음): {filename}")
            result["error"] = (
                f"텍스트를 추출할 수 없습니다: {_orig_name or filename}\n"
                f"이미지 스캔 PDF인 경우 서버에 tesseract-ocr 설치 후 재시도하세요: "
                f"sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-kor"
            )
            result["message"] = (
                f"학습 실패 — 이미지 PDF에서 텍스트를 추출하지 못했습니다: {_orig_name or filename}\n"
                f"(OCR 지원 필요: sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-kor)"
            )
            return result

        # 2. 구조화된 정보 추출 및 저장
        #    embed_text 호출이 있으므로, enrichment 스레드 시작 전에 완료하여 Ollama GPU 경합 방지
        try:
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
                farm_knowledge_collection(),
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

        # 3. 작물/병해충 문서 → farm_knowledge_collection에도 청크 이중 저장
        if document_type in ('crop_info', 'disease_info'):
            try:
                _store_crop_chunks_to_farm_knowledge(
                    document_content, metadata, document_type, crop_name, _orig_name or filename, farm_id
                )
            except Exception as e:
                logger.warning(f"[문서학습] farm_knowledge 이중 저장 실패 (document 저장은 유지): {e}")

        logger.info(f"[문서학습] 청크 + 구조화 데이터 저장 완료: {filename} (type={document_type})")

        # 성공 처리
        result["success"] = True
        result["message"] = f"문서 처리 및 저장 완료: {filename}"

        _doc_elapsed = _time.time() - _t_doc_start
        logger.debug(f"문서 처리 완료: {filename}")
        logger.debug(
            f"[PERF:문서학습] 문서처리={_doc_elapsed:.1f}s, "
            f"파일={filename}, 청크={result['chunks_stored']}개"
        )
        return result

    except Exception as e:
        logger.error(f"문서 처리 중 오류: {str(e)}")
        logger.error(traceback.format_exc())
        result["error"] = str(e)
        return result


# ══════════════════
# 첨부 파일 처리
# ══════════════════
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
            if file_ext not in ['.txt', '.md', '.csv', '.json', '.pdf']:
                msg = f"파일 '{filename}'은 지원하지 않는 형식입니다. txt, md, csv, json, pdf 파일만 처리 가능합니다."
                logger.warning(msg)
                failed_files.append({"filename": filename, "error": "지원하지 않는 파일 형식"})
                results_summary.append(msg)
                continue

            result = llm_document_process(
                file_path=file_path, farm_id=farm_id,
                original_name=file_info.get("original_name"),
            )

            if result["success"]:
                success_count += 1
                chunks_count = result.get("chunks_stored", 0)
                qa_count = result.get("qa_pairs_generated", 0)
                crop_name = result.get("crop_name", "")
                doc_type = result.get("document_type", "general")
                structured = result.get("structured_data_stored", False)

                doc_type_label = DOC_TYPE_LABELS.get(doc_type, doc_type)

                # 응답 메시지에는 원본 파일명 표시
                _display_name = file_info.get("original_name") or filename
                msg = f"✓ '{_display_name}' → {chunks_count}개 청크 저장"
                msg += f" | 문서유형: {doc_type_label}"
                if crop_name:
                    msg += f" | 작물: {crop_name}"
                if structured:
                    msg += f" | 구조화 데이터 저장 완료"
                if result.get("summary_stored"):
                    msg += f" | LLM 요약 완료"
                if qa_count > 0:
                    msg += f" | {qa_count}개 QA 쌍 생성"

                logger.debug(msg)
                results_summary.append(msg)
            else:
                error = result.get("error", "알 수 없는 오류")
                _display_name = file_info.get("original_name") or filename
                msg = f"파일 '{_display_name}' 처리 실패: {error}"
                logger.error(msg)
                failed_files.append({"filename": _display_name, "error": error})
                results_summary.append(msg)

        except Exception as e:
            _display_name = file_info.get("original_name") or filename
            msg = f"파일 '{_display_name}' 처리 중 예외 발생: {str(e)}"
            logger.error(msg)
            logger.error(traceback.format_exc())
            failed_files.append({"filename": _display_name, "error": str(e)})
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
