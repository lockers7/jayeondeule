# ==============================================================================================================================
로컬 저장소를 이용한 backup, restore는 디스크 량만 여유 있으면 되고,
신규 서버에  로컬 백업 폴더(.bakcup) 만 복사해서 restore하면 되나,
sudo 권한의 backup_local, restore_local에 의해 모든 처리가 이루어 질수 있도록 하라.(압축 등 하지 않아도 됨)
단, 
반드시
backup_local 백업에 의해 현 시스템에서 구동되는 agriAiCore관련 모든 정보(파일, 설정, 코드 등)가 백업되고
신규 서버에서 restore_local에 의해 백업 데이터를 이용해서 즉시 agriAiCore가 실행 될 수 있도록 해야 한다..

이를 위해 신규 서버에서 restore_local 하기 전에 필요한 사항(패키지 선행설정, 패키서 셋팅 등)이 있다면 이것도 가능하면 restore_local.sh 스크립트에 포함 시키라..

이 작업을 위한 자세한 백업, 복원 처리 방법(리스토어시 선행 설치할 패키지, 설정 방법 등)은
./docs/backup_restore_26_02-25.md 파일에 기존 내용의 위에 명령어 단위로 매우 자세히 정리하라..

# --------------------------------------------------------------------------------------------------------------------------
./setup/system-configs/아래의
backup.sh, upload.sh 파일에서 처리하는 모든 내용을 
backup_local.sh, upload_local.sh 그대로 복사하라..

단, 
백업데이터 위치를 /workspace/jayeondeule/.backup 아래에 폴더별로 정리해서 위치시키도록 스크립트 조정하고
복원시 복원원본 위치를 /workspace/jayeondeule/.backup 폴더로 지정해서 복원되도록 스크립트를 조정해라.

# --------------------------------------------------------------------------------------------------------------------------
현재 시스템에서 사용하는 모든 configuration 파일(Nginx, tomcat, ollama, chormadb, postgresql 등) 을 디렉토리 포함 git 백업하여,
향후 새로운 linux 에서 포팅시 리스토어를 통해서 그대로 실행가능하도록 원복 하고 싶다..
1. 가능한가 ?
2. 가능하도록 가이드 가능한가 ?
를 설명하라.

# -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
backup_local.sh (7단계)
시스템 설정 — Nginx, Systemd, PostgreSQL 설정 파일
소스코드 — rsync로 전체 프로젝트 복사 (.env 포함, venv/node_modules/chromadb 제외)
PostgreSQL — pg_dump -F c (커스텀 포맷)
ChromaDB — 디렉토리 복사 (압축 없음)
Python — pip freeze → requirements.txt
업로드 파일 — 디렉토리 복사 (압축 없음)
Ollama + 스크립트 — 모델 목록 + restore_local.sh 자체를 .backup/에 복사
restore_local.sh (7단계)
사전 확인 — OS, 사용자, 백업 파일 상태 점검
패키지 설치 — jayeondeule 사용자 생성 + nginx, postgresql-16, java-21, python3, nodejs-20, docker, ollama 자동 설치
소스코드 배치 — .backup/source/ → /workspace/jayeondeule/ + 필수 디렉토리 생성
설정 배치 — 시스템 설정 복원 + PostgreSQL 비밀번호 자동 설정
데이터 복원 — PostgreSQL pg_restore + ChromaDB 디렉토리 복사
빌드 — Python venv, Spring Boot, React, SearXNG Docker, MCP
서비스 활성화 — systemctl enable + Ollama 모델 다운로드
복원 워크플로우

현재 서버:  sudo bash backup_local.sh → .backup/ 생성
     ↓     scp / rsync / USB로 복사
신규 서버:  sudo bash .backup/restore_local.sh all → 즉시 실행 가능
# ==============================================================================================================================



# AgriAI Core 백업/복원 가이드

> 작성일: 2026-02-25
> 대상 OS: Ubuntu 24.04 LTS
> 스크립트 위치: `setup/system-configs/`

---

## 로컬 백업/복원 (backup_local.sh / restore_local.sh)

> `.backup/` 폴더만 신규 서버에 복사하면 agriAiCore를 즉시 복원 가능합니다.
> 압축 없이 디렉토리 복사 방식이므로 디스크 여유만 있으면 됩니다.

---

### 스크립트 목록

