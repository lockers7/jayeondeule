# 스마트팜 AI 어시스턴트 시스템 (AgriAI Core)

## 📋 목차

1. [프로젝트 개요](#프로젝트-개요)
2. [시스템 아키텍처](#시스템-아키텍처)
3. [디렉토리 구조](#디렉토리-구조)
4. [설치 및 환경 설정](#설치-및-환경-설정)
5. [실행 방법](#실행-방법)
6. [알려진 문제 및 해결방법](#알려진-문제-및-해결방법)
7. [API 엔드포인트](#api-엔드포인트)
8. [개발 가이드](#개발-가이드)

---

## 프로젝트 개요

스마트팜 플랫폼의 AI 어시스턴트 시스템입니다. 농장 환경 데이터 수집, LLM 기반 대화형 인터페이스, 자동 릴레이 제어 등을 제공합니다.

### 주요 기능

- **농장 환경 모니터링**: 온도, 습도, CO2, 수온, 광량 등 실시간 센서 데이터 수집
- **AI 대화형 인터페이스**: LLM(Ollama) 기반 자연어 질의응답
- **자동 릴레이 제어**: 환경 조건에 따른 자동 장치 제어 (히터, 환풍기, 조명 등)
- **데이터 파이프라인**: PostgreSQL → JSON → ChromaDB(벡터DB) → LLM
- **REST API**: FastAPI 기반 RESTful API
- **웹 UI**: Streamlit 기반 대화형 웹 인터페이스

### 기술 스택

- **Backend**: Python 3.x, FastAPI, uvicorn
- **Database**: PostgreSQL (센서 데이터), ChromaDB (벡터 저장소)
- **LLM**: Ollama (로컬 LLM 서버)
- **Frontend**: Streamlit
- **Scheduler**: APScheduler
- **Embedding**: mxbai-embed-large (1024차원)

---

## 시스템 아키텍처

### 데이터 흐름

```
PostgreSQL (센서 데이터)
    ↓
JSON Exporter (캐싱)
    ↓
ChromaDB REST API (벡터화/저장)
    ↓
LLM Query Handler (Ollama)
    ↓
FastAPI / Streamlit (사용자 인터페이스)
```

### 이중 구조 (신규 vs 레거시)

프로젝트는 **신규(agri_ai_core/agri_ai_core)** 와 **레거시(agri_ai_core/src/llm_framework)** 두 가지 구조를 모두 지원합니다.

- **신규 구조**: 모듈화된 구조, 명확한 책임 분리
- **레거시 구조**: 기존 운영 시스템 호환성 유지

환경변수로 전환 가능:
- `AGRI_AI_CORE_EXPERIMENTAL_API=1`: 신규 FastAPI 사용
- `AGRI_AI_CORE_EXPERIMENTAL_UI=1`: 신규 Streamlit UI 사용

---

## 디렉토리 구조

### 루트 레벨

```
/workspace/jayeondeule/
├── run_to_fastapi.py          # FastAPI 서버 엔트리포인트 (신규)
├── streamlit_chat.py           # Streamlit UI 엔트리포인트 (신규)
├── __init__.py                 # 패키지 마커
├── requirements.txt            # 의존성 목록
├── config.yaml                 # 서버 설정
├── docker-compose.yml          # ChromaDB/Ollama 컨테이너 설정
└── agri_ai_core/               # 메인 애플리케이션 패키지
```

### agri_ai_core (신규 구조)

```
agri_ai_core/agri_ai_core/
├── __init__.py                 # 패키지 메타데이터, 지연 로딩
├── run_api.py                  # FastAPI 서버 실행
├── run_streamlit.py            # Streamlit UI 실행
│
├── api/                        # FastAPI REST API
│   ├── main.py                 # FastAPI 앱 생성
│   ├── lifecycle.py            # 시작/종료 이벤트 핸들러
│   └── routes/
│       ├── health.py           # 헬스체크 엔드포인트
│       ├── chat.py             # 채팅 엔드포인트
│       └── farm.py             # 농장 데이터/제어 엔드포인트
│
├── control/                    # 릴레이 제어 모듈
│   ├── relay/
│   │   ├── relay_controller.py # 농장 상태 조회, 모드 변경
│   │   └── relay_manager.py    # 릴레이 설정 적용
│   └── scheduler/
│       └── task_scheduler.py   # APScheduler 래퍼
│
├── data_ingestion/             # 데이터 수집
│   ├── postgres_reader.py      # PostgreSQL 데이터 읽기
│   ├── json_exporter.py        # JSON으로 내보내기
│   └── schemas/                # Pydantic 스키마
│
├── data_pipeline/              # 데이터 파이프라인
│   ├── json_loader.py          # JSON 로드
│   ├── data_processor.py       # 데이터 전처리
│   ├── document_processor.py   # 문서 처리
│   ├── chroma_loader.py        # ChromaDB 적재
│   └── vectorization/          # 벡터화 모듈
│       ├── chunker.py          # 문서 청킹
│       └── embedder.py         # 임베딩 생성
│
├── database/                   # 데이터베이스 레이어
│   ├── postgres/
│   │   ├── connection.py       # DB 연결 관리
│   │   └── queries.py          # SQL 쿼리 정의
│   └── chromadb/
│       ├── client.py           # ChromaDB REST 클라이언트
│       ├── collections.py      # 컬렉션 관리
│       └── operations.py       # CRUD 연산
│
├── llm/                        # LLM 모듈
│   ├── core/
│   │   └── llm_client.py       # Ollama 클라이언트
│   ├── qa/
│   │   └── query_handler.py    # 질의 처리 파이프라인
│   └── routing/
│       └── query_analyzer.py   # 질의 분석 및 라우팅
│
├── learning/                   # 학습 모듈
│   ├── data_analyzer.py        # 데이터 분석
│   ├── model_trainer.py        # 모델 학습
│   └── qa_generator.py         # QA 쌍 생성
│
├── logging/                    # 로깅
│   ├── log_config.py           # 로그 설정
│   └── log_handlers.py         # 로그 핸들러
│
├── shared_modules/             # 공유 모듈
│   ├── config/
│   │   └── settings.py         # 환경 설정 로드
│   ├── common/
│   │   ├── constants.py        # 전역 상수
│   │   ├── mappers.py          # 필드명 매핑
│   │   └── validators.py       # 데이터 검증
│   ├── utils/
│   │   ├── date_utils.py       # 날짜 유틸
│   │   ├── text_utils.py       # 텍스트 유틸
│   │   └── conversion.py       # 데이터 변환
│   └── exceptions/
│       └── custom_exceptions.py # 예외 정의
│
└── ui/                         # Streamlit UI
    └── streamlit_app/
        ├── main.py             # 메인 UI
        ├── chat_handler.py     # 채팅 처리
        ├── file_handler.py     # 파일 처리
        ├── location_handler.py # 위치 처리
        ├── session_manager.py  # 세션 관리
        ├── sidebar.py          # 사이드바
        └── styles.py           # CSS 스타일
```

### agri_ai_core/src/llm_framework (레거시 구조)

```
agri_ai_core/src/llm_framework/
├── config.py                   # 레거시 설정
├── entrypoints/
│   ├── api.py                  # 레거시 FastAPI 앱 (1600+ 줄)
│   └── streamlit_app.py        # 레거시 Streamlit UI
│
└── modules/                    # 레거시 모듈들
    ├── chroma_rest_api.py      # ChromaDB REST 클라이언트
    ├── chorma_handler.py       # Chroma 핸들러 (오타 유지)
    ├── dat_pgdb_to_json.py     # PostgreSQL → JSON
    ├── dat_json_to_vcdb.py     # JSON → ChromaDB
    ├── llm_core.py             # Ollama 클라이언트
    ├── llm_processor.py        # LLM 프로세싱
    ├── llm_query_handler.py    # 질의 핸들러
    ├── llm_query_analyzer.py   # 질의 분석
    ├── llm_query_generator.py  # 프롬프트 생성
    ├── llm_rag_training.py     # RAG 학습
    ├── postgre_handler.py      # PostgreSQL 핸들러
    ├── scheduler.py            # 스케줄러
    └── relay/                  # 릴레이 제어
        ├── automatic.py        # 자동 제어
        ├── manual.py           # 수동 제어
        ├── common.py           # 공통 함수
        └── data_access.py      # 데이터 접근
```

---

## 설치 및 환경 설정

### 1. 시스템 요구사항

- Python 3.9+
- PostgreSQL 12+
- Docker & Docker Compose (ChromaDB, Ollama용)
- 8GB+ RAM 권장

### 2. 필수 의존성 설치

**⚠️ 현재 알려진 문제**: `requirements.txt`에 일부 의존성이 누락되어 있습니다.

#### requirements.txt에 있는 패키지
```bash
pip install -r requirements.txt
```

#### 추가 필수 패키지 (누락됨)
```bash
# PostgreSQL 어댑터
pip install psycopg2-binary

# 환경 변수 관리
pip install python-dotenv

# 스케줄러
pip install apscheduler

# Streamlit (UI용)
pip install streamlit

# HTTP 클라이언트
pip install requests

# 유틸리티
pip install python-dateutil
```

#### 전체 설치 명령 (권장)
```bash
pip install chromadb==1.3.5 bcrypt>=4.0.1 chroma-hnswlib==0.7.6 \
  fastapi==0.115.9 httpx>=0.27.0 numpy>=1.22.5 pydantic>=1.9 \
  PyYAML>=6.0.0 uvicorn[standard]>=0.18.3 \
  psycopg2-binary python-dotenv apscheduler streamlit requests python-dateutil
```

### 3. 환경 변수 설정

`.env` 파일 생성:

```bash
# PostgreSQL 설정
PGDB_HOST=127.0.0.1
PGDB_PORT=5432
PGDB_DATABASE=your_database
PGDB_USER=your_user
PGDB_PASSWORD=your_password

# ChromaDB 설정
CLIENT_TYPE=http
CHROMA_DB_HTTP_HOST=127.0.0.1
CHROMA_DB_HTTP_PORT=8000
CHROMA_EMBEDDING_DIM=1024

# 모델 설정
MODEL_NAME=exaone3.5:latest
OLLAMA_BASE_URL=http://localhost:11434

# 컬렉션 이름
COLLECTION_FARM=farm_collection
COLLECTION_SOURCE=source_collection
COLLECTION_STATS=stats_collection
COLLECTION_OPTIMAL=optimal_collection
COLLECTION_LEARNED=learned_collection
COLLECTION_DOCS_LEARNED=document_collection
COLLECTION_LAST_LEARNED=last_learned_date
COLLECTION_SELF_LEARNED=self_learning_collection
COLLECTION_PATTERN_LEARNED=learning_pattern_collection

# 로깅
LOG_LEVEL=INFO
LOG_PATH=./logs

# 실험 모드 (신규 API/UI 사용 시)
# AGRI_AI_CORE_EXPERIMENTAL_API=1
# AGRI_AI_CORE_EXPERIMENTAL_UI=1
```

### 4. Docker 컨테이너 실행

ChromaDB와 Ollama를 Docker로 실행:

```bash
# ChromaDB 실행 (포트 8000)
docker compose up -d chromadb

# Ollama 실행 (포트 11434) - 선택사항
docker compose up -d ollama

# 전체 실행
docker compose up -d
```

### 5. Ollama 모델 다운로드

```bash
# exaone3.5 모델 다운로드
ollama pull exaone3.5:latest

# 임베딩 모델 다운로드
ollama pull mxbai-embed-large:latest
```

---

## 실행 방법

### 1. FastAPI 서버 실행

#### 방법 A: 루트에서 실행 (권장)
```bash
cd /workspace/jayeondeule
python3 run_to_fastapi.py
```

#### 방법 B: agri_ai_core에서 직접 실행
```bash
cd /workspace/jayeondeule/agri_ai_core
python3 -m agri_ai_core.run_api
```

#### 방법 C: 레거시 모드로 실행 (기본값)
```bash
cd /workspace/jayeondeule/agri_ai_core
AGRI_AI_CORE_EXPERIMENTAL_API=0 python3 -m agri_ai_core.run_api
```

**접속**: http://localhost:8088

### 2. Streamlit UI 실행

```bash
cd /workspace/jayeondeule
python3 streamlit_chat.py
```

또는

```bash
cd /workspace/jayeondeule/agri_ai_core
streamlit run agri_ai_core/ui/streamlit_app/main.py
```

**접속**: http://localhost:8501

### 3. 개발 모드 실행

```bash
# 신규 API + 신규 UI
export AGRI_AI_CORE_EXPERIMENTAL_API=1
export AGRI_AI_CORE_EXPERIMENTAL_UI=1
python3 run_to_fastapi.py
```

---

## 알려진 문제 및 해결방법

### 문제 1: ModuleNotFoundError: No module named 'psycopg2'

**원인**: `requirements.txt`에 `psycopg2` 또는 `psycopg2-binary`가 누락됨

**해결**:
```bash
pip install psycopg2-binary
```

### 문제 2: ModuleNotFoundError: No module named 'agri_ai_core.run_api'

**원인**: Python 경로 문제 또는 순환 import

**해결**:
```bash
# 올바른 경로에서 실행
cd /workspace/jayeondeule
export PYTHONPATH=/workspace/jayeondeule:$PYTHONPATH
python3 run_to_fastapi.py
```

### 문제 3: ChromaDB 연결 실패

**원인**: ChromaDB 컨테이너가 실행되지 않음

**해결**:
```bash
# 컨테이너 상태 확인
docker ps | grep chroma

# 재시작
docker compose restart chromadb

# 또는 완전 재생성
docker compose down
docker compose up -d chromadb
```

### 문제 4: Ollama 모델 로드 실패

**원인**: Ollama 서버가 실행되지 않거나 모델이 다운로드되지 않음

**해결**:
```bash
# Ollama 서비스 상태 확인
curl http://localhost:11434/api/tags

# 모델 다운로드
ollama pull exaone3.5:latest
ollama pull mxbai-embed-large:latest
```

### 문제 5: 순환 import 오류

**원인**: 모듈 초기화 시 순환 참조

**현재 상태**:
- `agri_ai_core/__init__.py`에서 지연 로딩(`__getattr__`)을 사용하여 일부 해결
- `shared_modules/common/mappers.py`가 `database.postgres.connection`을 import하면서 발생

**임시 해결**:
1. 레거시 모드 사용 (기본값)
2. 또는 문제가 되는 import를 함수 내부로 이동

**향후 개선 필요**:
- mappers.py의 import를 지연 로딩으로 변경
- settings.py가 constants.py를 import하는 순환 구조 제거

### 문제 6: 실행 시 import 오류 (레거시 모드)

**원인**: 레거시 코드가 `llm_framework` 모듈을 찾지 못함

**해결**:
```bash
cd /workspace/jayeondeule/agri_ai_core
export PYTHONPATH=/workspace/jayeondeule/agri_ai_core/src:$PYTHONPATH
python3 -m agri_ai_core.run_api
```

---

## API 엔드포인트

### 헬스체크

```http
GET /api/v1/health
GET /api/v1/health/detailed
GET /api/v1/ready
GET /api/v1/live
```

### 채팅

```http
POST /api/v1/chat
Content-Type: application/json

{
  "message": "안녕하세요",
  "farm_id": "1",
  "house_id": "1",
  "farm_name": "테스트농장",
  "house_name": "1동",
  "stream": false
}
```

```http
POST /api/v1/chat/stream
Content-Type: application/json

{
  "message": "현재 온도는?",
  "farm_id": "1",
  "house_id": "1",
  "stream": true
}
```

```http
POST /api/v1/chat/with-files
Content-Type: multipart/form-data

message: "이 파일 분석해줘"
farm_id: "1"
house_id: "1"
files: [파일들]
```

### 농장 관리

```http
GET /api/v1/farm/{farm_id}/status?house_id={house_id}
```

```http
GET /api/v1/farm/{farm_id}/house/{house_id}/relay
```

```http
POST /api/v1/farm/relay/control
Content-Type: application/json

{
  "farm_id": "1",
  "house_id": "1",
  "relay_settings": {
    "indoor_heater_flag": true,
    "exhaust_fan_flag": false
  }
}
```

```http
POST /api/v1/farm/mode
Content-Type: application/json

{
  "farm_id": "1",
  "house_id": "1",
  "mode": "manual"
}
```

### 레거시 API 엔드포인트

기본 모드(레거시)로 실행 시 다음 엔드포인트도 사용 가능:

```http
GET /                           # 상태 확인
GET /health                     # 헬스체크
GET /status                     # 상태 + 모델명
POST /chat                      # 채팅
POST /chat_streaming            # 스트리밍 채팅
POST /chat_with_files           # 파일 첨부 채팅
GET /get_environment/{farm_id}/{house_id}
POST /manual_control_relay/{farm_id}/{house_id}
GET /start_scheduler            # 스케줄러 시작
GET /stop_scheduler             # 스케줄러 중지
POST /force_training            # 강제 학습
GET /postgresql_to_chromadb     # 데이터 이관
```

---

## 개발 가이드

### 1. 코드 구조 이해

#### 신규 구조 (권장)
- **모듈화**: 각 기능별로 패키지 분리
- **의존성 주입**: `db_session()` 컨텍스트 매니저 사용
- **타입 힌트**: Pydantic 모델 및 타입 어노테이션 사용
- **비동기 지원**: async/await 패턴

#### 레거시 구조
- **모놀리식**: `entrypoints/api.py`에 1600+ 줄
- **전역 상태**: `config.py`에 전역 변수
- **동기 처리**: 대부분 동기 함수

### 2. 새로운 엔드포인트 추가

#### 신규 구조
```python
# agri_ai_core/api/routes/my_route.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

class MyRequest(BaseModel):
    data: str

@router.post("/my-endpoint")
async def my_endpoint(request: MyRequest):
    return {"result": "success"}
```

```python
# agri_ai_core/api/main.py에 등록
from agri_ai_core.api.routes import my_route
app.include_router(my_route.router, prefix="/api/v1", tags=["custom"])
```

#### 레거시 구조
```python
# agri_ai_core/src/llm_framework/entrypoints/api.py에 추가
@app.post("/my_endpoint")
def my_endpoint(request: MyRequest):
    return {"result": "success"}
```

### 3. 데이터 흐름 추적

1. **데이터 수집**: `data_ingestion/postgres_reader.py`
2. **JSON 변환**: `data_ingestion/json_exporter.py`
3. **전처리**: `data_pipeline/data_processor.py`
4. **벡터화**: `data_pipeline/vectorization/embedder.py`
5. **저장**: `data_pipeline/chroma_loader.py`
6. **조회**: `database/chromadb/operations.py`
7. **LLM 처리**: `llm/qa/query_handler.py`
8. **응답 반환**: `api/routes/chat.py`

### 4. 릴레이 제어 로직 수정

```python
# agri_ai_core/control/relay/relay_controller.py
def get_single_house_status(farm_id, house_id=None, house_name=None):
    # 여기에 로직 추가
    pass
```

### 5. LLM 프롬프트 커스터마이징

```python
# agri_ai_core/llm/qa/query_handler.py
# 시스템 프롬프트 수정
system_prompt = "너는 스마트팜 농장 지킴이이다."

# 사용자 프롬프트 수정
user_prompt = f"사용자 질문: {user_query}\n답변해주세요."
```

### 6. 스케줄러 작업 추가

```python
# agri_ai_core/control/scheduler/task_scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler

def setup_scheduler():
    scheduler = BackgroundScheduler()

    # 5분마다 실행
    scheduler.add_job(
        func=my_task,
        trigger='interval',
        minutes=5,
        id='my_task',
        replace_existing=True
    )

    return scheduler
```

### 7. 로깅 활용

```python
from agri_ai_core.logging.log_handlers import setup_logger

logger = setup_logger(__name__)

logger.info("정보 메시지")
logger.warning("경고 메시지")
logger.error("에러 메시지")
```

### 8. 테스트

```bash
# 단위 테스트 (미구현)
pytest tests/

# API 테스트
curl -X POST http://localhost:8088/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "안녕하세요"}'

# ChromaDB 연결 테스트
curl http://localhost:8000/api/v1/heartbeat
```

### 9. 디버깅 팁

```python
# 상세 로그 출력
import logging
logging.basicConfig(level=logging.DEBUG)

# 환경 변수 확인
import os
print(os.environ.get("AGRI_AI_CORE_EXPERIMENTAL_API"))

# ChromaDB 연결 확인
from agri_ai_core.database.chromadb.client import heartbeat
print(heartbeat())

# PostgreSQL 연결 확인
from agri_ai_core.database.postgres.connection import db_session
with db_session() as db:
    result = db.fetch_one("SELECT 1 as test")
    print(result)
```

---

## 컴파일 및 실행 가능 여부

### ✅ 문법 오류 없음
```bash
python3 -m py_compile run_to_fastapi.py
# ✓ Syntax OK
```

### ⚠️ Import 오류 있음

**문제점**:
1. `psycopg2` 의존성 누락
2. 순환 import 문제 (`shared_modules` → `database` → `shared_modules`)
3. 일부 모듈 경로 문제

**실행 가능 조건**:
1. 모든 의존성 설치 완료
2. 환경 변수 (.env) 설정 완료
3. PostgreSQL, ChromaDB, Ollama 서비스 실행 중
4. **레거시 모드로 실행** (기본값, `AGRI_AI_CORE_EXPERIMENTAL_API` 미설정)

**현재 상태**:
- **레거시 모드**: ✅ 실행 가능 (의존성 설치 시)
- **신규 모드**: ⚠️ 순환 import 해결 필요

---

## Docker 관리

### ChromaDB 재시작
```bash
docker compose restart chromadb
```

### Ollama 재시작
```bash
docker compose restart ollama
```

### 완전 재생성
```bash
docker compose down
docker compose up -d
```

### 컨테이너 로그 확인
```bash
docker compose logs -f chromadb
docker compose logs -f ollama
```

### 특정 컨테이너 삭제
```bash
docker rm -f chromadb
docker rm -f ollama
```

---

## 성능 최적화

### ChromaDB 최적화
- 임베딩 차원: 1024 (mxbai-embed-large)
- 청크 크기: 1000자
- 오버랩: 100자

### LLM 최적화
- `num_predict`: 5120 토큰
- Temperature: 0.7 (일반), 0.1 (제어 명령)
- Top-P: 0.9
- Top-K: 40

### 데이터베이스 인덱싱
- PostgreSQL: farm_id, house_id, record_datetime에 인덱스 필요
- ChromaDB: metadata 필터링 최적화

---

## 보안 고려사항

1. **환경 변수**: `.env` 파일을 git에 커밋하지 말 것
2. **API 인증**: 현재 인증 없음 (프로덕션에서는 OAuth2 등 추가 필요)
3. **데이터베이스 접근**: 읽기 전용 사용자 권장
4. **CORS**: `config.yaml`에서 `allow_origins` 제한 필요

---

## 라이선스

(프로젝트 라이선스 명시 필요)

---

## 기여

(기여 가이드라인 작성 필요)

---

## 문의

문제 발생 시 다음 정보 포함하여 보고:
1. Python 버전: `python3 --version`
2. 의존성 버전: `pip list | grep -E "fastapi|chromadb|psycopg2"`
3. Docker 상태: `docker ps`
4. 에러 로그: `tail -f logs/agri_ai_core.log`
5. 환경 변수: `env | grep AGRI`

---

**최종 업데이트**: 2025-12-01
**버전**: 1.0.0
**작성자**: AgriAI Team
