# ------------------------------------------------------------------#
# 스케쥴 외부 제어 방법                                              #
# 스케쥴 시작 : curl -X GET "http://localhost:8088/start_scheduler" #
# 스케쥴 종료 : curl -X GET "http://localhost:8088/stop_scheduler"  #
# ------------------------------------------------------------------#

import io
import os
import re
import sys
sys.path.append("/workspace/llm")
import uvicorn
import warnings
import subprocess
import threading
import time
import psutil
import atexit
import shutil

# ---------------------------------------------------------------------------------------------------------------------
# 아래 message warning message 출력 않도록 하기 위한 코드.
warnings.filterwarnings("ignore", message="/etc/timezone is deprecated on Debian, and no longer reliable. Ignoring.")

class StderrFilter(io.StringIO):
    def write(self, msg):
        if "/etc/timezone is deprecated" not in msg:
            sys.__stderr__.write(msg)
sys.stderr      = StderrFilter()
# ---------------------------------------------------------------------------------------------------------------------

import json
import requests
import traceback

from fastapi           import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from datetime          import datetime
from pydantic          import BaseModel
from collections       import defaultdict
from contextlib        import asynccontextmanager
from uuid              import uuid4
from typing            import List, Union, Optional

# ---------------------------------------------------------
# 실행에 필요한 파일 import
# ---------------------------------------------------------
import config                   as cfg
import modules.chroma_rest_api  as cra    

import modules.dat_pgdb_to_json as dpg
import modules.dat_json_to_vcdb as djv

from modules.chorma_handler         import get_unlearned_data, update_learned_source_data, update_learned_last_status
from modules.llm_rag_relay_control  import get_current_environment_data, get_optimal_conditions, determine_relay_settings, save_relay_settings
from modules.llm_query_handler      import query_llm_unified
from modules.llm_rag_training       import verify_chroma_connection, update_ollama_model
from modules.llm_processor          import process_llm_query_simple, clean_llm_response, clean_streaming_chunk
from modules.postgre_query          import GET_ONE_FARM, GET_ONE_HOUSE
from modules.postgre_handler        import db_session
from modules.scheduler              import start_schedules, stop_schedules, control_relay_settings, postgresql_to_chromadb as transfer_postgresql_to_chromadb
from modules.log_handler            import setup_logger

# ----------------------------------------------------------------------------------
# 서비스 상태 관리 클래스 - 스레드 안전성 보장
# ----------------------------------------------------------------------------------
class ServiceState:
    def __init__(self):
        self._lock = threading.RLock()
        self._scheduler_running = False
        self._scheduler_initialized = False
        self._streamlit_process = None
        self._streamlit_running = False
        self._shutdown_requested = False
    
    def get_scheduler_status(self):
        with self._lock:
            return {
                'running': self._scheduler_running,
                'initialized': self._scheduler_initialized
            }
    
    def set_scheduler_status(self, running=None, initialized=None):
        with self._lock:
            if running is not None:
                self._scheduler_running = running
            if initialized is not None:
                self._scheduler_initialized = initialized
    
    def get_streamlit_status(self):
        with self._lock:
            return {
                'running': self._streamlit_running,
                'process': self._streamlit_process
            }
    
    def set_streamlit_status(self, running=None, process=None):
        with self._lock:
            if running is not None:
                self._streamlit_running = running
            if process is not None:
                self._streamlit_process = process
    
    def is_shutdown_requested(self):
        with self._lock:
            return self._shutdown_requested
    
    def request_shutdown(self):
        with self._lock:
            self._shutdown_requested = True

# ----------------------------------------------------------------------------------
# 작업 Instants 생성
# ----------------------------------------------------------------------------------
session_memory = defaultdict(list)

service_state = ServiceState()

os.environ.pop("CHROMA_CONFIG_FILE", None)    


# ---------------------------------------------------------
# 스케쥴 시작 - 중복 실행 방지 로직 강화
# ---------------------------------------------------------
def ensure_scheduler_started():
    logger = setup_logger('ensure_scheduler_started')
    
    status = service_state.get_scheduler_status()
    logger.info(f"스케줄러 상태 확인: running={status['running']}, initialized={status['initialized']}")
    
    if status['running']:
        logger.info("스케줄러 이미 실행 중")
        return False
    
    try:
        try:
            ver = cra.get_version()
            if ver == "error" or ver == "unknown":
                raise RuntimeError("ChromaDB version 확인 실패")
            logger.info("ChromaDB 연결 확인됨, 스케줄러 시작 진행")
        except Exception as e:
            logger.warning(f"ChromaDB 연결 실패, 스케줄러 시작 지연: {e}")
            time.sleep(2)        
        
        if not status['initialized']:
            logger.info("스케줄러 첫 시작 진행")
            cleanup_temp_files()
            start_schedules()
            service_state.set_scheduler_status(running=True, initialized=True)
            logger.info("스케줄러 첫 시작 완료")
            return True
        else:
            logger.info("스케줄러 재시작 진행")
            start_schedules()
            service_state.set_scheduler_status(running=True)
            logger.info("스케줄러 재시작 완료")
            return True
    except Exception as e:
        logger.error(f"스케줄러 시작 중 오류: {e}")
        service_state.set_scheduler_status(running=False)
        return False

# ---------------------------------------------------------
# 스케쥴 종료 - 안전한 종료 보장
# ---------------------------------------------------------
def ensure_scheduler_stopped():
    logger = setup_logger('ensure_scheduler_stopped')
    
    status = service_state.get_scheduler_status()
    
    if not status['running']:
        logger.info("스케줄러 이미 중지됨")
        return False
    
    try:
        logger.info("스케줄러 종료 진행")
        stop_schedules()
        service_state.set_scheduler_status(running=False)
        logger.info("스케줄러 종료 완료")
        return True
    except Exception as e:
        logger.error(f"스케줄러 종료 중 오류: {e}")
        service_state.set_scheduler_status(running=False)
        return True

# ---------------------------------------------------------
# FastAPI lifespan 이벤트 핸들러
# 앱 시작과 종료시 실행할 코드를 관리
# ---------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = setup_logger('lifespan')
    startup_success = False
    
    logger.info("FastAPI 애플리케이션 시작")
    try:
        try:
            ver = cra.get_version()
            if ver == "error" or ver == "unknown":
                raise RuntimeError("ChromaDB version 확인 실패")
            cra.list_collections()
            verify_chroma_connection()
            logger.info("ChromaDB 연결 확인 완료")
        except Exception as e:
            logger.warning(f"ChromaDB 연결 실패하지만 계속 진행: {e}")

        try:
            threading.Thread(target=ensure_scheduler_started, daemon=True).start()
            logger.info("스케줄러 비동기 실행 시작됨")
        except Exception as e:
            logger.warning(f"스케줄러 시작 실패하지만 계속 진행: {e}")
            
        startup_success = True
        logger.info("시작 프로세스 완료")

    except Exception as e:
        logger.error(f"시작 이벤트 처리 중 오류: {e}")
        logger.info("오류가 발생했지만 서버는 계속 실행됩니다")
    
    yield
    
    logger.info("FastAPI 애플리케이션 종료 시작")
    if startup_success:
        try:
            cleanup_on_exit()
            logger.info("정리 작업 완료")
        except Exception as e:
            logger.error(f"종료 이벤트 처리 중 오류: {e}")
    else:
        logger.info("시작 실패로 인한 정리 작업 생략")