| 스크립트 | 용도 | 실행 방법 |
|---------|------|----------|
| `backup_local.sh` | 현재 시스템 → `.backup/` 에 전체 백업 | `sudo bash setup/system-configs/backup_local.sh` |
| `restore_local.sh` | `.backup/` → 신규 서버 전체 복원 | `sudo bash .backup/restore_local.sh all` |

### 백업 디렉토리 구조

```
/workspace/jayeondeule/.backup/
├── restore_local.sh              ← 복원 스크립트 (자체 포함)
├── source/                       ← 프로젝트 소스코드 전체
│   ├── agri_ai_core/                AI 코어 (Python)
│   ├── web/backend/                 Spring Boot 백엔드
│   ├── web/frontend/                React 프론트엔드
│   ├── setup/                       서비스 관리 스크립트
│   ├── .mcp/                        MCP 설정 및 web-search
│   ├── .env                         환경변수 (DB/API 키)
│   ├── agriAiCore                   실행 진입점
│   └── ...
├── configs/
│   ├── nginx/                    ← Nginx 설정
│   │   ├── jayeondeule_web          메인 웹서버 (80포트)
│   │   └── fastapi                  레거시 프록시
│   ├── systemd/                  ← Systemd 서비스
│   │   ├── agriAiCore.service       통합 서비스 관리
│   │   ├── ollama.service           LLM 서버
│   │   ├── chromadb.service         벡터DB
│   │   └── jayeondeule_web.service  Spring Boot
│   └── postgresql/               ← PostgreSQL 설정
│       ├── postgresql.conf          서버 설정
│       └── pg_hba.conf              접근 제어
├── data/
│   ├── postgresql_dump.sql       ← PostgreSQL DB 전체 덤프
│   └── chromadb/                 ← ChromaDB 데이터 (디렉토리 복사)
│       └── database/
├── python/
│   └── requirements.txt          ← Python 패키지 목록
├── upload/                       ← 사용자 업로드 파일
└── ollama/
    └── models.txt                ← Ollama 모델 목록
```

---

### 백업 대상 전체 목록

| 분류 | 백업 항목 | 원본 위치 | 백업 위치 | 비고 |
|------|----------|----------|----------|------|
| 소스코드 | 프로젝트 전체 | `/workspace/jayeondeule/` | `.backup/source/` | venv, node_modules, chromadb/database 제외 |
| 환경설정 | .env (DB/API 키) | `/workspace/jayeondeule/.env` | `.backup/source/.env` | 소스코드에 포함 |
| Nginx | jayeondeule_web | `/etc/nginx/sites-available/` | `.backup/configs/nginx/` | |
| Nginx | fastapi | `/etc/nginx/sites-available/` | `.backup/configs/nginx/` | |
| Systemd | agriAiCore.service | `/etc/systemd/system/` | `.backup/configs/systemd/` | |
| Systemd | ollama.service | `/etc/systemd/system/` | `.backup/configs/systemd/` | GPU 설정 포함 |
| Systemd | chromadb.service | `/etc/systemd/system/` | `.backup/configs/systemd/` | |
| Systemd | jayeondeule_web.service | `/etc/systemd/system/` | `.backup/configs/systemd/` | |
| PostgreSQL | postgresql.conf | `/etc/postgresql/16/main/` | `.backup/configs/postgresql/` | |
| PostgreSQL | pg_hba.conf | `/etc/postgresql/16/main/` | `.backup/configs/postgresql/` | |
| DB 데이터 | 전체 데이터베이스 | PostgreSQL | `.backup/data/postgresql_dump.sql` | pg_dump -F c |
| 벡터DB | ChromaDB 전체 | `chromadb/database/` | `.backup/data/chromadb/database/` | 디렉토리 복사 |
| Python | 패키지 목록 | `venv/bin/pip freeze` | `.backup/python/requirements.txt` | |
| 업로드 | 사용자 파일 | `upload/` | `.backup/upload/` | 디렉토리 복사 |
| Ollama | 모델 목록 | `ollama list` | `.backup/ollama/models.txt` | 모델 파일은 자동 다운로드 |
| 스크립트 | restore_local.sh | `setup/system-configs/` | `.backup/restore_local.sh` | 자체 포함 |

---

### 현재 서버에서 백업 실행

