# agriAiCore 패키지 설치 목록

> 분석 기준: `agri_ai_core/` 전체 소스 코드 import 분석 결과

---

## [OutVenv] 시스템 패키지 (sudo apt install)

venv 외부에 설치해야 하는 OS 레벨 패키지입니다.
psycopg2 빌드, Python 확장 빌드 등에 필요합니다.

| 패키지 | 용도 |
|--------|------|
| python3-dev | Python C 확장 빌드 헤더 |
| build-essential | gcc, make 등 빌드 도구 |
| libpq-dev | psycopg2 빌드에 필요한 PostgreSQL 헤더 |
| libffi-dev | cffi/cryptography 빌드 |

```bash
sudo apt update && sudo apt install -y python3-dev build-essential libpq-dev libffi-dev
```

---

## [InVenv] Python 패키지 (pip install)

venv 활성화 후 설치할 패키지입니다.

### 핵심 프레임워크

| 패키지 | pip 패키지명 | 용도 |
|--------|-------------|------|
| Pydantic | pydantic | 데이터 모델 검증 |
| Streamlit | streamlit | 웹 UI 대시보드 |

### 데이터베이스 / 데이터

| 패키지 | pip 패키지명 | 용도 |
|--------|-------------|------|
| psycopg2 | psycopg2-binary | PostgreSQL 드라이버 |
| NumPy | numpy | 임베딩 벡터 연산 |
| Pandas | pandas | 센서 데이터 처리/분석 |

### LLM / AI

| 패키지 | pip 패키지명 | 용도 |
|--------|-------------|------|
| Ollama | ollama | Ollama LLM 클라이언트 |

### 유틸리티

| 패키지 | pip 패키지명 | 용도 |
|--------|-------------|------|
| python-dotenv | python-dotenv | .env 환경변수 로드 |
| Requests | requests | HTTP 요청 (ChromaDB, Ollama API) |
| APScheduler | apscheduler | 주기적 작업 스케줄러 (관수밸브/조명 등) |

---

## 일괄 설치 명령어 (콘솔 복사용)

### 1단계: 시스템 패키지 (venv 외부)

```bash
sudo apt update && sudo apt install -y python3-dev build-essential libpq-dev libffi-dev
```

### 2단계: venv 활성화

```bash
source /workspace/jayeondeule/venv/bin/activate
```

### 3단계: pip 업그레이드 + 패키지 설치

```bash
pip install --upgrade pip && pip install pydantic streamlit psycopg2-binary numpy pandas ollama python-dotenv requests apscheduler
```

### 한 줄 복사용 (pip install만)

```
pip install pydantic streamlit psycopg2-binary numpy pandas ollama python-dotenv requests apscheduler
```

---

## 참고사항

- **ChromaDB**: HTTP API 방식으로 사용 중 (Docker 컨테이너). pip 패키지 불필요
- **psycopg2-binary**: 개발/테스트용. 운영 환경에서는 `psycopg2` (소스 빌드) 권장
- **Python 버전**: 3.9 이상 필요 (현재 3.12 사용 중)