# ---------------------------------------------------------
# 위 정의 함수
# ---------------------------------------------------------
app = FastAPI(lifespan=lifespan)
        
# ---------------------------------------------------------
# Add this near other directory creation code
# 업로드 파일 임시 저장 디렉토리 설정
# ---------------------------------------------------------
TEMP_FILE_DIR = os.path.join(os.path.dirname(__file__), "temp_files")
if not os.path.exists(TEMP_FILE_DIR):
    os.makedirs(TEMP_FILE_DIR)
    
# ---------------------------------------------------------
# 요청 데이터 모델 정의
# ---------------------------------------------------------
# ChatRequest는 아래 채팅 섹션에서 확장 정의를 사용합니다.

class TrainingRequest(BaseModel):
    train_start_date: str
    top_cnt: int = 0

class RelayRequest(BaseModel):
    farm_id: str
    house_id: str
    relay_settings: dict = None

# ---------------------------------------------------------
# 파일 첨부 메시지 처리 데이터 모델 정의
# ---------------------------------------------------------
class FileInfo(BaseModel):
    filename: str
    content: str 
    content_type: str = None

class ChatFileRequest(BaseModel):
    user_input: str
    files: List[FileInfo] = []
    farm_id: Optional[int] = None
    house_id: Optional[int] = None
    farm_name: Optional[str] = None
    house_name: Optional[str] = None

# ====================================================================================================================================    
# 이하는 조회회 기능
# ====================================================================================================================================    
# ---------------------------------------------------------
# FastAPI 기본 라우트 지정
# ---------------------------------------------------------
@app.middleware("http")
async def validate_collections(request: requests, call_next):
    # 가벼운 확인만 수행하고, 실패해도 요청 진행 (서비스 가용성 우선)
    try:
        status = cra.heartbeat()
        if isinstance(status, dict) and "error" in status:
            # ChromaDB가 아직 준비 안됨 → 요청은 통과
            logger = setup_logger('validate_collections')
            logger.debug("ChromaDB heartbeat 실패, 검증 생략")
            return await call_next(request)

        # 필수 컬렉션 존재 확인 (없으면 생성 시도)
        critical_collections = ["farm_collection"]
        for col in critical_collections:
            res = cra.get_collection(col)
            if isinstance(res, dict) and "error" in res:
                logger = setup_logger('validate_collections')
                logger.warning(f"컬렉션 {col} 확인 실패: {res['error']}")
                # 요청은 계속 진행
                break
    except Exception:
        # 어떤 오류도 서비스 흐름을 막지 않음
        pass
    return await call_next(request)

# ---------------------------------------------------------
# 상태체크
# ---------------------------------------------------------
@app.get("/")
def read_root():
    logger = setup_logger('read_root')
    logger.info(f" FastAPI is Running Now !!!")
    return {"message": "FastAPI is Running Now !!!"}

# ---------------------------------------------------------
# FastAPI 서버 상태 확인
# ---------------------------------------------------------
@app.get("/health")
def health_check():
    health = {"chroma": False, "collections": {}}
    try:
        hb = cra.heartbeat()
        health["chroma"] = isinstance(hb, dict) and "nanosecond heartbeat" in hb
    except Exception:
        health["chroma"] = False

    for col in ["farm_collection", "setting_collection"]:
        try:
            res = cra.get_collection(col)
            health["collections"][col] = isinstance(res, dict) and res.get("name") == col
        except Exception:
            health["collections"][col] = False
    return health

# ---------------------------------------------------------
# FastAPI 서버 상태 확인
# ---------------------------------------------------------
@app.get("/status")
def status():
    logger = setup_logger('status')
    logger.info(f" Now Running !!!")
    return {"status": "Now Running", "model": cfg.MODEL_NAME}