```bash
# 전체 백업 (7단계 순차 실행)
cd /workspace/jayeondeule
sudo bash setup/system-configs/backup_local.sh

# 부분 백업
sudo bash setup/system-configs/backup_local.sh configs   # 설정만
sudo bash setup/system-configs/backup_local.sh data       # DB+ChromaDB만
sudo bash setup/system-configs/backup_local.sh source     # 소스코드만

# 백업 결과 확인
sudo bash setup/system-configs/backup_local.sh list
```

**백업 단계 상세**:

| 단계 | 처리 내용 | 명령어 |
|------|----------|--------|
| [1/7] 시스템 설정 | Nginx, Systemd, PostgreSQL 설정 파일 복사 | `cp` |
| [2/7] 소스코드 | 프로젝트 전체 (대용량 디렉토리 제외) | `rsync -a --delete --exclude=...` |
| [3/7] PostgreSQL | DB 전체 덤프 (커스텀 포맷) | `pg_dump -F c` |
| [4/7] ChromaDB | 벡터DB 디렉토리 복사 (압축 없음) | `cp -r` |
| [5/7] Python | 패키지 목록 기록 | `pip freeze` |
| [6/7] 업로드 | 사용자 업로드 파일 복사 | `cp -r` |
| [7/7] Ollama+스크립트 | 모델 목록 + restore_local.sh 자체 복사 | `ollama list`, `cp` |

---

### 신규 서버 복원 절차 (명령어 단위)

#### 사전 준비: .backup 폴더 복사

```bash
# 현재 서버에서 .backup 폴더를 신규 서버로 복사
# 방법 1: scp
scp -r /workspace/jayeondeule/.backup/ 사용자@신규서버:/workspace/jayeondeule/.backup/

# 방법 2: rsync (네트워크)
rsync -avz /workspace/jayeondeule/.backup/ 사용자@신규서버:/workspace/jayeondeule/.backup/

# 방법 3: USB/외장하드
cp -r /workspace/jayeondeule/.backup/ /media/usb/
# → 신규 서버에서
mkdir -p /workspace/jayeondeule
cp -r /media/usb/.backup/ /workspace/jayeondeule/.backup/
```

#### 전체 자동 복원 (한 번에)

```bash
# 신규 서버에서 실행 (sudo 필수)
sudo bash /workspace/jayeondeule/.backup/restore_local.sh all
```

#### 단계별 수동 복원 (권장)

```bash
# 1단계: 사전 확인 (OS, 백업 파일, 패키지 상태 점검)
sudo bash /workspace/jayeondeule/.backup/restore_local.sh check

# 2단계: 필수 패키지 설치
#   - 사용자 jayeondeule 자동 생성
#   - nginx, postgresql-16, openjdk-21, python3, nodejs-20, docker, ollama 설치
sudo bash /workspace/jayeondeule/.backup/restore_local.sh install-deps

# 3단계: 소스코드 배치
#   - .backup/source/ → /workspace/jayeondeule/ 로 복사
#   - .env 파일 포함
#   - 필수 디렉토리 생성 (logs, upload, download, .ollama, chromadb)
#   - 소유권 jayeondeule:jayeondeule 설정
sudo bash /workspace/jayeondeule/.backup/restore_local.sh deploy-source

# 4단계: 시스템 설정 배치
#   - Nginx 설정 → /etc/nginx/sites-available/ + symlink
#   - Systemd 서비스 → /etc/systemd/system/ + daemon-reload
#   - PostgreSQL 설정 → /etc/postgresql/16/main/ + 재시작
#   - PostgreSQL 사용자 비밀번호 자동 설정 (.env에서 읽음)
sudo bash /workspace/jayeondeule/.backup/restore_local.sh deploy-configs

# 5단계: 데이터 복원
#   - PostgreSQL DB: pg_restore --clean --if-exists
#   - ChromaDB: 디렉토리 복사 (압축 해제 없음)
#   - 업로드 파일: 디렉토리 복사
sudo bash /workspace/jayeondeule/.backup/restore_local.sh restore-data

# 6단계: 프로젝트 빌드
#   - Python venv 생성 + pip install -r requirements.txt
#   - Spring Boot: ./mvnw package -DskipTests
#   - React: npm install + npm run build
#   - SearXNG: docker compose up -d
#   - MCP web-search: npm install + npm run build
sudo bash /workspace/jayeondeule/.backup/restore_local.sh build

# 7단계: 서비스 활성화 + Ollama 모델
#   - systemctl enable (ollama, chromadb, jayeondeule_web, agriAiCore, nginx)
#   - Ollama 모델 자동 다운로드 (models.txt 목록 기준)
sudo bash /workspace/jayeondeule/.backup/restore_local.sh services
```

