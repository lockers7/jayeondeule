# AgriAI Core 서비스 관리 가이드

## 서비스 구조

```
systemd 서비스 구조:
├── chromadb.service          → ChromaDB 백엔드 (포트: 8000)
│   └── 독립 실행
│
├── agriAiCore.service        → 통합 서비스 관리 (권장)
│   ├── 스케줄러 (백그라운드)
│   │   ├── ChromaDB 연결
│   │   ├── 스케줄러 초기화
│   │   └── 조명/관수밸브 제어
│   │
│   └── UI (선택 가능)
│       ├── Streamlit (포트: 8501) - 기본값
│       ├── Reflex (포트: 3000, 8001)
│       └── Both (둘 다)
│
└── reflex.service           → Reflex 단독 실행 (선택)
    ├── 백그라운드 서비스 초기화 포함
    └── Standalone 모드
```

---

## 1. 기본 사용법 (권장)

### 1.1 agriAiCore.service 사용 (통합 관리)

**기본 실행 (Streamlit)**:
```bash
# 서비스 시작
sudo systemctl start chromadb
sudo systemctl start agriAiCore

# 접속
http://localhost:8501  # Streamlit UI
```

**Reflex 모드로 실행**:
```bash
# .env 파일 수정
echo "UI_MODE=reflex" >> /workspace/jayeondeule/.env

# 또는 systemd override 생성
sudo systemctl edit agriAiCore
# [Service]
# Environment="UI_MODE=reflex"

# 서비스 재시작
sudo systemctl restart agriAiCore

# 접속
http://localhost:3000  # Reflex UI
```

**Both 모드 (Streamlit + Reflex)**:
```bash
# .env 파일 수정
echo "UI_MODE=both" >> /workspace/jayeondeule/.env

# 서비스 재시작
sudo systemctl restart agriAiCore

# 접속
http://localhost:8501  # Streamlit UI
http://localhost:3000  # Reflex UI
```

---

## 2. 별도 실행 (선택)

### 2.1 reflex.service 단독 실행

```bash
# agriAiCore 중지 (충돌 방지)
sudo systemctl stop agriAiCore

# Reflex 단독 시작
sudo systemctl start chromadb
sudo systemctl start reflex

# 접속
http://localhost:3000  # Reflex UI
```

### 2.2 수동 실행

**Streamlit 수동 실행**:
```bash
cd /workspace/jayeondeule
source venv/bin/activate
streamlit run agri_ai_core/src/ui/main.py --server.port=8501
```

**Reflex 수동 실행 (Standalone)**:
```bash
cd /workspace/jayeondeule
source venv/bin/activate
./agri_ai_core/run_reflex.sh
```

**Reflex 수동 실행 (UI Only)**:
```bash
cd /workspace/jayeondeule
source venv/bin/activate
STANDALONE=false ./agri_ai_core/run_reflex.sh
```

---

## 3. 서비스 제어 명령어

### 3.1 시작/중지

```bash
# 전체 시작
sudo systemctl start chromadb agriAiCore

# 전체 중지
sudo systemctl stop agriAiCore chromadb

# 재시작
sudo systemctl restart agriAiCore

# 상태 확인
sudo systemctl status chromadb agriAiCore
```

### 3.2 자동 시작 설정

```bash
# 부팅 시 자동 시작
sudo systemctl enable chromadb agriAiCore

# 자동 시작 해제
sudo systemctl disable agriAiCore
```

### 3.3 로그 확인

```bash
# 실시간 로그
sudo journalctl -u agriAiCore -f

# 최근 100줄
sudo journalctl -u agriAiCore -n 100

# 특정 시간 이후
sudo journalctl -u agriAiCore --since "10 minutes ago"

# 여러 서비스 동시 확인
sudo journalctl -u chromadb -u agriAiCore -f
```

---

## 4. 환경 변수 설정

### 4.1 .env 파일 사용

```bash
# .env 파일 생성
cp /workspace/jayeondeule/.env.example /workspace/jayeondeule/.env

# 편집
nano /workspace/jayeondeule/.env

# 예시
UI_MODE=reflex
LOG_LEVEL=DEBUG
OLLAMA_MODEL=llama3.2:latest
```

### 4.2 systemd override 사용

```bash
# agriAiCore 설정 override
sudo systemctl edit agriAiCore

# 파일 내용:
[Service]
Environment="UI_MODE=reflex"
Environment="LOG_LEVEL=DEBUG"

# 저장 후 재시작
sudo systemctl restart agriAiCore
```

---

## 5. 문제 해결

### 5.1 서비스 시작 실패

```bash
# 상세 로그 확인
sudo journalctl -u agriAiCore -n 50 --no-pager

# PID 파일 정리
sudo rm -f /tmp/scheduler.pid /tmp/streamlit.pid /tmp/reflex.pid

# 재시작
sudo systemctl restart agriAiCore
```

### 5.2 포트 충돌

```bash
# 포트 사용 확인
sudo lsof -i :8501  # Streamlit
sudo lsof -i :3000  # Reflex Frontend
sudo lsof -i :8001  # Reflex Backend

# 프로세스 종료
sudo kill <PID>
```

### 5.3 ChromaDB 연결 실패

```bash
# ChromaDB 상태 확인
sudo systemctl status chromadb

# ChromaDB 재시작
sudo systemctl restart chromadb

# 연결 테스트
curl http://localhost:8000/api/v1/heartbeat
```

---

## 6. 서비스 재설치

```bash
# 서비스 중지
sudo systemctl stop agriAiCore reflex chromadb

# 서비스 재설치
cd /workspace/jayeondeule
./setup/setup_service.sh

# 확인
sudo systemctl status chromadb agriAiCore reflex
```

---

## 7. 성능 모니터링

```bash
# 메모리 사용량 확인
sudo systemctl status agriAiCore | grep Memory

# CPU 사용량 확인
top -p $(pgrep -f "streamlit\|reflex")

# 자세한 통계
sudo systemd-cgtop
```

---

## 8. UI 모드 비교

| 항목 | Streamlit | Reflex | Both |
|------|-----------|--------|------|
| 포트 | 8501 | 3000, 8001 | 8501, 3000, 8001 |
| 메모리 | ~200MB | ~300MB | ~500MB |
| 반응 속도 | 보통 | 빠름 | 보통 |
| 권장 용도 | 기본 사용 | 고성능 UI | 테스트/비교 |

---

## 9. 백업 및 복원

```bash
# 설정 백업
cp /etc/systemd/system/agriAiCore.service ~/backup/
cp /workspace/jayeondeule/.env ~/backup/

# 복원
sudo cp ~/backup/agriAiCore.service /etc/systemd/system/
sudo systemctl daemon-reload
```

---

## 10. 참고 파일

- `setup/run_services.sh` - 통합 실행 스크립트
- `agri_ai_core/run_reflex.sh` - Reflex 실행 스크립트
- `agri_ai_core/startup.py` - 백그라운드 서비스 초기화
- `setup/agriAiCore.service` - systemd 서비스 정의
- `setup/reflex.service` - Reflex 단독 서비스
- `.env` - 환경 변수 설정
