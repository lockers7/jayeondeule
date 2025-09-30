import re
import sys
sys.path.append("/workspace/llm")
import json
import time
import numpy as np
import hashlib
import traceback
import requests

from datetime  import datetime, timedelta

import config                  as cfg
import modules.chroma_rest_api as cra

from modules.log_handler import setup_logger

# -------------------------------------------------------------------------------------------
# 로거 초기화
# -------------------------------------------------------------------------------------------
logger = setup_logger(__name__)

_embedding_cache = {}

# -----------------------------------------------
# 컬렉션 목록 조회 (REST API 기반)
# -----------------------------------------------
"""미사용 함수 제거: list_chroma_collections"""

# -----------------------------------------------------------
# ** 최종 학습 시작 시간 저장
# -----------------------------------------------------------
def update_learned_last_status():
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    logger.info(f" 학습 완료 일자 셋팅 -> {current_datetime}")
    result = cra.upsert_collection_data("update_learned_last_status",cfg.job_status_collection(),"last_learned_datetime","최종 학습일자",{"last_learned_datetime": current_datetime})
    if "error" not in result:
        logger.info(f" 학습완료 시간: {current_datetime} 저장 성공")
    else:
        logger.error(f" 학습완료 시간 저장 실패: {result['error']}")
        
    return current_datetime

# -------------------------------------------------------------------------------------------
# 마지막 학습 시간 가져오기
# -------------------------------------------------------------------------------------------
"""미사용 함수 제거: get_last_learned_datetime"""