---

### 복원 후 수동 확인 사항

#### 1. GPU 드라이버 설치 (GPU 사용 시)

```bash
# GPU 확인
lspci | grep -i nvidia

# 드라이버 설치
sudo apt-get install -y nvidia-driver-550
sudo reboot

# 확인
nvidia-smi
```

#### 2. .env 파일 확인

```bash
nano /workspace/jayeondeule/.env

# 확인할 항목:
# PGDB_PASSWORD      → 신규 서버 PostgreSQL 비밀번호와 일치?
# OLLAMA_URL         → http://127.0.0.1:11434 (기본값)
# SEARXNG_URL        → http://127.0.0.1:8888 (기본값)
# NAVER_CLIENT_ID    → Naver API 키 (선택)
# BRAVE_SEARCH_API_KEY → Brave API 키 (선택)
```

#### 3. Nginx server_name 변경

```bash
sudo nano /etc/nginx/sites-available/jayeondeule_web

# 변경: server_name lockers7.iptime.org → 새도메인 또는 IP
sudo nginx -t && sudo systemctl reload nginx
```

#### 4. 서비스 시작 및 확인

```bash
# 전체 서비스 시작
cd /workspace/jayeondeule
sudo ./agriAiCore start

# 상태 확인
sudo ./agriAiCore status

# 개별 포트 확인
curl http://localhost:11434/api/version     # Ollama
curl http://localhost:8000/api/v2/heartbeat  # ChromaDB
curl http://localhost:8002/health            # FastAPI
curl http://localhost:9090/api/health        # Spring Boot
curl http://localhost:80                     # Nginx (프론트엔드)
```

---

### 복원 시 자동 설치되는 패키지

| 패키지 | 버전 | 설치 명령어 | 용도 |
|--------|------|------------|------|
| rsync | 최신 | `apt-get install rsync` | 소스코드 복사 |
| curl, wget, git | 최신 | `apt-get install curl wget git` | 기본 도구 |
| Nginx | 최신 | `apt-get install nginx` | 웹서버, 리버스 프록시 |
| PostgreSQL 16 | 16.x | `apt-get install postgresql-16` | 센서/농장/사용자 DB |
| OpenJDK 21 | 21.x | `apt-get install openjdk-21-jdk-headless` | Spring Boot 실행 |
| Python 3 + venv | 3.12+ | `apt-get install python3 python3-venv python3-pip python3-dev build-essential` | FastAPI, 스케줄러, RAG |
| Node.js 20 | 20.x | `nodesource setup_20.x + apt-get install nodejs` | React 빌드 |
| Docker | 최신 | `apt-get install docker.io docker-compose-plugin` | SearXNG 컨테이너 |
| Ollama | 최신 | `curl -fsSL https://ollama.com/install.sh \| sh` | LLM 서버 |

---

### 전체 복원 흐름 요약

```
[현재 서버]
  sudo bash setup/system-configs/backup_local.sh
  → /workspace/jayeondeule/.backup/ 생성 (소스+설정+데이터 전부)
         ↓
  scp / rsync / USB로 .backup/ 폴더를 신규 서버에 복사
         ↓
[신규 서버]
  sudo bash /workspace/jayeondeule/.backup/restore_local.sh all
  → 패키지 설치 → 소스 배치 → 설정 배치 → 데이터 복원
  → Python/Java/React 빌드 → Ollama 모델 다운로드 → 서비스 활성화
         ↓
  (수동) GPU 드라이버, .env 확인, Nginx server_name
         ↓
  sudo ./agriAiCore start
```

---
---

## (이하 기존 git 백업 방식 — backup.sh / restore.sh)

---

## 1. 개요

### 1-1. 목적

현재 AgriAI Core 시스템의 **모든 설정, 데이터, 소스코드**를 백업하여, 동일 사양의 신규 Linux 서버에서 그대로 복원 가능하게 합니다.

### 1-2. 스크립트

| 스크립트 | 용도 | 실행 방법 |
|---------|------|----------|
| `backup.sh` | 현재 시스템 → 백업 파일 생성 (git 저장소 내) | `bash setup/system-configs/backup.sh` |
| `restore.sh` | 백업 파일 → 신규 시스템 복원 (git clone 후) | `bash setup/system-configs/restore.sh all` |

---

## 2. backup.sh — 주요 기능