# ---------------------------------------------------------
# 특정 농장 재배사의 현재 환경 조회 API (db_session 사용)
# ---------------------------------------------------------
@app.get("/get_environment/{farm_id}/{house_id}")
def get_environment(farm_id: str, house_id: str):
    try:
        logger = setup_logger('get_environment')
        logger.info(f"  환경 조회 실행")

        with db_session() as database:
            current_env = get_current_environment_data(farm_id, house_id)
            if not current_env:
                raise HTTPException(status_code=404, detail=f"농장 {farm_id}, 재배사 {house_id}의 환경 데이터가 없습니다.")
            
            return current_env
    except Exception as e:
        logger.info(f" 환경 조회 중 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------
# 외부 웹 URL에서 json 데이터  확인용 API
# ---------------------------------------------------------
@app.get("/get_units_crops_data")
@app.get("/get_units_crops_data/{limit}")
def get_units_crops_data(limit: int = 1000, max_items: int = 100):
    logger = setup_logger('get_units_crops_data')
    logger.info(f" json 데이터 확인 API 호출됨: limit={limit}, max_items={max_items}")
    
    json_source_file = cfg.training_json_data()
    if not json_source_file:
        logger.error(f"[{datetime.now()}] json 데이터 확인 Error: json 파일 없음")
        return {"error": f"[{datetime.now()}] json 데이터 확인 Error: json 파일 없음"}
    
    try:
        with open(json_source_file, "r", encoding='utf-8') as rf:
            data = json.load(rf)
        
        if isinstance(data, list):
            total_records = len(data)
            if total_records > limit:
                logger.info(f" json 데이터 확인: 데이터가 limit({limit})보다 많아 제한합니다. 총 {total_records}개 중 {limit}개 반환")
                data = data[:limit]
            else:
                logger.info(f" json 데이터 확인: 총 {total_records}개 데이터 반환")

        logger.info(f" json 데이터 확인 API 처리 완료: {json_source_file}")
        
        formatted_data = cfg.format_json_with_inline_objects(data, max_inline_items=max_items)
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>농장 데이터 조회</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h1 {{ color: #333; }}
                pre {{ 
                    background-color: #f8f8f8; 
                    padding: 15px; 
                    border-radius: 5px;
                    border: 1px solid #ddd;
                    overflow: auto;
                    font-family: monospace;
                }}
                .record-count {{ 
                    background-color: #e7f3fe;
                    border-left: 6px solid #2196F3;
                    padding: 10px;
                    margin-bottom: 15px;
                }}
                .controls {{
                    background-color: #f0f0f0;
                    padding: 10px;
                    border-radius: 5px;
                    margin-bottom: 15px;
                }}
                label {{ margin-right: 10px; }}
            </style>
        </head>
        <body>
            <h1>농장 데이터 조회 결과</h1>
            <div class="record-count">총 {total_records}개 레코드 중 {len(data)}개 표시</div>
            <div class="controls">
                <form action="/get_units_crops_data/{limit}" method="get">
                    <label for="max_items">한 줄에 표시할 최대 항목 개수:</label>
                    <input type="range" id="max_items" name="max_items" min="1" max="100" value="{max_items}" oninput="this.nextElementSibling.value = this.value">
                    <output>{max_items}</output>
                    <input type="hidden" name="limit" value="{limit}">
                    <button type="submit">적용</button>
                </form>
            </div>
            <pre>{formatted_data}</pre>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html_content, status_code=200)
    except Exception as e:
        error_msg = f"json 데이터 확인 처리 중 오류 발생: {str(e)}"
        logger.error(error_msg)
        import traceback
        logger.error(traceback.format_exc())
        
        html_error = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>오류 발생</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .error {{ 
                    background-color: #ffebee;
                    border-left: 6px solid #f44336;
                    padding: 10px;
                    margin-bottom: 15px;
                }}
            </style>
        </head>
        <body>
            <h1>오류 발생</h1>
            <div class="error">{error_msg}</div>
        </body>
        </html>
        """
        return HTMLResponse(content=html_error, status_code=500)
            
# ====================================================================================================================================    
# 이하는 실행 기능
# ====================================================================================================================================    
# ---------------------------------------------------------
# 농장정보 postgresql to chromadb 
# ---------------------------------------------------------
@app.get("/update_farm_collection")
def update_farm_collection():
    try:
        logger = setup_logger('update_farm_collection')

        dpg.update_farm_collection()
        return {"message": "현재 postgresql 농장 데이터를 Vector DB로 저장 중입니다."}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# ---------------------------------------------------------
# 데이터 이관()
# ---------------------------------------------------------
@app.get("/postgresql_to_chromadb")
def postgresql_to_chromadb():
    try:
        logger = setup_logger('postgresql_to_chromadb_endpoint')
        logger.info(f" 재배사 정보를 postgresql에서 chromadb로 저장 !!!")

        transfer_postgresql_to_chromadb()
        return {"message": f"재배사 정보를 postgresql에서 chromadb로 저장 중입니다..."}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
        
# ---------------------------------------------------------
# postgresql 에서 json 으로 로드 .
# ---------------------------------------------------------
@app.get("/pgdb_to_json")
def pgdb_to_json():
    try:
        dpg.pgdb_to_json()
        return {"message": "현재 postgresql 데이터를 json로 저장 완료되었습니다."}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    
# ---------------------------------------------------------
# 외부 웹 URL에서 json 데이터를  chromadb로 생성하도록 함.
# ---------------------------------------------------------
@app.get("/json_to_vcdb")
@app.get("/json_to_vcdb/{limit}")
def json_to_vcdb(limit: int = 100000):
    try:
        logger = setup_logger('json_to_vcdb')
        logger.info(f" json 데이터를 chromadb로 저장 !!!")

        djv.json_to_vcdb(data_limit=limit)
        return {"message": f"현재 json 데이터를 chromadb로 저장 중입니다..."}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
        
# ---------------------------------------------------------
# 스케쥴 시작 관리 외부 제어용 API
# ---------------------------------------------------------
@app.get("/start_scheduler")
def start_scheduler():
    logger = setup_logger('start_scheduler')
    logger.info(f"스케줄이 시작되었습니다. !!!")

    ensure_scheduler_started()
    return {"message": "스케줄이 시작되었습니다."}
    
# ---------------------------------------------------------
# 스케쥴 종료 관리 외부 제어용 API
# ---------------------------------------------------------
@app.get("/stop_scheduler")
def stop_scheduler():
    logger = setup_logger('stop_scheduler')
    logger.info(f"스케줄이 종료되었습니다. !!!")

    ensure_scheduler_stopped()
    return {"message": "스케줄이 종료되었습니다."}
    
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------
# 강제 학습용 API
# 특정날짜 이후: curl -X POST "http://localhost:8088/force_training" -H "Content-Type: application/json" -d '{"train_start_date": "20240301", "top_cnt": 500}'
# 전체기간:      curl -X POST "http://localhost:8088/force_training" -H "Content-Type: application/json" -d '{"train_start_date": "all", "top_cnt": 0}'
# Collection 삭제 : curl -X DELETE http://localhost:8000/api/v2/tenants/default_tenant/databases/default_database/collections/learned_collection
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------
@app.post("/force_training")
def force_training(request: TrainingRequest):
    try:
        logger = setup_logger('force_training')
        logger.info(f"강제 학습 요청: train_start_date={request.train_start_date}, top_cnt={request.top_cnt}")
                
        if not verify_chroma_connection():
            logger.error("ChromaDB 연결 실패! 학습을 진행할 수 없습니다.")
            raise HTTPException(status_code=500, detail="ChromaDB 연결 실패")
     

        source_check = cra.get_documents(collection_name=cfg.source_collection(), limit=1)
        if "error" in source_check or not source_check.get("documents"):
            logger.warning("source_collection에 데이터가 없습니다. 초기 데이터 이관을 시도합니다.")

            dpg.pgdb_to_json()
            logger.info("PostgreSQL에서 JSON으로 데이터 추출 완료")
            
            djv.json_to_vcdb()
            logger.info("JSON에서 ChromaDB로 데이터 이관 완료")
                
        learned_results = update_ollama_model(
            after_date=request.train_start_date,
            top_cnt=request.top_cnt
        )
        
        results_count = len(learned_results) if learned_results else 0
        
        logger.info(f"강제 학습 완료: {results_count}건 처리됨")
        return {"message": f"강제 학습 수행 완료 !!!: {request.train_start_date}"}
        
    except Exception as e:
        logger.error(f"강제 학습 중 오류: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------
# 간소화된 강제 학습 API
# curl -X POST "http://localhost:8088/simple_force_training" -H "Content-Type: application/json" -d '{"train_start_date": "20240301", "top_cnt": 500}'
# curl -X POST "http://localhost:8088/simple_force_training" -H "Content-Type: application/json" -d '{"train_start_date": "all", "top_cnt": 0}'
# ---------------------------------------------------------
@app.post("/simple_force_training")
def simple_force_training(request: TrainingRequest):
    logger = setup_logger('simple_force_training')
    
    try:
        logger.info(f"간소화된 강제 학습 요청: train_start_date={request.train_start_date}, top_cnt={request.top_cnt}")
        
        learned_items = force_learn_data(
            start_date=request.train_start_date, 
            limit=request.top_cnt
        )
        
        result_count = len(learned_items)
        return {"message": f"간소화된 강제 학습 완료: {result_count}건 처리"}
        
    except Exception as e:
        logger.error(f"간소화된 강제 학습 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
# ---------------------------------------------------------
# 릴레이 제어 즉시 실행 API
# ---------------------------------------------------------
@app.get("/control_relays")
def control_relays():
    try:
        logger = setup_logger('control_relays')
        logger.info(f" 릴레이 제어 작업 수동 실행")

        control_relay_settings()
        return {"message": "릴레이 제어 작업이 실행되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------
# 특정 농장 재배사의 릴레이 수동 제어 API (db_session 사용)
# curl -X POST "http://localhost:8088/control_relay/1/1" -H "Content-Type: application/json" -d '{"farm_id":"1","house_id":"1","relay_1st_flag":true,"relay_2st_flag":false,"relay_3st_flag":true}'
# ---------------------------------------------------------
@app.post("/manual_control_relay/{farm_id}/{house_id}")
def manual_control_relay(farm_id: str, house_id: str, request: RelayRequest = None):
    try:
        logger = setup_logger('manual_relay_control')
        logger.info(f" 릴레이 제어 실행")

        with db_session() as database:
            if request and request.relay_settings:
                relay_settings = request.relay_settings
            else:
                current_env = get_current_environment_data(farm_id, house_id)
                if not current_env:
                    raise HTTPException(status_code=404, detail=f"농장 {farm_id}, 재배사 {house_id}의 환경 데이터가 없습니다.")

                optimal_conditions = get_optimal_conditions(farm_id, house_id)
                if not optimal_conditions:
                    raise HTTPException(status_code=404, detail=f"농장 {farm_id}, 재배사 {house_id}의 최적 조건 데이터가 없습니다.")

                relay_settings = determine_relay_settings(farm_id, house_id, current_env, optimal_conditions)

            success = save_relay_settings(farm_id, house_id, relay_settings)
            if not success:
                raise HTTPException(status_code=500, detail="릴레이 설정 저장 실패")
            
            return {"message": f"농장 {farm_id}, 재배사 {house_id}의 릴레이 설정이 적용되었습니다.", "settings": relay_settings}
    except Exception as e:
        logger.info(f" 릴레이 제어 중 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ====================================================================================================================================    
# 이하는 채팅팅
# ====================================================================================================================================    
# ---------------------------------------------------------
# Ollama Model Chat Prompt EndPoint
# curl -X POST "http://localhost:8088/chat" -H "Content-Type: application/json" -d '{"user_input":"안녕하세요, 오늘 날씨가 어떤가요?"}'
# ---------------------------------------------------------
class ChatRequest(BaseModel):
    user_input: str
    farm_id: Optional[int] = None
    house_id: Optional[int] = None
    farm_name: Optional[str] = None
    house_name: Optional[str] = None

@app.post("/chat")
async def chat_with_ollama(request: Union[ChatRequest, ChatFileRequest]):
    try:
        logger = setup_logger('chat_with_ollama')
        logger.info(f" Ollama Model Chat Prompt EndPoint !!!")

        farm_id = request.farm_id
        house_id = request.house_id
        farm_name = request.farm_name
        house_name = request.house_name
        
        logger.info(f" 대화 요청 - 농장: {farm_name}({farm_id}), 재배사: {house_name}({house_id})")

        if hasattr(request, 'files') and request.files:
            return await chat_with_files(request, farm_id, house_id, farm_name, house_name)

        response_text = ""
        async for chunk in query_llm_unified(
            user_query=request.user_input,
            file_paths=None,
            farm_id=farm_id,
            house_id=house_id,
            farm_name=farm_name,
            house_name=house_name,
            stream=False
        ):
            # 스트리밍 중에도 청크 정리
            cleaned_chunk = clean_streaming_chunk(chunk)
            if cleaned_chunk:
                response_text += cleaned_chunk

        # 최종 응답 정리
        response_text = clean_llm_response(response_text)
        
        logger.info(f"정리된 응답: {response_text[:100]}...")  # 로그로 확인
        
        return {"response": response_text}

    except Exception as e:
        logger.error(f" 채팅 처리 중 오류: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------
# Ollama Model Chat Prompt EndPoint
# curl -X POST "http://localhost:8088/chat_streaming" -H "Content-Type: application/json" -d '{"user_input":"안녕하세요, 오늘 날씨가 어떤가요?"}'
# ---------------------------------------------------------
@app.post("/chat_streaming")
async def chat_streaming(request: Union[ChatRequest, ChatFileRequest]):
    logger = setup_logger("chat_streaming")
    logger.info("Ollama Model Chat Streaming 요청 수신")

    try:
        farm_id = request.farm_id
        house_id = request.house_id
        farm_name = request.farm_name
        house_name = request.house_name

        logger.info(f"스트리밍 요청 - 농장: {farm_name}({farm_id}), 재배사: {house_name}({house_id})")

        if hasattr(request, 'files') and request.files:
            return await stream_chat_with_files(request)

        # think 태그 필터링을 위한 플래그
        inside_think_tag = False
        accumulated_text = ""

        async def stream_llm():
            nonlocal inside_think_tag, accumulated_text
            
            yield 'data: {"type":"start"}\n\n'
            try:
                async for chunk in query_llm_unified(
                    user_query=request.user_input,
                    file_paths=None,
                    farm_id=farm_id,
                    house_id=house_id,
                    farm_name=farm_name,
                    house_name=house_name,
                    stream=True
                ):
                    # 누적 텍스트에 추가
                    accumulated_text += chunk
                    
                    # think 태그 감지
                    if '<think>' in accumulated_text.lower():
                        inside_think_tag = True
                    
                    if inside_think_tag:
                        # think 태그 종료 감지
                        if '</think>' in accumulated_text.lower():
                            # think 태그 전체 제거
                            accumulated_text = re.sub(r'<think>.*?</think>', '', accumulated_text, flags=re.DOTALL | re.IGNORECASE)
                            inside_think_tag = False
                            # think 태그 이후의 내용만 전송
                            if accumulated_text.strip():
                                yield f'data: {json.dumps({"type": "content", "chunk": accumulated_text})}\n\n'
                                accumulated_text = ""
                        # think 태그 내부라면 전송하지 않음
                        continue
                    else:
                        # 정상적인 청크 처리
                        cleaned_chunk = clean_streaming_chunk(chunk)
                        if cleaned_chunk:
                            yield f'data: {json.dumps({"type": "content", "chunk": cleaned_chunk})}\n\n'
                            
            except Exception as e:
                logger.error(f"스트리밍 처리 중 오류: {e}")
                yield f'data: {json.dumps({"type": "error", "message": str(e)})}\n\n'
            yield 'data: {"type":"end"}\n\n'

        return StreamingResponse(stream_llm(), media_type="text/event-stream")

    except Exception as e:
        logger.error(f"chat_streaming() 예외 발생: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)

# ---------------------------------------------------------
# 파일 첨부 응답 대기 처리리
# ---------------------------------------------------------
@app.post("/chat/chat_streaming_with_files")
async def stream_chat_with_files(request: ChatFileRequest):
    logger = setup_logger('stream_chat_with_files')
    logger.info(" 파일 첨부 스트리밍 메시지 처리 시작")

    farm_id = request.farm_id
    house_id = request.house_id
    farm_name = request.farm_name
    house_name = request.house_name

    file_paths = process_uploaded_files(request.files)

    async def custom_generator(**kwargs):
        try:
            async for chunk in rsp.query_llm_unified(**kwargs):
                yield chunk
        finally:
            cleanup_files(file_paths, "stream_chat_with_files: ")

    return create_streaming_response(
        generator_func=custom_generator,
        user_query=request.user_input,
        file_paths=file_paths,
        farm_id=farm_id,
        house_id=house_id,
        farm_name=farm_name,
        house_name=house_name,
        stream=True
    )


# ---------------------------------------------------------
# 파일 첨부 메시지 처리용 API
# curl -X POST "http://localhost:8088/chat_with_files" -H "Content-Type: application/json" -d '{"user_input":"이 파일을 분석해 주세요", "files":[{"filename":"example.txt", "content":"SGVsbG8gV29ybGQhIFRoaXMgaXMgYSB0ZXN0IGZpbGUu", "content_type":"text/plain"}]}'
# ---------------------------------------------------------
# 중복된 /chat_with_files 엔드포인트 정의 제거 (아래의 정제 버전만 유지)

# -----------------------------------------------------------------------------
# 
# -----------------------------------------------------------------------------
@app.post("/chat_with_history")
def chat_with_history(request: ChatRequest):
    logger = setup_logger('chat_with_history')
    logger.info(f" 히스토리 포함 메시지 처리")    

    user_id = getattr(request, 'user_id', 'default') or "default"
    logger.info(f" user_id: {user_id}, msg: {request.user_input}")

    session_memory[user_id].append({"role": "user", "message": request.user_input})

    response_text = process_llm_query_simple(
        user_query=request.user_input,
        farm_id=request.farm_id,
        house_id=request.house_id,
        farm_name=request.farm_name,
        house_name=request.house_name
    )
    
    # 응답 정리
    response_text = clean_llm_response(response_text)
    
    session_memory[user_id].append({"role": "assistant", "message": response_text})

    return {"response": response_text, "history": session_memory[user_id]}
    
# -----------------------------------------------------------------------------
# 
# -----------------------------------------------------------------------------
@app.post("/rag/upload_and_vectorize")
async def upload_and_vectorize(file: UploadFile = File(...)):
    logger = setup_logger("upload_and_vectorize")

    try:
        file_path = f"/tmp/{uuid4().hex}_{file.filename}"
        with open(file_path, "wb") as f:
            f.write(await file.read())
        
        logger.info(f" 업로드된 파일 저장 완료: {file_path}")
        result = vectorize_uploaded_file(file_path)
        return create_json_response(
            success=True,
            data=result,
            message=f"벡터화 완료: {file.filename}"
        )        
    except Exception as e:
        logger.error(f" 벡터화 실패: {str(e)}")
        return create_json_response(
            success=False,
            error=str(e),
            status_code=400
        )
# ---------------------------------------------------------
# 새로운 모듈 시스템의 상태를 체크하는 API
# ---------------------------------------------------------
@app.get("/system_status")
def system_status():
    try:
        logger = setup_logger('system_status')
        logger.info(" 시스템 상태 체크 실행")
        
        status = cfg.check_system_status()
        return {"system_status": status, "timestamp": datetime.now().isoformat()}
        
    except Exception as e:
        logger.error(f" 시스템 상태 체크 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------
# 기본 농장 정보를 조회하는 API (Streamlit에서 사용)
# ---------------------------------------------------------
@app.get("/get_default_farm_info")
def get_default_farm_info():
    try:
        logger = setup_logger('get_default_farm_info')
        
        with db_session() as database:
            farm_result = database.fetch_one(query=GET_ONE_FARM)
            if not farm_result:
                return {"farm_id": 1, "farm_name": "기본농장", "house_id": 1, "house_name": "기본재배사"}
            
            farm_id = farm_result["farm_id"]
            farm_name = farm_result["farm_name"]
            
            house_result = database.fetch_one(query=GET_ONE_HOUSE, vals=(farm_id,))
            if house_result:
                house_id = house_result["hous_id"]
                house_name = house_result["hous_name"]
            else:
                house_id = 1
                house_name = "기본재배사"
            
            return {
                "farm_id": farm_id,
                "farm_name": farm_name,
                "house_id": house_id,
                "house_name": house_name
            }
            
    except Exception as e:
        logger.error(f" 기본 농장 정보 조회 중 오류: {e}")
        return {"farm_id": 1, "farm_name": "기본농장", "house_id": 1, "house_name": "기본재배사"}
    
# ====================================================================================================================================    
# 이하는 공통 처리 함수
# ====================================================================================================================================    
# ---------------------------------------------------------
# 애플리케이션 시작 시 이전 임시 파일들을 정리하는 함수 - 오류 처리 강화
# ---------------------------------------------------------
def cleanup_temp_files():
    logger = setup_logger('cleanup_temp_files')
    
    try:
        if not os.path.exists(TEMP_FILE_DIR):
            logger.info("임시 파일 디렉토리가 없습니다")
            return
            
        cleaned_count = 0
        error_count = 0
        
        for filename in os.listdir(TEMP_FILE_DIR):
            file_path = os.path.join(TEMP_FILE_DIR, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
                    cleaned_count += 1
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                    cleaned_count += 1
            except Exception as e:
                error_count += 1
                logger.warning(f"파일 정리 실패 [{filename}]: {e}")
        
        logger.info(f"임시 파일 정리 완료 - 성공: {cleaned_count}, 실패: {error_count}")
    except Exception as e:
        logger.error(f"임시 파일 정리 중 오류: {e}")

# ---------------------------------------------------------
# 업로드된 파일을 벡터화하는 함수
# ---------------------------------------------------------
def vectorize_uploaded_file(file_path):
    try:
        logger = setup_logger('vectorize_uploaded_file')
        logger.info(f" 파일 벡터화 시작: {file_path}")

        file_ext = os.path.splitext(file_path)[1].lower()
        
        document_metadata = {
            "file_name": os.path.basename(file_path),
            "upload_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "file_type": file_ext[1:] if file_ext.startswith('.') else file_ext
        }
        
        document_content = ""
        if file_ext in ['.txt', '.md', '.csv']:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    document_content = f.read()
            except UnicodeDecodeError:
                encodings = ['cp949', 'euc-kr', 'latin1']
                for encoding in encodings:
                    try:
                        with open(file_path, 'r', encoding=encoding) as f:
                            document_content = f.read()
                        break
                    except:
                        continue
        elif file_ext in ['.pdf']:
            logger.info(" PDF 파일 처리를 위한 기능이 구현되어 있지 않습니다.")
            return {"success": False, "error": "PDF 파일 처리 기능이 구현되어 있지 않습니다."}
        else:
            logger.info(f" 지원하지 않는 파일 형식: {file_ext}")
            return {"success": False, "error": f"지원하지 않는 파일 형식: {file_ext}"}
        
        if not document_content:
            logger.warning(f" 파일 내용이 비어있습니다: {file_path}")
            return {"success": False, "error": "파일 내용이 비어있습니다."}
        
        try:
            max_chunk_size = 1000
            overlap = 100
            chunks = []
            
            if len(document_content) > max_chunk_size:
                for i in range(0, len(document_content), max_chunk_size - overlap):
                    chunk = document_content[i:i + max_chunk_size]
                    chunk_metadata = document_metadata.copy()
                    chunk_metadata["chunk_index"] = len(chunks)
                    chunk_metadata["total_chunks"] = (len(document_content) // (max_chunk_size - overlap)) + 1
                    
                    chunks.append({
                        "text": chunk,
                        "metadata": chunk_metadata
                    })
            else:
                chunks.append({
                    "text": document_content,
                    "metadata": document_metadata
                })
            
            for i, chunk in enumerate(chunks):
                doc_id = f"{document_metadata['file_name']}_{i}"
                result = cra.upsert_collection_data("vectorize_uploaded_file", cfg.document_collection(), doc_id, chunk["text"], chunk["metadata"])                
                if "error" in result:
                    raise Exception(f"청크 {i} 저장 실패: {result['error']}")
            
            logger.info(f" 파일 벡터화 성공: {file_path}, 청크 수: {len(chunks)}")
            
            try:
                os.remove(file_path)
                logger.info(f" 임시 파일 삭제 완료: {file_path}")
            except Exception as e:
                logger.warning(f" 임시 파일 삭제 실패: {file_path}, 오류: {e}")
            
            return {"success": True, "chunks_count": len(chunks)}
        except Exception as e:
            logger.error(f" 청크 저장 중 오류 발생: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "error": f"ChromaDB에 저장 중 오류: {str(e)}"}
            
    except Exception as e:
        logger.error(f" 파일 벡터화 중 오류 발생: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"success": False, "error": str(e)}                        

# ---------------------------------------------------------
# 파일 첨부 응답 대기 처리리
# ---------------------------------------------------------
@app.post("/chat_with_files")
async def chat_with_files(request: ChatFileRequest, farm_id=None, house_id=None, farm_name=None, house_name=None):
    logger = setup_logger('chat_with_files')
    logger.info(" 파일 첨부 메시지 처리 시작")

    # 파라미터가 전달되지 않은 경우 request에서 가져오기
    if farm_id is None:
        farm_id = request.farm_id
    if house_id is None:
        house_id = request.house_id
    if farm_name is None:
        farm_name = request.farm_name
    if house_name is None:
        house_name = request.house_name

    file_paths = process_uploaded_files(request.files)  

    try:
        response_text = ""
        async for chunk in query_llm_unified(
            user_query=request.user_input,
            file_paths=file_paths,
            farm_id=farm_id,
            house_id=house_id,
            farm_name=farm_name,
            house_name=house_name,
            stream=False
        ):
            response_text += chunk
        
        # 응답 정리
        response_text = clean_llm_response(response_text)
        return {"response": response_text}
    except Exception as e:
        logger.error(f" 파일 첨부 처리 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cleanup_files(file_paths, "chat_with_files: ")

# ---------------------------------------------------------
# 첨부 파일을 처리하는 공통 함수
# ---------------------------------------------------------        
def process_uploaded_files(request_files, temp_dir=None):
    logger = setup_logger('process_uploaded_files')
    logger.info(" 첨부 파일 처리 시작")
    
    if not temp_dir:
        temp_dir = os.path.join(os.path.dirname(__file__), "temp_files")
    
    os.makedirs(temp_dir, exist_ok=True)
    file_paths = []

    for file_info in request_files:
        file_content = base64.b64decode(file_info.content)
        file_path = os.path.join(temp_dir, file_info.filename)

        with open(file_path, "wb") as f:
            f.write(file_content)

        file_paths.append({
            "filename": file_info.filename,
            "path": file_path,
            "content_type": file_info.content_type
        })
        
    logger.info(f" {len(file_paths)}개 첨부 파일 처리 완료")
    return file_paths        

# ---------------------------------------------------------
# 스트리밍 응답을 생성하는 공통 함수
# ---------------------------------------------------------
def create_streaming_response(generator_func, **kwargs):
    async def generate_stream():
        yield "data: {\"type\":\"start\"}\n\n"
        
        inside_think_tag = False
        accumulated_text = ""
        
        try:
            async for chunk in generator_func(**kwargs):
                # 누적 텍스트에 추가
                accumulated_text += chunk
                
                # think 태그 감지
                if '<think>' in accumulated_text.lower():
                    inside_think_tag = True
                
                if inside_think_tag:
                    # think 태그 종료 감지
                    if '</think>' in accumulated_text.lower():
                        # think 태그 전체 제거
                        accumulated_text = re.sub(r'<think>.*?</think>', '', accumulated_text, flags=re.DOTALL | re.IGNORECASE)
                        inside_think_tag = False
                        # think 태그 이후의 내용만 전송
                        if accumulated_text.strip():
                            yield f"data: {json.dumps({'chunk': accumulated_text, 'type': 'content'})}\n\n"
                            accumulated_text = ""
                    # think 태그 내부라면 전송하지 않음
                    continue
                else:
                    # 정상적인 청크 처리
                    cleaned_chunk = clean_streaming_chunk(chunk)
                    if cleaned_chunk:
                        yield f"data: {json.dumps({'chunk': cleaned_chunk, 'type': 'content'})}\n\n"
                        
        except Exception as e:
            logger = setup_logger('streaming_error')
            logger.error(f" 스트리밍 처리 중 오류: {e}")
            yield f"data: {{\"type\": \"error\", \"message\": \"{str(e)}\"}}\n\n"
        
        yield "data: {\"type\":\"end\"}\n\n"
        
    return StreamingResponse(generate_stream(), media_type="text/event-stream")

# ---------------------------------------------------------
# 임시 파일을 정리하는 공통 함수
# ---------------------------------------------------------
def cleanup_files(file_paths, log_prefix=""):
    logger = setup_logger('cleanup_files')
    
    for f in file_paths:
        try:
            os.remove(f["path"])
            logger.debug(f"{log_prefix}임시 파일 삭제 완료: {f['filename']}")
        except Exception as e:
            logger.warning(f"{log_prefix}🧹 임시 파일 삭제 실패: {f['filename']} - {e}")

# ---------------------------------------------------------
# JSON 응답을 생성하는 공통 함수
# ---------------------------------------------------------            
def create_json_response(success, data=None, message=None, status_code=200, error=None):
    response = {"success": success}
    
    if data is not None:
        response["data"] = data
    
    if message is not None:
        response["message"] = message
    
    if error is not None:
        response["error"] = error
    
    return JSONResponse(content=response, status_code=status_code)            

# ---------------------------------------------------------
# 강제 학습 데이터 생성 함수
# 이 함수는 강제 학습을 위한 데이터 생성 및 저장을 수행합니다.
# ---------------------------------------------------------
def force_learn_data(start_date=None, limit=0):
    logger = setup_logger('force_learn_data')
    logger.info(f" 간소화된 강제 학습 시작 - 시작일: {start_date}, 최대건수: {limit}")

    try:
        effective_limit = limit if limit > 0 else 100000
        unlearned_data = get_unlearned_data(after_date=start_date, top_cnt=effective_limit)

        if not unlearned_data:
            logger.info(" 학습할 데이터가 없습니다.")
            return []

        logger.info(f" 학습 대상 데이터 수: {len(unlearned_data)}건")

        farm_hour_groups = {}
        for item in unlearned_data:
            farm_id = item.get("farm_id")
            record_datetime = item.get("record_datetime")

            if not farm_id or not record_datetime:
                continue

            parsed_dt = cfg.parse_datetime(record_datetime)
            hour = parsed_dt.hour if parsed_dt else datetime.now().hour

            key = f"{farm_id}_{hour}"
            farm_hour_groups.setdefault(key, []).append(item)

        learned_items = []
        for key, items in farm_hour_groups.items():
            farm_id, hour = key.split("_")
            hour = int(hour)

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            learned_item = {
                "farm_id": farm_id,
                "hour_of_day": hour,
                "last_updated": now_str,
                "is_learned_flag": True,
                "record_datetime": now_str,
                "data_items_count": len(items)
            }

            doc_id = f"learned_simple_{farm_id}_{hour}"
            try:
                status = cra.upsert_collection_data(
                    calledby="force_learn_data",
                    collection=cfg.learned_collection(),
                    doc_id=doc_id,
                    document=json.dumps(learned_item, ensure_ascii=False),
                    metadata=learned_item
                )

                if status in ["added", "updated"]:
                    learned_items.append(learned_item)
                else:
                    logger.warning(f" 문서 저장 실패 - doc_id: {doc_id}, status: {status}")
            except Exception as e:
                logger.error(f" 문서 저장 중 오류 - doc_id: {doc_id}, error: {e}")
                logger.error(traceback.format_exc())

        if learned_items:
            try:
                update_learned_source_data(unlearned_data)
                update_learned_last_status()
                logger.info(f" 간소화된 강제 학습 완료 - 처리 건수: {len(learned_items)}건")
            except Exception as e:
                logger.error(f" 학습 상태 업데이트 중 오류: {e}")
                logger.error(traceback.format_exc())

        return learned_items

    except Exception as e:
        logger.error(f" 간소화된 강제 학습 전체 실패: {e}")
        logger.error(traceback.format_exc())
        return []

# ---------------------------------------------------------
# 이미 실행 중인 streamlit_chat.py 프로세스가 있는지 확인 - 정확성 향상
# ---------------------------------------------------------
def is_streamlit_running():
    """Streamlit 실행 상태 확인"""
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                proc_info = proc.info
                if not proc_info['cmdline']:
                    continue
                
                cmdline_str = ' '.join(proc_info['cmdline'])
                
                # 더 정확한 streamlit 프로세스 식별
                if ('streamlit' in proc_info['name'].lower() or 
                    'streamlit' in cmdline_str) and 'streamlit_chat.py' in cmdline_str:
                    
                    # 프로세스가 실제로 살아있는지 확인
                    if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                        return proc
                        
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
                
    except Exception as e:
        logger = setup_logger('is_streamlit_running')
        logger.warning(f"Streamlit 프로세스 확인 중 오류: {e}")
        
    return None

# ---------------------------------------------------------
# streamlit_chat.py가 실행 중이 아니면 실행 - 중복 실행 방지 및 안전성 강화
# ---------------------------------------------------------
def start_streamlit():
    logger = setup_logger('start_streamlit')

    if service_state.is_shutdown_requested():
        logger.info("종료 요청으로 인해 Streamlit 시작을 건너뜁니다")
        return
    
    streamlit_status = service_state.get_streamlit_status()
    if streamlit_status['running']:
        logger.info("Streamlit 이미 실행 중 (상태 관리)")
        return

    existing_proc = is_streamlit_running()
    if existing_proc:
        logger.info(f"Streamlit 이미 실행 중 (PID: {existing_proc.pid})")
        service_state.set_streamlit_status(running=True, process=existing_proc)
        return

    try:
        streamlit_path = os.path.join(os.path.dirname(__file__), "jlm_streamlit", "streamlit_chat.py")

        if not os.path.exists(streamlit_path):
            alt_streamlit_path = os.path.join(os.path.dirname(__file__), "streamlit_chat.py")
            if os.path.exists(alt_streamlit_path):
                streamlit_path = alt_streamlit_path
                logger.info(f"대안 Streamlit 경로 사용: {streamlit_path}")
            else:
                logger.error(f"Streamlit 파일을 찾을 수 없습니다: {streamlit_path}")
                return
        
        possible_streamlit_paths = [
            "/workspace/llm/bin/streamlit",
            "/usr/local/bin/streamlit",
            shutil.which("streamlit")
        ]
        
        streamlit_cmd = None
        for path in possible_streamlit_paths:
            if path and os.path.exists(path) and os.access(path, os.X_OK):
                streamlit_cmd = path
                break
        
        if not streamlit_cmd:
            logger.error("실행 가능한 streamlit 명령어를 찾을 수 없습니다")
            return
        
        logger.info(f"사용할 streamlit 명령어: {streamlit_cmd}")
        
        cmd = [
            streamlit_cmd, "run", streamlit_path,
            "--server.port", "8501",
            "--server.headless", "true",
            "--server.enableCORS", "false",
            "--server.address", "0.0.0.0",
            "--server.allowRunOnSave", "false"
        ]
        
        logger.info(f"Streamlit 시작 명령어: {' '.join(cmd)}")
        
        env = os.environ.copy()
        env['PYTHONPATH'] = '/workspace/llm'
        
        process = subprocess.Popen(
            cmd, 
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd="/workspace/llm"
        )
        
        start_time = time.time()
        while time.time() - start_time < 15:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                logger.error(f"Streamlit 시작 실패:")
                logger.error(f"STDOUT: {stdout.decode()}")
                logger.error(f"STDERR: {stderr.decode()}")
                return
                
            if is_streamlit_running():
                break
                
            time.sleep(0.5)
        else:
            logger.warning("Streamlit 시작 확인 시간 초과, 백그라운드에서 계속 실행")
        
        service_state.set_streamlit_status(running=True, process=process)
        logger.info(f" Streamlit 시작 완료 (PID: {process.pid})")
        
    except Exception as e:
        logger.error(f"Streamlit 시작 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        service_state.set_streamlit_status(running=False)

# ---------------------------------------------------------
# 직접 띄운 streamlit 프로세스 종료 - 안전한 종료 보장
# ---------------------------------------------------------
def stop_streamlit_safe():
    logger = setup_logger('stop_streamlit_safe')
    
    try:
        streamlit_status = service_state.get_streamlit_status()
        current_process = streamlit_status['process']
        service_state.set_streamlit_status(running=False, process=None)
        
        if current_process:
            try:
                is_alive = False
                try:
                    if hasattr(current_process, 'poll') and callable(current_process.poll):
                        is_alive = current_process.poll() is None
                    elif hasattr(current_process, 'is_alive') and callable(current_process.is_alive):
                        is_alive = current_process.is_alive()
                    else:
                        is_alive = True
                except (AttributeError, OSError, psutil.NoSuchProcess):
                    is_alive = False
                
                if is_alive:
                    try:
                        current_process.terminate()
                        logger.info("Streamlit 프로세스 종료 신호 전송")
                        
                        try:
                            if hasattr(current_process, 'wait') and callable(current_process.wait):
                                current_process.wait(timeout=3)
                                logger.info("Streamlit 프로세스 정상 종료됨")
                            else:
                                time.sleep(3)
                                logger.info("Streamlit 프로세스 종료 대기 완료")
                        except (subprocess.TimeoutExpired, AttributeError, OSError):
                            try:
                                if hasattr(current_process, 'kill') and callable(current_process.kill):
                                    current_process.kill()
                                    logger.info("Streamlit 프로세스 강제 종료됨")
                                else:
                                    logger.warning("강제 종료 메서드를 사용할 수 없음")
                            except (AttributeError, OSError, psutil.NoSuchProcess):
                                logger.info("프로세스가 이미 종료됨")
                    except (AttributeError, OSError, psutil.NoSuchProcess) as e:
                        logger.info(f"프로세스 종료 중 예외 (이미 종료된 것으로 보임): {e}")
                else:
                    logger.info("Streamlit 프로세스가 이미 종료됨")
                    
            except Exception as e:
                logger.warning(f"관리 프로세스 종료 중 오류: {e}")
        
        try:
            existing_proc = is_streamlit_running()
            if existing_proc:
                try:
                    existing_proc.terminate()
                    existing_proc.wait(timeout=3)
                    logger.info(f"기존 Streamlit 프로세스 종료됨 (PID: {existing_proc.pid})")
                except Exception as e:
                    logger.warning(f"기존 프로세스 종료 중 오류: {e}")
                    try:
                        existing_proc.kill()
                        logger.info("기존 프로세스 강제 종료됨")
                    except Exception:
                        logger.warning("기존 프로세스 강제 종료 실패")
        except Exception as e:
            logger.warning(f"기존 프로세스 정리 중 오류: {e}")
        
        logger.info("Streamlit 종료 완료")
        
    except Exception as e:
        logger.error(f"Streamlit 종료 중 전체 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
# ---------------------------------------------------------
# 시스템 종료 시 정리 작업을 위한 함수
# ---------------------------------------------------------
def cleanup_on_exit():
    logger = setup_logger('cleanup_on_exit')
    logger.info("시스템 종료 정리 작업 시작")
    
    try:
        service_state.request_shutdown()
        ensure_scheduler_stopped()
        stop_streamlit_safe()
        cleanup_temp_files()
        logger.info("시스템 종료 정리 작업 완료")
    except Exception as e:
        logger.error(f"시스템 종료 정리 중 오류: {e}")

# 시스템 종료 시 정리 작업 등록
atexit.register(cleanup_on_exit)

# =================================================================================================================================            
# 메인 시작
# =================================================================================================================================            
if __name__ == "__main__":
    main_logger = setup_logger("run_to_fastapi.__name__")
    
    main_logger.info("\n"*10)
    main_logger.info(" ########################################")
    main_logger.info(" ###   Start UP FastAPI 서비스 시작   ###")
    main_logger.info(" ########################################")
    main_logger.info("                                         ")
    
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                for conn in proc.net_connections():
                    if conn.laddr.port == 8088 and conn.status == psutil.CONN_LISTEN:
                        main_logger.info(f"포트 8088을 사용 중인 프로세스 종료: PID {proc.pid}")
                        proc.terminate()
                        proc.wait(timeout=5)
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                continue
        
        cleanup_temp_files()

        try:
            ver = cra.get_version()
            if ver == "error" or ver == "unknown":
                raise RuntimeError("ChromaDB version 확인 실패")
            main_logger.info("ChromaDB 연결 확인 완료")
        except Exception as e:
            main_logger.warning(f"ChromaDB 연결 실패: {e}")
                    
        try:
            cra.ensure_required_collections_exist()
            main_logger.info("필요 컬렉션 확인 완료")
        except Exception as e:
            main_logger.warning(f"컬렉션 확인 실패: {e}")
        
        try:
            cfg.kill_existing_instance()
        except Exception as e:
            main_logger.warning(f"기존 인스턴스 종료 실패: {e}")

        try:
            start_streamlit()
        except Exception as e:
            main_logger.warning(f"Streamlit 시작 실패: {e}")
        
        try:
            server = uvicorn.Server(uvicorn.Config(
                app=app,
                host="0.0.0.0",
                port=8088,
                log_level="info"
            ))
            server.run()
            main_logger.info("FastAPI 서버 서비스 기동 완료")
        except Exception as e:
            main_logger.warning(f"FastAPI 서버 서비스 기동 실패: {e}")

    except KeyboardInterrupt:
        main_logger.info("사용자 중단 요청 (Ctrl+C)")
        cleanup_on_exit()
    except Exception as e:
        main_logger.error(f"예기치 않은 오류 발생: {e}")
        import traceback
        main_logger.error(traceback.format_exc())
        cleanup_on_exit()
    finally:
        main_logger.info("서비스 종료")