# -------------------------------------------------------------------------------------------
# 기존 학습된 데이터 가져오기
# ChromaDB v2 API 기반으로 learned_collection에서 학습된 데이터를 조회합니다.
# farm_id와 hour로 필터링하며, record_datetime 파싱과 타입 검사를 포함합니다.
# -------------------------------------------------------------------------------------------
def get_learned_data(after_date=None, hour=None):
    default_dt = datetime.now() - timedelta(days=3*365)

    if after_date is None:
        after_date_obj = default_dt
    elif isinstance(after_date, str):
        try:
            if len(after_date) == 8 and after_date.isdigit():
                after_date_obj = datetime.strptime(after_date, "%Y%m%d")
            else:
                after_date_obj = datetime.strptime(after_date, "%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logger.warning(f"after_date 파싱 실패: {after_date} - {e}")
            after_date_obj = default_dt
    elif isinstance(after_date, datetime):
        after_date_obj = after_date
    else:
        logger.warning(f"지원되지 않는 after_date 타입: {type(after_date)}")
        after_date_obj = default_dt

    result = cra.get_documents(
        collection_name=cfg.learned_collection(),
        limit=100
    )

    if "error" in result or not result.get("documents"):
        logger.info(f" 기존 학습 데이터 없음 또는 오류: {result.get('error', '데이터 없음')}")
        return []

    all_data = result.get("metadatas", [])
    filtered_data = []

    for item in all_data:
        dt_str = item.get("record_datetime")
        if not dt_str:
            continue
        try:
            item_date = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            if item_date >= after_date_obj:
                filtered_data.append(item)
        except Exception as e:
            logger.warning(f"record_datetime 파싱 오류: {dt_str} - {e}")
            continue

    sorted_data = sorted(filtered_data, key=lambda x: x.get("record_datetime", ""), reverse=False)
    logger.info(f" 기존 학습 데이터 읽기 종료 - 처리완료: {len(sorted_data)}건")

    return sorted_data

# -------------------------------------------------------------------------------------------
# 신규 데이터 가져오기 (is_learned=False)
# 학습되지 않은 데이터를 source_collection에서 가져오는 함수.
# - after_date: datetime 또는 'all'
# - top_cnt: 0보다 크면 상위 n건만 반환
# -------------------------------------------------------------------------------------------
def get_unlearned_data(after_date=None, top_cnt=0):
    try:
        logger = setup_logger('get_unlearned_data')
        logger.info(f"Source 신규 학습 데이터 읽기 시작 - 시작일자: {after_date}, 건수: {top_cnt}")
        start_time = datetime.now()

        if isinstance(after_date, str) and after_date.lower() == "all":
            after_date_dt = datetime(2000, 1, 1)
        elif isinstance(after_date, str):
            try:
                if len(after_date) == 8:
                    after_date_dt = datetime.strptime(after_date, "%Y%m%d")
                elif "/" in after_date:
                    after_date_dt = datetime.strptime(after_date, "%Y/%m/%d")
                else:
                    after_date_dt = datetime.strptime(after_date, "%Y-%m-%d")
            except Exception as e:
                logger.warning(f"after_date 문자열 변환 실패 → 기본값 사용: {e}")
                after_date_dt = datetime.now() - timedelta(days=365 * 3)
        elif isinstance(after_date, datetime):
            after_date_dt = after_date
        else:
            after_date_dt = datetime.now() - timedelta(days=365 * 3)

        after_date_str = after_date_dt.strftime("%Y-%m-%d 00:00:00")
        logger.info(f"설정된 검색 시작 날짜: {after_date_str}")

        result = cra.get_documents(collection_name=cfg.source_collection(), limit=10000)
        metadatas = result.get("metadatas") if isinstance(result, dict) else None
        if not isinstance(metadatas, list) or not metadatas:
            logger.warning(f"source_collection 조회 실패 또는 빈 응답: {result}")
            return []

        logger.info(f"조회된 메타데이터 수: {len(metadatas)}")
        if "is_learned_flag" in metadatas[0]:
            logger.info(f"is_learned_flag 필드 존재: {metadatas[0]['is_learned_flag']}")
        else:
            logger.info("is_learned_flag 필드가 존재하지 않음")

        filtered = []
        for item in metadatas:
            if not isinstance(item, dict):
                continue

            is_learned = str(item.get("is_learned_flag", "False")).lower() == "true"
            record_dt_str = item.get("record_datetime")

            if not is_learned and record_dt_str:
                try:
                    record_dt = datetime.strptime(record_dt_str, "%Y-%m-%d %H:%M:%S")
                    if record_dt >= after_date_dt:
                        filtered.append(item)
                except Exception as e:
                    logger.warning(f"record_datetime 파싱 실패: {record_dt_str} → {e}")

        if top_cnt > 0:
            filtered = filtered[:top_cnt]

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Source 신규 학습 데이터 읽기 종료: 전체 {len(metadatas)}건 중 {len(filtered)}건 (처리시간: {elapsed:.3f}초)")

        return filtered
    except Exception as e:
        logger.error(f"학습 데이터 검색 중 오류: {e}")
        logger.error(traceback.format_exc())
        return []

# ------------------------------------------------------------------------
# Ollama 서버 상태 확인
# ------------------------------------------------------------------------
def check_ollama_health():
    try:
        v = requests.get(cfg.OLLAMA_BASE_URL + "/api/version", timeout=5)
        if v.status_code != 200:
            return False
        t = requests.get(cfg.OLLAMA_BASE_URL + "/api/tags", timeout=5)
        return t.status_code == 200
    except Exception:
        return False

# ------------------------------------------------------------------------
# 텍스트 길이에 따른 동적 타임아웃 계산
# ------------------------------------------------------------------------
def get_dynamic_timeout(text_length, base_timeout=60):
    return min(180, max(base_timeout, 30 + (text_length // 100)))

# ------------------------------------------------------------------------
# 일관성 있는 더미 임베딩 생성
# ------------------------------------------------------------------------
def generate_dummy_embedding(text):
    try:
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        seed = int(text_hash[:8], 16)
        
        np.random.seed(seed)
        expected_dim = cfg.CHROMA_EMBEDDING_DIM
        dummy_embedding = np.random.normal(0, 0.1, expected_dim).tolist()
        
        logger.debug(f"[embed_text] 더미 임베딩 생성 완료 - 시드: {seed}, 차원: {expected_dim}")
        return dummy_embedding
        
    except Exception as fallback_error:
        logger.error(f"[embed_text] 더미 임베딩 생성도 실패: {fallback_error}")
        return [0.0] * cfg.CHROMA_EMBEDDING_DIM

# ------------------------------------------------------------------------
# 배치 처리로 여러 텍스트를 임베딩
# - 서버 부하 분산
# - 배치 간 지연
# ------------------------------------------------------------------------
"""미사용 함수 제거: batch_embed_texts"""

# ------------------------------------------------------------------------
# 캐시 기능이 있는 임베딩 함수
# ------------------------------------------------------------------------
"""미사용 함수 제거: embed_text_with_cache"""

# ------------------------------------------------------------------------
# 저장 데이터의 텍스트 embedding 처리
# ------------------------------------------------------------------------
def embed_text(text, timeout=60, max_retries=5):
    if cfg.USE_DUMMY_EMBEDDING:
        return generate_dummy_embedding(text)
        
    if not text or not isinstance(text, str):
        logger.warning("[embed_text] 빈 텍스트 또는 잘못된 입력")
        return None
    
    original_length = len(text)
    if len(text) > 10000:
        text = text[:10000] + "..."
        logger.debug(f"[embed_text] 텍스트 길이 제한 적용: {original_length} -> {len(text)} 문자")
    
    if not check_ollama_health():
        logger.info("[embed_text] Ollama 서버 상태 불량 - 더미 임베딩 생성")
        return generate_dummy_embedding(text)
    
    dynamic_timeout = get_dynamic_timeout(len(text), timeout)
    logger.debug(f"[embed_text] 동적 타임아웃 설정: {dynamic_timeout}초 (텍스트 길이: {len(text)})")
    
    logger.debug(f"cfg.EMBEDDING_MODEL_NAME = {cfg.EMBEDDING_MODEL_NAME}")
    
    payload = {
        "model": cfg.EMBEDDING_MODEL_NAME,
        "input": text,
        "stream": False
    }
    
    last_error = None
    
    for attempt in range(max_retries):
        try:
            start_time = time.time()
            
            response = requests.post(
                cfg.OLLAMA_BASE_URL + "/api/embeddings", 
                json=payload, 
                timeout=dynamic_timeout
            )
            
            elapsed_time = time.time() - start_time
            logger.debug(f"[embed_text] 요청 완료 (시도 {attempt + 1}/{max_retries}): {elapsed_time:.2f}초")
            
            response.raise_for_status()
            data = response.json()
            embedding = data.get("embedding")

            if (not embedding) and isinstance(data.get("embeddings"), list) and data["embeddings"]:
                first = data["embeddings"][0]
                if isinstance(first, list):
                    embedding = first

            if (not embedding) and isinstance(data.get("data"), list) and data["data"]:
                first = data["data"][0]
                if isinstance(first, dict) and isinstance(first.get("embedding"), list):
                    embedding = first["embedding"]

            if embedding and isinstance(embedding, list) and len(embedding) > 0:
                expected_dim = cfg.CHROMA_EMBEDDING_DIM
                if len(embedding) == expected_dim:
                    logger.debug(f"[embed_text] 임베딩 성공 - 크기: {len(embedding)}, 소요시간: {elapsed_time:.2f}초")
                    return embedding
                else:
                    logger.warning(f"[embed_text] 임베딩 차원 불일치: {len(embedding)} != {expected_dim}")
                    last_error = f"차원 불일치: {len(embedding)} != {expected_dim}"
                    continue
            else:
                logger.debug(f"[embed_text] 임베딩 응답이 비어있음/스키마 불일치: {str(data)[:160]} → 더미 폴백")
                return generate_dummy_embedding(text)
                
        except requests.exceptions.Timeout as e:
            elapsed_time = time.time() - start_time
            logger.warning(f"[embed_text] 타임아웃 발생 (시도 {attempt + 1}/{max_retries}): {elapsed_time:.2f}초 경과")
            last_error = f"타임아웃: {e}"
            
            if attempt < max_retries - 1:
                wait_time = min(30, (2 ** attempt) + 5)  # 최대 30초 대기
                logger.info(f"[embed_text] {wait_time}초 대기 후 재시도... (타임아웃)")
                time.sleep(wait_time)
                
                dynamic_timeout = min(300, dynamic_timeout * 1.5)
                logger.debug(f"[embed_text] 다음 시도 타임아웃: {dynamic_timeout:.1f}초")
                continue
                
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"[embed_text] 연결 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            last_error = f"연결 오류: {e}"
            
            if attempt < max_retries - 1:
                wait_time = min(60, 10 + (attempt * 5))
                logger.info(f"[embed_text] {wait_time}초 대기 후 재시도... (연결 오류)")
                time.sleep(wait_time)
                
                if not check_ollama_health():
                    logger.error("[embed_text] 서버 상태 지속적으로 불량 - 더미 임베딩 생성")
                    return generate_dummy_embedding(text)
                continue
                
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None

            if status in (400, 404, 422):
                logger.warning(f"[embed_text] 임베딩 요청 거절({status}) → 더미 폴백")
                return generate_dummy_embedding(text)

            logger.warning(f"[embed_text] HTTP 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            last_error = f"HTTP 오류: {e}"

            if status is not None and status >= 500 and attempt < max_retries - 1:
                wait_time = min(30, 5 + (attempt * 3))
                logger.info(f"[embed_text] {wait_time}초 대기 후 재시도... (서버 오류)")
                time.sleep(wait_time)
                continue

            break
                
        except Exception as e:
            logger.warning(f"[embed_text] 예외 발생 (시도 {attempt + 1}/{max_retries}): {e}")
            last_error = f"예외: {e}"
            
            if attempt < max_retries - 1:
                wait_time = min(15, 2 + attempt)
                logger.info(f"[embed_text] {wait_time}초 대기 후 재시도... (일반 예외)")
                time.sleep(wait_time)
                continue
    
    logger.info(f"[embed_text] 모든 재시도 실패 ({max_retries}회) → 더미 임베딩 반환")
    logger.info(f"[embed_text] 마지막 오류: {last_error}")
    
    return generate_dummy_embedding(text)
    
# -------------------------------------------------------------------------------------------
# Vector DB에서 유사 데이터 검색(RAG 적용) - 확장된 버전
# -------------------------------------------------------------------------------------------
def search_similar_data(query_text, farm_id=None, hour=None, top_count=5, date_range=None):
    try:
        if farm_id is None:
            farm_id_pattern = re.compile(r'농장\s*ID[:\s=]*(\d+)|농장\s*(\d+)\s*번|(\d+)\s*번\s*농장')
            match = farm_id_pattern.search(query_text)
            if match:
                groups = match.groups()
                farm_id = next((g for g in groups if g), "default_farm_id")
            else:
                farm_id = "default_farm_id"
            logger.info(f" 농장코드가 지정되지 않아 추출한 ID {farm_id} 사용")

        if not date_range:
            one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
            today = datetime.now().strftime("%Y-%m-%d")
            date_range = {
                "start_date": one_year_ago,
                "end_date": today
            }
            logger.info(f" Similar 날짜 범위가 지정되지 않아 기본 범위 사용: {date_range['start_date']} ~ {date_range['end_date']}")
        
        try:
            where_clause = {}
            if farm_id:
                where_clause["farm_id"] = farm_id
                
            query_embedding = embed_text(query_text)
            if not query_embedding:
                logger.warning("쿼리 임베딩 생성 실패")
                return []
                
            results = cra.query_documents(
                collection_name=cfg.learned_collection(),
                query_texts=query_text,
                query_embeddings=[query_embedding],
                n_results=top_count * 3,
                where=where_clause if where_clause else None
            )            
            similar_docs = []
            
            if "error" not in results and results.get("matches"):
                for match in results["matches"]:
                    metadata = match.get("metadata", {})
                    
                    # 날짜 범위 필터링 로직
                    if date_range and "record_datetime" in metadata:
                        record_date = metadata["record_datetime"]
                        is_in_range = False
                        
                        if isinstance(record_date, str):
                            try:
                                record_date_str = datetime.strptime(record_date, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
                                if date_range["start_date"] <= record_date_str <= date_range["end_date"]:
                                    is_in_range = True
                            except:
                                try:
                                    record_date_str = datetime.strptime(record_date, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
                                    if date_range["start_date"] <= record_date_str <= date_range["end_date"]:
                                        is_in_range = True
                                except:
                                    pass
                        
                        if not is_in_range:
                            continue

                    relay_data = cfg.extract_relay_data(metadata)
                    if relay_data:
                        metadata["standardized_relay_data"] = relay_data
                    
                    similar_docs.append(metadata)
                    
                    if len(similar_docs) >= top_count:
                        break
            
            logger.info(f" 쿼리 실행 결과: {len(similar_docs)}건")
            return similar_docs
            
        except Exception as e:
            logger.info(f" 벡터DB 검색 오류: {e}")
            logger.error(traceback.format_exc())
            return []
    
    except Exception as e:
        logger.info(f" 벡터DB 검색 오류: {e}")
        return []

# -------------------------------------------------------------------------------------------
# 신규 학습할 데이터 is_learned=True 로 셋팅팅
# -------------------------------------------------------------------------------------------
def clean_metadata(metadata: dict) -> dict:
    cleaned = {}
    for k, v in metadata.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            cleaned[k] = v
        else:
            cleaned[k] = str(v)
    return cleaned

def generate_document_text(meta: dict) -> str:
    def get(key):
        val = meta.get(key)
        return val if val not in [None, ""] else "정보 없음"

    return (
        f"{get('record_datetime')} 기준 환경 데이터: 농장 '{get('farm_name')}', 재배사 '{get('house_name')}'. "
        f"온도 {get('indoor_temperature_value')}°C, 습도 {get('indoor_humidity_value')}%, "
        f"co₂농도 {get('co2_concentration_value')}ppm, 급수: {get('fog_occurs_flag')}, "
        f"난방: {get('indoor_heater_flag')}, 조명토글: {get('lighting_flag')}, "
        f"환기: {get('exhaust_fan_flag')}, 관수토글: {get('irrigation_flag')}."
    )

def update_learned_source_data(datas):
    try:
        if not datas:
            logger.info("업데이트할 소스 데이터가 없습니다.")
            return {"error": "입력 데이터 없음"}

        ids, documents, metadatas = [], [], []

        for idx, item in enumerate(datas):
            try:
                doc_id = cra._doc_id_generator(
                    item.get("data_kind"),
                    item.get("farm_id"),
                    item.get("house_id"),
                    item.get("record_datetime")
                )
                if not doc_id:
                    logger.warning(f"[스킵] doc_id 생성 실패 → index={idx}")
                    continue

                # 학습 상태 및 타임스탬프 기록
                learning_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                item["is_learned_flag"] = True
                item["learning_date"] = learning_time
                item["doc_id"] = doc_id

                # 최종 입력값 구성
                ids.append(doc_id)
                documents.append(generate_document_text(item))
                metadatas.append(clean_metadata(item))

            except Exception as ie:
                logger.warning(f"[스킵] doc_id 생성 중 오류 → index={idx}, error={str(ie)}")
                continue

        if not (ids and documents and metadatas):
            logger.error("  문서 형식 오류 - list 내 유효 문서 없음")
            return {"error": "문서 형식 오류 - list 내 유효 문서 없음"}

        logger.info(f"[Chroma] 총 {len(ids)}건의 학습 플래그 업데이트 시작")

        result = cra.upsert_collection_data(
            calledby="update_learned_source_data",
            collection=cfg.source_collection(),
            doc_id=ids,
            document=documents,
            metadata=metadatas
        )

        logger.info(f"[Chroma] 학습 플래그 업데이트 완료: {result}")

        if result and isinstance(result, dict) and "error" in result:
            logger.error("[분석] ❌ 오류 발생 - ChromaDB 업서트 실패")
            logger.error(f"🔎 오류 메시지: {result['error']}")
            logger.error(f"📦 대상 컬렉션: {cfg.source_collection()}")
            logger.error(f"🆔 총 doc_id 수: {len(ids)}")
            logger.error(f"📄 총 document 수: {len(documents)}")
            logger.error(f"🧾 총 metadata 수: {len(metadatas)}")
            for i in range(min(5, len(ids))):
                logger.error(f"--- 문서 {i+1} ---")
                logger.error(f"doc_id: {ids[i]}")
                logger.error(f"document: {documents[i]}")
                logger.error(f"metadata: {json.dumps(metadatas[i], ensure_ascii=False)[:1000]}")

        return result

    except Exception as e:
        logger.error(f"update_learned_source_data 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"error": str(e)}

    
# -------------------------------------------------------------------------------------------
# 원문을 의미 있는 청크로 나누어 저장하는 함수
# -------------------------------------------------------------------------------------------
def store_document_with_chunks(document_content, document_metadata, chunk_size=1000, chunk_overlap=200):
    result = {
        "success": False,
        "chunks_count": 0,
        "error": None
    }
    
    try:
        # 문서를 청크로 분할 - 문단 단위 분리 시도
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
            logger.info("문단 기반 분할 결과가 불충분하여 크기 기반 분할로 전환")
            chunks = []
            for i in range(0, len(document_content), chunk_size - chunk_overlap):
                chunk = document_content[i:i + chunk_size]
                if len(chunk) < 100:  # 너무 작은 청크는 건너뜀
                    continue
                chunks.append(chunk)
        
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

                status = cra.upsert_collection_data(calledby="save_document_chunks", collection=cfg.document_collection(), doc_id=chunk_id, document=chunk, metadata=chunk_metadata)
                if status in ["added", "updated"]:
                    success_count += 1
                else:
                    logger.warning(f" 청크 저장 실패: {chunk_id} - status: {status}")

            except Exception as e:
                logger.error(f" 청크 저장 중 예외 발생: {e}")
                import traceback
                logger.error(traceback.format_exc())

        
        result["success"] = success_count > 0
        result["chunks_count"] = success_count
        logger.info(f"문서 '{document_metadata.get('file_name', 'doc')}' {success_count}개 청크로 저장 완료")
        
        return result
        
    except Exception as e:
        logger.error(f"문서 청크 저장 중 오류: {e}")
        logger.error(traceback.format_exc())
        result["error"] = str(e)
        return result

            # Removed legacy document content generation code