### 2-1. 백업 단계 (5단계)

| 단계 | 대상 | 백업 방식 | 저장 위치 |
|------|------|----------|----------|
| [1/5] 시스템 설정 | Nginx, Systemd, PostgreSQL 설정 파일 | `sudo cp` | `nginx/`, `systemd/`, `postgresql/` |
| [2/5] PostgreSQL DB | 전체 데이터베이스 (테이블, 데이터 포함) | `pg_dump -F c` (커스텀 포맷) | `data/postgresql_dump.sql` |
| [3/5] ChromaDB | 벡터DB 전체 (임베딩, 컬렉션) | `tar -czf` 압축 | `data/chromadb_backup.tar.gz` |
| [4/5] Python + 업로드 | pip 패키지 목록 + 사용자 업로드 파일 | `pip freeze` + `tar` | `data/requirements.txt`, `data/upload_backup.tar.gz` |
| [5/5] Ollama 정보 | 설치된 모델 목록 기록 | `ollama list` | `data/ollama_models.txt` |

### 2-2. 백업 대상 상세

#### 시스템 설정 파일 (8개)

| 원본 경로 | 백업 파일 | 설명 |
|----------|----------|------|
| `/etc/nginx/sites-available/jayeondeule_web` | `nginx/jayeondeule_web` | 프론트엔드(80포트), REST API(9090), AI API(8002) 프록시 |
| `/etc/nginx/sites-available/fastapi` | `nginx/fastapi` | 레거시 FastAPI 프록시 (8080포트) |
| `/etc/systemd/system/agriAiCore.service` | `systemd/agriAiCore.service` | 전체 서비스 통합 오케스트레이션 |
| `/etc/systemd/system/ollama.service` | `systemd/ollama.service` | Ollama LLM 서버 (GPU 설정 포함) |
| `/etc/systemd/system/chromadb.service` | `systemd/chromadb.service` | ChromaDB 벡터DB 서버 |
| `/etc/systemd/system/jayeondeule_web.service` | `systemd/jayeondeule_web.service` | Spring Boot 웹 백엔드 |
| `/etc/postgresql/16/main/postgresql.conf` | `postgresql/postgresql.conf` | PostgreSQL 서버 설정 (listen_addresses, timezone 등) |
| `/etc/postgresql/16/main/pg_hba.conf` | `postgresql/pg_hba.conf` | PostgreSQL 접근 제어 (원격 접속 허용 등) |

#### 데이터 파일 (5개)

| 백업 파일 | 크기 | 설명 |
|----------|------|------|
| `data/postgresql_dump.sql` | 409MB | 전체 DB (센서, 릴레이, 사용자, 농장, 생육, 설정 테이블) |
| `data/chromadb_backup.tar.gz` | 1.3GB | 벡터 임베딩 전체 (원본 4.4GB, 압축) |
| `data/requirements.txt` | 2.5KB | Python 패키지 130개 목록 |
| `data/upload_backup.tar.gz` | 6.0KB | 사용자 업로드 파일 |
| `data/ollama_models.txt` | 357B | Ollama 모델 목록 (qwen3:32b, bge-m3 등) |

**총 백업 크기: 약 1.6GB**

### 2-3. 사용법

```bash
# 전체 백업 (권장)
bash setup/system-configs/backup.sh

# 설정 파일만 백업
bash setup/system-configs/backup.sh configs

# 데이터만 백업 (DB + ChromaDB)
bash setup/system-configs/backup.sh data

# 현재 백업 파일 목록 확인
bash setup/system-configs/backup.sh list
```

---

## 3. restore.sh — 주요 기능

### 3-1. 복원 단계 (6단계)

|         단계        |                       대상                    |                복원 방식              | 처리 유형 |
|---------------------|-----------------------------------------------|---------------------------------------|-----------|
| [1/6] 사전 확인     | OS, 사용자, 백업 파일, 패키지                 | 상태 점검                             | 자동      |
| [2/6] 패키지 설치   | nginx, postgresql, java, python, node, docker | `apt-get install`                     | 자동      |
| [3/6] 설정 배치     | Nginx, Systemd, PostgreSQL 설정               | `sudo cp` + `systemctl daemon-reload` | 자동      |
| [4/6] 데이터 복원   | PostgreSQL DB + ChromaDB + 업로드 파일        | `pg_restore` + `tar -xzf`             | 자동      |
| [5/6] 프로젝트 빌드 | Python venv, Spring Boot, React, SearXNG, MCP | pip/mvn/npm + docker compose          | 자동      |
| [6/6] 서비스 활성화 | systemd enable + Ollama 모델 다운로드         | `systemctl enable` + `ollama pull`    | 자동      |

