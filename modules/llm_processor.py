import os
import re
import sys
sys.path.append("/workspace/llm")
import json
import time
import ollama
from datetime import datetime

import config                  as cfg
import modules.chroma_rest_api as cra

from modules.relay_status import generate_final_response

from modules.log_handler  import setup_logger
logger = setup_logger(__name__)

os.environ['OLLAMA_MAX_LOADED_MODELS'] = '1'
os.environ['OLLAMA_NUM_PARALLEL']      = '2'
os.environ['OLLAMA_KEEP_ALIVE']        = '1h'

# -----------------------------------------------------------
# ** LLM 질의를 처리하고 응답을 생성하는 통합 함수
# ** 완전한 버전 (날씨 + 날짜 질문 처리 포함)
# -----------------------------------------------------------
async def process_llm_query(system_prompt=None, user_prompt=None, query_type=None, context_data=None, hour=None, stream=False):
    start_time = datetime.now()
    if system_prompt == None:
        system_prompt =""    
    try:
        system_length = len(system_prompt)
        user_length   = len(user_prompt)
        total_length  = system_length + user_length
        logger.info("\n"*1)
        if not stream:
            logger.info("="*20 + " " + ">"*3 + " LLM PROCESSING START " + "<"*3 + " " + "="*20)  
        else:      
            logger.info("="*20 + " " + ">"*3 + " LLM STREAM PROCESSING START " + "<"*3 + " " + "="*20)  
        logger.info(f"[1] 질의 유형: {query_type}자 \n 프롬프트 길이: {total_length}")
        logger.info(f"[2] 시스템 질의: {system_length}자\n {system_prompt}")
        logger.info(f"[3] 사용자 질의: {user_length}자\n {user_prompt}")
        logger.info(">>>" + "-"*50 + "<<<")

        if not stream:
            if query_type == "relay_llm_control":
                response = get_llm_response(system_prompt=system_prompt, user_prompt=user_prompt,temperature=0.1, top_p=0.8, top_k=20, num_predict=cfg.NUM_PREDICT, query_type=query_type)
            else:
                response = get_llm_response(user_prompt=user_prompt)
        else:
            response = ""
            async for chunk in get_llm_streaming_response(user_prompt):
                response += chunk
                yield chunk          

        response_length = len(response)
        processing_time = (datetime.now() - start_time).total_seconds()
        logger.info(f"[4] LLM 응답: {response_length}자\n\n\n{response}")
        logger.info(f"[5] 처리 시간: {processing_time:.3f}초")
        if not stream:
            logger.info("="*20 + " " + ">"*3 + " LLM PROCESSING FINISH " + "<"*3 + " " + "="*20)
            logger.info("\n"*1)
            
            yield response
        else:
            logger.info("="*20 + " " + ">"*3 + " LLM STREAM PROCESSING START " + "<"*3 + " " + "="*20)        
            logger.info("\n"*1)

    except Exception as e:
        logger.error(f" LLM 질의 처리 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        error_message = "죄송합니다. 응답 생성 중 오류가 발생했습니다."
        yield error_message

# -----------------------------------------------------------
# ** 단순 질의 처리 
# -----------------------------------------------------------
def process_llm_query_simple(user_query=None, farm_id=None, house_id=None, farm_name=None, house_name=None):
    try:
        context_result = prepare_query_context(user_query, None, farm_id, house_id, farm_name, house_name)
        
        if context_result.get("special_command"):
            special_response = process_special_commands(
                context_result["special_command"], 
                user_query, 
                None, 
                farm_id, 
                farm_name, 
                context_result.get("context_data")
            )
            if special_response:
                return special_response

        prompt = context_result.get("prompt", "")
        query_type = context_result.get("query_type", "general_chat")
        
        if prompt:
            llm_response = get_llm_response(user_prompt=prompt)
            
            final_response = generate_final_response(llm_response, query_type, farm_id, house_id)
            return final_response
        else:
            return "질문을 처리할 수 없습니다. 다시 시도해주세요."
            
    except Exception as e:
        logger.error(f"단순 질의 처리 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return f"질의 처리 중 오류가 발생했습니다: {str(e)}"
    
# ----------------------------------------------------------------------------------------------------------------
# ** LLM 응답 생성
#    Ollama API를 통한 LLM 응답 생성
# 파라미터          설명	                                                  수치 추천
# temperature  	    창의성 정도 (0=결정적, 1=창의적)	                       0.0 ~ 0.2 ← 낮을수록 명확한 응답
# top_p             누적 확률이 높은 단어 집합 내에서 선택 (Nucleus sampling)   0.8 ~ 0.9
# top_k             확률이 높은 상위 K개 단어 중 선택	                       20 ~ 40
# num_predict       최대 출력 토큰 수	                                 예:   512, 1024 등
# stop	응답 종료    트리거 문자열 (선택)	                              예:  ["\nUser:", "###"]
# repeat_penalty     반복 억제 (높을수록 반복 덜함)	                    기본:  1.0
# presence_penalty	 등장빈도 높은 단어 피함	                        기본:  0.0
# frequency_penalty	중복 단어 감소	                                    기본:  0.0
# ----------------------------------------------------------------------------------------------------------------
def get_llm_response(system_prompt=None, user_prompt=None, temperature=0.7, top_p=0.9, top_k=40, num_predict=cfg.NUM_PREDICT, query_type=None):
    try:
        max_retries = 2
        retry_count = 0
        while retry_count <= max_retries:
            try:
                response = ollama.chat(
                    model=cfg.MODEL_NAME,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    options={
                        "temperature": temperature,
                        "top_p": top_p,
                        "top_k": top_k,
                        "num_predict": num_predict
                    }
                )
                break
            except Exception as retry_err:
                retry_count += 1
                if retry_count > max_retries:
                    raise retry_err
                logger.error(f" LLM 응답 생성 중 오류, 재시도 {retry_count}/{max_retries}: {retry_err}")
                time.sleep(1)

        if hasattr(response, 'message') and hasattr(response.message, 'content'):
            response_text = response.message.content

        elif isinstance(response, dict) and "response" in response:
            response_text = response["response"]

        else:
            response_text = "응답을 생성할 수 없습니다."

        original_length = len(response_text) if response_text else 0 

        if query_type == "relay_llm_control" and original_length > 0:
            if not response_text.strip().endswith('}'):
                logger.warning(" 응답이 중간에 잘린 것으로 보임 (JSON이 완성되지 않음)")
            
            if "METADATA:" in response_text and response_text.count('{') > response_text.count('}'):
                logger.warning(" JSON 구조가 불완전함")
            
        if not response_text or len(response_text.strip()) == 0:
            logger.error("빈 응답 텍스트")
            response_text = "LLM이 빈 응답을 반환했습니다."
        
        if query_type == "relay_llm_control":
            filtered_response = filter_llm_response(response_text, filter_type="relay_control")
        else:
            filtered_response = filter_llm_response(response_text, filter_type="general")

                    
        return filtered_response
        
    except Exception as e:
        logger.error(f" LLM 응답 생성 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return "죄송합니다. 현재 응답을 생성할 수 없습니다."

# -----------------------------------------------------------
# ** LLM 스트리밍 응답 생성
# -----------------------------------------------------------
async def get_llm_streaming_response(prompt, temperature=0.7, top_p=0.9, top_k=40, num_predict=cfg.NUM_PREDICT):
    try:
        full_response = ""
        accumulated_text = ""
        think_tag_removed = False
        
        for response_chunk in ollama.generate(
            model=cfg.MODEL_NAME, 
            prompt=prompt, 
            stream=True, 
            options={
                "temperature": temperature, 
                "top_p": top_p, 
                "top_k": top_k, 
                "num_predict": num_predict
            }
        ):
            chunk_text = response_chunk.get("response", "")
            if not chunk_text:
                continue

            accumulated_text += chunk_text
            
            if not think_tag_removed:
                if "</think>" in accumulated_text:
                    filtered_accumulated = filter_llm_response(accumulated_text, filter_type="general")
                    think_tag_removed = True
                    
                    if filtered_accumulated != full_response:
                        new_chunk = filtered_accumulated[len(full_response):]
                        if new_chunk and new_chunk not in full_response:
                            yield new_chunk
                            full_response = filtered_accumulated
                else:
                    continue
            else:
                filtered_chunk = clean_streaming_chunk(chunk_text)
                if filtered_chunk:
                    yield filtered_chunk
                    full_response += filtered_chunk
                
    except Exception as e:
        logger.error(f" LLM 스트리밍 응답 생성 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        yield "죄송합니다. 현재 응답을 생성할 수 없습니다."
     
# -----------------------------------------------------------
# ** 특수 명령어 처리
# -----------------------------------------------------------
def process_special_commands(special_command, query=None, file_paths=None, farm_id=None, farm_name=None, context_data=None):
    try:
        if special_command == "document_train":
            from modules.llm_document_process import process_attached_files
            response = process_attached_files(file_paths, farm_id)
            return response

        if special_command == "text_learn":
            logger.info(" 학습 및 저장 명령어 감지됨")
            next_message = get_next_message()
            if next_message and len(next_message) > 50:
                from modules.data_retriever     import process_and_save_text
                response = process_and_save_text(next_message, farm_id)
                return response
            else:
                return "학습할 내용을 충분히 입력해주세요. 내용이 너무 짧거나 없습니다."

        if special_command == "llm_identity":
            farm_name = f"{farm_name}" if farm_name else "스마트팜"
            response = f"안녕하세요! 저는 {farm_name}의 지킴이입니다. 스마트팜 데이터를 관리하고 분석하여 농장주님께 도움을 드리는 AI 어시스턴트입니다. 어떤 도움이 필요하신가요?"
            return response

        if special_command == "learning_info":
            prompt = f"""사용자가 현재까지 학습된 데이터에 대해 질문했습니다.\n사용자 질문: {query}\n\n아래는 현재까지 학습된 데이터 목록입니다:"""
            learned_data = context_data.get("learned_data", [])

            if not learned_data:
                try:
                    result = cra.get_documents(collection_name=cfg.learned_collection(), limit=100)
                    if result and "metadatas" in result:
                        learned_data = result["metadatas"]
                        logger.info(f" 학습 데이터 직접 조회: {len(learned_data)}건")
                except Exception as e:
                    logger.warning(f" 학습 데이터 직접 조회 중 오류: {e}")

            learning_summaries = []
            seen_docs = set()
            for data in learned_data:
                doc_title = data.get("document_title", "알 수 없는 문서")
                learning_date = data.get("learning_date", "날짜 정보 없음")
                crop_name = data.get("crop_name", "")
                category = data.get("category", "")
                doc_key = f"{doc_title}_{learning_date}"
                if doc_key in seen_docs:
                    continue
                seen_docs.add(doc_key)
                summary = f"- 문서: {doc_title}, 학습 일자: {learning_date}"
                if crop_name:
                    summary += f", 작물: {crop_name}"
                if category:
                    summary += f", 카테고리: {category}"
                learning_summaries.append(summary)

            if learning_summaries:
                prompt += "\n" + "\n".join(learning_summaries)
            else:
                prompt += "\n현재까지 학습된 데이터가 없습니다."

            prompt += """\n\n다음 내용을 포함하여 답변해주세요:\n1. 학습된 문서 목록과 각 문서의 학습 날짜를 명확하게 설명해주세요.\n2. 사용자가 특정 작물이나 카테고리에 관심이 있다면, 관련된 학습 데이터를 강조해주세요.\n3. 학습된 내용이 없다면, 문서를 업로드하고 학습하는 방법을 안내해주세요."""

            response = get_llm_response(user_prompt=prompt)
            return response

        return None
        
    except Exception as e:
        logger.error(f" 특수 명령어 처리 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return f"특수 명령어 처리 중 오류가 발생했습니다: {str(e)}"

# ----------------------------------------------------------------------------------
#   1. API 환경: 다음 메시지를 기다리는 로직
#   2. 웹 인터페이스: 프론트엔드에서 처리
#   3. 테스트 환경: 입력 프롬프트
# ----------------------------------------------------------------------------------
def get_next_message():
    logger.info(" 다음 메시지 대기 중...")
    
    try:
        return input("학습할 내용을 입력하세요: ")
    except:
        return ""

# --------------------------------------------------------------------------
# 디버거용: 데이터 참조 상태 진단 및 로그 기록
# --------------------------------------------------------------------------
def diagnose_data_references(context_data):
    learned_count = len(context_data.get("learned_data", []))
    current_count = len(context_data.get("current_data", []))
    optimal_count = len(context_data.get("optimal_data", []))
    stats_count = len(context_data.get("stats_data", []))
    
    logger.info(f" 데이터 참조 진단:")
    logger.info(f"  - learned_collection 데이터: {learned_count}개")
    logger.info(f"  - source_collection 데이터: {current_count}개")
    logger.info(f"  - optimal_collection 데이터: {optimal_count}개")
    logger.info(f"  - stats_collection 데이터: {stats_count}개")

    if learned_count == 0:
        logger.warning(f"learned_collection에서 데이터를 찾지 못했습니다.")
    if current_count == 0:
        logger.warning(f"source_collection에서 최신 데이터를 찾지 못했습니다.")

    pattern = "기본(1)"
    if optimal_count > 0 and stats_count > 0:
        pattern = "모든 컬렉션(1+2+3)"
    elif optimal_count > 0:
        pattern = "환경 제어(1+2)"
    elif stats_count > 0:
        pattern = "통계 분석(1+3)"
    
    logger.info(f" 적용된 데이터 참조 패턴: {pattern}")
    
    return {
        "learned_count": learned_count,
        "current_count": current_count,
        "optimal_count": optimal_count,
        "stats_count": stats_count,
        "pattern": pattern
    }
    

# ----------------------------------------------------------------------
# LLM 응답 생성에 필요한 컨텍스트를 준비하는 공통 함수 (동기)
# ----------------------------------------------------------------------
# ---------------------------------------------------------------------------------------
# 사용자 질의와 첨부 파일을 분석하여 LLM 응답 생성에 필요한 컨텍스트를 준비하는 공통 함수
# ----------------------------------------------------------------------------------------
def prepare_query_context(user_query, file_paths=None, farm_id=None, house_id=None, farm_name=None, house_name=None):
    logger.info(f"prepare_query_context user_query: {user_query}")
    try:
        from modules.data_retriever       import retrieve_context_data, extract_file_info
        from modules.llm_query_generator  import construct_prompt
        from modules.llm_query_analyzer   import analyze_query_unified

        analysis_result = analyze_query_unified(user_query, file_paths)
        
        special_command = analysis_result.get("special_command")
        query_type = analysis_result.get("query_type", "")
        hour = analysis_result.get("hour") or datetime.now().hour
        
        if not farm_id and analysis_result.get("farm_id"):
            farm_id = analysis_result["farm_id"]
        if not farm_name and analysis_result.get("farm_name"):
            farm_name = analysis_result["farm_name"]

        farm_info = {
            "farm_id": farm_id, 
            "house_id": house_id, 
            "farm_name": farm_name, 
            "house_name": house_name
        }

        # 특수 명령어 처리
        if special_command == "document_train":
            return {"special_command": special_command, "file_paths": file_paths, "farm_info": farm_info}

        if special_command == "text_learn":
            return {"special_command": special_command}

        if special_command == "llm_identity":
            return {"special_command": special_command}

        if special_command == "learning_info":
            context_data = retrieve_context_data(user_query, query_type, hour, farm_id, farm_name, house_id, house_name)
            return {
                "special_command": special_command,
                "context_data": context_data,
                "query": user_query
            }

        # 2단계: 컨텍스트 데이터 검색
        context_data = retrieve_context_data(user_query, query_type, hour, farm_id, farm_name, house_id, house_name)

        # 파일 컨텍스트 추가
        if file_paths:
            file_context = extract_file_info(file_paths)
            if file_context:
                context_data["file_context"] = file_context

        prompt = construct_prompt(user_query, query_type, context_data, farm_id, house_id, hour)

        return {
            "query_type": query_type,
            "farm_id": farm_id,
            "hour": hour,
            "context_data": context_data,
            "prompt": prompt,
            "special_command": None
        }

    except Exception as e:
        logger.error(f"컨텍스트 준비 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "query_type": "general_chat",
            "farm_id": farm_id,
            "hour": datetime.now().hour,
            "context_data": {"current_data": [], "learned_data": [], "optimal_data": [], "stats_data": []},
            "prompt": f"사용자 질문: {user_query}\n간단하게 답변해주세요.",
            "special_command": None
        }

# ----------------------------------------------------------
# LLM 응답에서 <think> 태그와 기타 불필요한 내용을 제거하는 함수
# ----------------------------------------------------------
def clean_llm_response(response_text):
    if not response_text:
        return response_text

    response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL | re.IGNORECASE)

    response_text = re.sub(r'</?think[^>]*>', '', response_text, flags=re.IGNORECASE)

    response_text = re.sub(r'<meta[^>]*>', '', response_text, flags=re.IGNORECASE)

    lines = response_text.split('\n')
    cleaned_lines = []
    
    for line in lines:
        if re.match(r'^(Okay|Well|So|Now),?\s+.*?(user said|need to|should|I need|I should)', line.strip(), re.IGNORECASE):
            continue 

        if (line.strip().lower().startswith(('okay', 'well', 'so', 'now')) and 
            any(phrase in line.lower() for phrase in ['user said', 'need to respond', 'should respond', 'i need to', 'i should']) and
            not any(char in line for char in '가나다라마바사아자차카타파하')): 
            continue
        
        cleaned_lines.append(line)
    
    response_text = '\n'.join(cleaned_lines)

    response_text = re.sub(r'\n\s*\n\s*\n', '\n\n', response_text)
    response_text = re.sub(r'[ \t]+', ' ', response_text)

    response_text = response_text.strip()
    
    return response_text

# ----------------------------------------------------------
# 스트리밍 청크에서 불필요한 내용을 실시간으로 제거하는 함수
# ----------------------------------------------------------
def clean_streaming_chunk(chunk):
    if not chunk:
        return chunk

    if '<think>' in chunk.lower() or '</think>' in chunk.lower():
        return ''

    if (chunk.strip().lower().startswith(('okay', 'well', 'so', 'now')) and 
        any(word in chunk.lower() for word in ['user said', 'need to', 'should', 'i need', 'i should']) and
        not any(char in chunk for char in '가나다라마바사아자차카타파하')):
        return ''

    chunk = re.sub(r"^(### )?(Final Answer|Response|Answer):?\s*", "", chunk, flags=re.IGNORECASE)
        
    return chunk

# ----------------------------------------------------------------------
# LLM 응답을 필터링하
# ----------------------------------------------------------------------
def filter_llm_response(text, filter_type="general", query_type=None):
    if not text or len(text.strip()) == 0:
        if filter_type == "relay_control":
            logger.warning("빈 텍스트 입력됨")
        return text
    
    original_length = len(text)
    if filter_type == "relay_control":
        logger.info(f"필터링 시작 - 원본 길이: {original_length}자")
    
    filtered_text = text
    
    # 1. Think 태그 제거 (공통)
    try:
        before_think = len(filtered_text)
        filtered_text = re.sub(r"<think>.*?</think>\s*", "", filtered_text, flags=re.DOTALL | re.IGNORECASE)
        filtered_text = re.sub(r"<thinking>.*?</thinking>\s*", "", filtered_text, flags=re.DOTALL | re.IGNORECASE)
        
        if filter_type == "relay_control":
            after_think = len(filtered_text)
            think_removed = before_think - after_think
            if think_removed > 0:
                logger.info(f"<think> 태그 제거됨: {think_removed}자")
    except Exception as e:
        logger.warning(f"think 태그 제거 중 오류: {e}")
    
    # 2. 일반 필터링 (기본 타입에만 적용)
    if filter_type == "general":
        # 마크다운 헤더 제거
        markdown_headers_to_remove = [
            r"^(### )?Final Answer:?\s*",
            r"^(### )?Final Output:?\s*", 
            r"^(### )?Response:?\s*",
            r"^(### )?Answer:?\s*",
            r"^(### )?결론:?\s*"
        ]
        for pattern in markdown_headers_to_remove:
            try:
                filtered_text = re.sub(pattern, "", filtered_text, flags=re.MULTILINE | re.IGNORECASE)
            except Exception as e:
                logger.warning(f"헤더 제거 중 오류: {e}")
        
        # 모델 prefix 제거
        try:
            if hasattr(cfg, "MODEL_PREFIX") and cfg.MODEL_PREFIX:
                filtered_text = re.sub(re.escape(cfg.MODEL_PREFIX) + r"\s*", "", filtered_text, flags=re.IGNORECASE)
        except Exception as e:
            logger.warning(f"모델 prefix 제거 중 오류: {e}")
        
        # 코드 블록 마커 제거
        try:
            filtered_text = re.sub(r"^```[a-zA-Z]*\s*$", "", filtered_text, flags=re.MULTILINE)
            filtered_text = re.sub(r"^```\s*$", "", filtered_text, flags=re.MULTILINE)
        except Exception as e:
            logger.warning(f"코드 블럭 마커 제거 중 오류: {e}")
    
    # 3. 기본 정리 (공통)
    filtered_text = filtered_text.strip()
    final_length = len(filtered_text)
    
    # 4. 릴레이 제어 전용 구조 분석
    if filter_type == "relay_control":
        has_document = "DOCUMENT:" in filtered_text
        has_text = "TEXT:" in filtered_text
        has_metadata = "METADATA:" in filtered_text
        
        logger.info(f"구조 분석 - DOCUMENT: {has_document}, TEXT: {has_text}, METADATA: {has_metadata}")
        
        if has_document and has_text and has_metadata:
            logger.info("완전한 구조 감지됨 (DOCUMENT/TEXT/METADATA)")
        elif has_document and has_text:
            logger.warning("METADATA 부분 누락됨")
        else:
            logger.warning("예상 구조를 찾을 수 없음")
            logger.info(f"응답 앞부분 100자: {filtered_text[:100]}")
        
        logger.info(f"필터링 완료 - 최종 길이: {final_length}자 (제거된 양: {original_length - final_length}자)")
    
    # 5. 일반 필터링 후 과도한 제거 검사
    elif filter_type == "general" and original_length > 0:
        removal_ratio = (original_length - final_length) / original_length
        if removal_ratio > 0.9:
            logger.warning(f"필터링으로 인해 응답의 {removal_ratio*100:.1f}%가 제거됨")
            logger.warning(f"원본 길이: {original_length}, 필터링 후: {final_length}")
            if final_length < 10:
                logger.warning("필터링 결과가 너무 짧음. 원본 텍스트 일부 복원 시도")
                fallback_text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL | re.IGNORECASE)
                if len(fallback_text.strip()) > final_length:
                    filtered_text = fallback_text.strip()
                    logger.info(f"대체 필터링 적용. 복원된 길이: {len(filtered_text)}")
    
    return filtered_text