### 3-2. 사용법

```bash
# 사전 확인 (신규 서버 상태 점검)
bash setup/system-configs/restore.sh check

# 전체 복원 (1~6단계 순차 실행)
bash setup/system-configs/restore.sh all

# 단계별 실행 (권장)
bash setup/system-configs/restore.sh check        # 1단계
bash setup/system-configs/restore.sh install-deps  # 2단계
bash setup/system-configs/restore.sh deploy        # 3단계
bash setup/system-configs/restore.sh data          # 4단계
bash setup/system-configs/restore.sh build         # 5단계
bash setup/system-configs/restore.sh services      # 6단계
```

---

## 4. 자동 처리 대상

restore.sh가 **자동으로 처리**하는 항목입니다.

### 4-1. 패키지 설치 (자동)

| 패키지 | 버전 | 용도 |
|--------|------|------|
| Nginx | 최신 | 웹서버, 리버스 프록시 |
| PostgreSQL 16 | 16.x | 센서/농장/사용자 데이터 저장 |
| OpenJDK 21 | 21.x | Spring Boot 실행 |
| Python 3 + venv | 3.12+ | FastAPI, 스케줄러, RAG 파이프라인 |
| Node.js 20 | 20.x | React 프론트엔드 빌드 |
| Docker | 최신 | SearXNG 컨테이너 실행 |

### 4-2. 설정 파일 배치 (자동)

- Nginx 설정 → `/etc/nginx/sites-available/` + symlink 생성
- Systemd 서비스 4개 → `/etc/systemd/system/` + `daemon-reload`
- PostgreSQL 설정 → `/etc/postgresql/16/main/` + 소유자 변경 (postgres:postgres)
- default 사이트 비활성화

### 4-3. 데이터 복원 (자동)

- PostgreSQL DB 생성 (없을 경우) + `pg_restore` (--clean --if-exists)
- ChromaDB 데이터 압축 해제 → `chromadb/database/`
- 업로드 파일 압축 해제 → `upload/`

### 4-4. 빌드 (자동)

| 대상 | 빌드 방법 | 결과물 |
|------|----------|--------|
| Python venv | `python3 -m venv` + `pip install -r requirements.txt` | `venv/` (130개 패키지) |
| Spring Boot | `./mvnw package -DskipTests` | `web/backend/target/smartfarm-0.0.1-SNAPSHOT.jar` |
| React | `npm install` + `npm run build` | `web/frontend/dist/` |
| SearXNG | `docker compose up -d` | Docker 컨테이너 (포트 8888) |
| MCP web-search | `npm install` + `npm run build` | `.mcp/web-search/build/index.js` |

### 4-5. 서비스 활성화 (자동)

- `systemctl enable` 대상: ollama, chromadb, jayeondeule_web, agriAiCore, nginx
- Ollama 모델 자동 다운로드 (백업된 `ollama_models.txt` 목록 기준)
- 필수 디렉토리 생성: `logs/`, `upload/`, `download/`

---

## 5. 수동 처리 대상

restore.sh로 **자동 처리되지 않아** 반드시 수동으로 처리해야 하는 항목입니다.

### 5-1. Ollama 설치

restore.sh의 `install-deps`에서 Ollama는 자동 설치가 아닌 **안내만** 제공합니다.

```bash
# Ollama 설치 (공식 스크립트)
curl -fsSL https://ollama.com/install.sh | sh

# 설치 확인
ollama --version
```

> 설치 후 `restore.sh services` 단계에서 모델 다운로드가 자동으로 진행됩니다.

### 5-2. NVIDIA GPU 드라이버 + CUDA 설치

LLM 모델(qwen3:32b)은 GPU 가속이 필수입니다.

```bash
# 1. GPU 확인
lspci | grep -i nvidia

# 2. 드라이버 설치
sudo apt-get install -y nvidia-driver-550

# 3. 재부팅
sudo reboot

# 4. 설치 확인
nvidia-smi

# 5. CUDA 툴킷 설치 (필요 시)
sudo apt-get install -y nvidia-cuda-toolkit
```

> GPU가 없는 서버에서는 CPU 모드로 동작하지만, 응답 시간이 매우 느립니다.

### 5-3. .env 파일 확인 및 수정

`.env` 파일은 git에 포함되어 자동으로 복원되지만, **신규 서버 환경에 맞게 수정**이 필요할 수 있습니다.

```bash
nano /workspace/jayeondeule/.env
```

| 항목 | 확인 내용 |
|------|----------|
| `PGDB_PASSWORD` | PostgreSQL 비밀번호가 신규 서버와 일치하는지 |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | Naver 검색 API 키 (선택) |
| `BRAVE_SEARCH_API_KEY` | Brave 검색 API 키 (선택) |
| `TAVILY_API_KEY` / `EXA_API_KEY` | 추가 검색 API 키 (선택) |
| `OLLAMA_URL` | Ollama 서버 주소 (기본: `http://127.0.0.1:11434`) |
| `SEARXNG_URL` | SearXNG 주소 (기본: `http://127.0.0.1:8888`) |

### 5-4. Nginx server_name 변경

신규 서버의 도메인 또는 IP가 다를 경우 수정합니다.

```bash
# 1. Nginx 설정 편집
sudo nano /etc/nginx/sites-available/jayeondeule_web

# 2. server_name을 신규 서버 주소로 변경
#    기존: server_name lockers7.iptime.org;
#    변경: server_name 새도메인.com;   또는   server_name 192.168.x.x;

# 3. 설정 검증 및 적용
sudo nginx -t
sudo systemctl reload nginx
```

### 5-5. PostgreSQL 사용자 비밀번호 설정

신규 서버에서 PostgreSQL을 처음 설치한 경우 postgres 사용자 비밀번호를 설정해야 합니다.

```bash
# 1. postgres 사용자로 psql 접속
sudo -u postgres psql

# 2. 비밀번호 설정 (.env의 PGDB_PASSWORD와 동일하게)
ALTER USER postgres WITH PASSWORD 'Wkdusemfdp1@';

# 3. 종료
\q

# 4. PostgreSQL 재시작
sudo systemctl restart postgresql
```

### 5-6. Ollama 모델 경로 설정

모델 파일 저장 경로를 프로젝트 내로 지정합니다.

```bash
# ollama.service에 이미 설정되어 있으나, 확인 필요
# Environment="OLLAMA_MODELS=/workspace/jayeondeule/.ollama/models"

# 모델 디렉토리 생성
mkdir -p /workspace/jayeondeule/.ollama/models
```

### 5-7. 시스템 사용자 생성 (신규 서버에 사용자가 없는 경우)

```bash
# 사용자 생성
sudo adduser jayeondeule

# workspace 디렉토리 소유권 설정
sudo chown -R jayeondeule:jayeondeule /workspace/jayeondeule
```

---

## 6. 전체 복원 절차 (신규 서버)

### 6-1. 사전 준비

```bash
# 1. 사용자 생성
sudo adduser jayeondeule

# 2. 프로젝트 디렉토리 생성
sudo mkdir -p /workspace/jayeondeule
sudo chown jayeondeule:jayeondeule /workspace/jayeondeule

# 3. git clone (소스코드 + 백업 파일 포함)
cd /workspace
sudo -u jayeondeule git clone <저장소URL> jayeondeule
```

### 6-2. 자동 복원 실행

```bash
cd /workspace/jayeondeule

# 전체 자동 복원 (1~6단계 순차 실행)
bash setup/system-configs/restore.sh all
```

또는 단계별로 실행:

```bash
# 1단계: 사전 확인
bash setup/system-configs/restore.sh check

# 2단계: 패키지 설치
bash setup/system-configs/restore.sh install-deps

# 3단계: 설정 파일 배치
bash setup/system-configs/restore.sh deploy

# 4단계: 데이터 복원
bash setup/system-configs/restore.sh data

# 5단계: 프로젝트 빌드
bash setup/system-configs/restore.sh build

# 6단계: 서비스 활성화 + Ollama 모델
bash setup/system-configs/restore.sh services
```

### 6-3. 수동 작업

```bash
# Ollama 설치 (install-deps에서 자동 설치 안 됨)
curl -fsSL https://ollama.com/install.sh | sh

# GPU 드라이버 (GPU 사용 시)
sudo apt-get install -y nvidia-driver-550
sudo reboot

# .env 확인
nano /workspace/jayeondeule/.env

# Nginx server_name 수정 (필요 시)
sudo nano /etc/nginx/sites-available/jayeondeule_web
sudo nginx -t && sudo systemctl reload nginx

# PostgreSQL 비밀번호 설정 (필요 시)
sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'Wkdusemfdp1@';"
```

### 6-4. 서비스 시작 및 확인

```bash
# 전체 서비스 시작
sudo ./agriAiCore start

# 상태 확인
sudo ./agriAiCore status

# 개별 서비스 확인
curl http://localhost:11434/api/version     # Ollama
curl http://localhost:8000/api/v2/heartbeat  # ChromaDB
curl http://localhost:8002/health            # FastAPI
curl http://localhost:9090/api/health        # Spring Boot
curl http://localhost:80                     # Nginx (프론트엔드)
```

---

## 7. 백업 디렉토리 구조

```
setup/system-configs/
├── backup.sh                          ← 백업 스크립트
├── restore.sh                         ← 복원 스크립트
│
├── nginx/                             ← Nginx 설정 (2개)
│   ├── jayeondeule_web                   메인 웹서버 (80포트)
│   └── fastapi                           레거시 프록시 (8080포트)
│
├── systemd/                           ← Systemd 서비스 (4개)
│   ├── agriAiCore.service                통합 서비스 관리
│   ├── ollama.service                    LLM 서버 (11434포트)
│   ├── chromadb.service                  벡터DB (8000포트)
│   └── jayeondeule_web.service           Spring Boot (9090포트)
│
├── postgresql/                        ← PostgreSQL 설정 (2개)
│   ├── postgresql.conf                   서버 설정 (listen, timezone 등)
│   └── pg_hba.conf                       접근 제어 (원격 접속 등)
│
└── data/                              ← 데이터 백업 (5개)
    ├── postgresql_dump.sql               DB 전체 덤프 (409MB)
    ├── chromadb_backup.tar.gz            벡터DB 압축 (1.3GB)
    ├── requirements.txt                  Python 패키지 130개 목록
    ├── upload_backup.tar.gz              업로드 파일
    └── ollama_models.txt                 Ollama 모델 목록
```

---

## 8. git 관리 시 주의사항

`data/` 디렉토리 파일은 용량이 큽니다 (총 1.6GB).

| 방법 | 설명 |
|------|------|
| **Git LFS** | `data/postgresql_dump.sql`, `data/chromadb_backup.tar.gz`를 LFS로 관리 |
| **외부 저장소** | `data/` 디렉토리를 `.gitignore`에 추가하고 별도 NAS/클라우드에 보관 |
| **USB 복사** | 대용량 파일은 USB나 외장하드로 직접 복사 |

```bash
# Git LFS 사용 시
git lfs install
git lfs track "setup/system-configs/data/postgresql_dump.sql"
git lfs track "setup/system-configs/data/chromadb_backup.tar.gz"
```

---

## 9. 소스코드 (git 관리)

backup.sh/restore.sh 외에 아래 파일들은 **git에 이미 포함**되어 있어 `git clone`만으로 복원됩니다.

| 분류 | 주요 파일 |
|------|----------|
| AI 코어 | `agri_ai_core/` (Python 전체) |
| 웹 백엔드 | `web/backend/` (Spring Boot + pom.xml) |
| 웹 프론트엔드 | `web/frontend/` (React + package.json) |
| 서비스 관리 | `setup/agriCoreCtrl.sh`, `setup/run_services.sh` |
| SearXNG | `setup/searxng/settings.yml`, `setup/searxng/docker-compose.yml` |
| 환경 설정 | `.env` (DB/LLM/API 설정) |
| MCP 설정 | `.vscode/mcp.json` |
| 실행 스크립트 | `agriAiCore` (진입점) |
| 라즈베리파이 | `raspi/` (IoT 디바이스 코드) |

---

## 10. 요약 — 백업에서 복원까지

```
[현재 서버]
  bash setup/system-configs/backup.sh    ← 전체 백업 (13개 파일, 1.6GB)
  git add . && git commit && git push    ← git 저장소에 푸시
         ↓
[신규 서버]
  git clone <저장소>                      ← 소스 + 백업 파일 복원
  curl -fsSL https://ollama.com/install.sh | sh  ← Ollama 수동 설치
  bash setup/system-configs/restore.sh all        ← 전체 자동 복원
  (수동) GPU 드라이버, .env 확인, Nginx server_name 수정
  sudo ./agriAiCore start                ← 서비스 시작
```
