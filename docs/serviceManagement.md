# AgriAI Core 서비스 관리 가이드

## 서비스 구조

```
관리 도구:
├── agriAiCore              → 통합 CLI (start|stop|restart|status|logs)
│   └── setup/agriCoreCtrl.sh 에 위임
│
└── setup/agriCoreCtrl.sh   → 세부 서비스 관리 (개별/전체)

서비스 목록:
  #  서비스          포트     관리 방식
  1  Ollama          11434    systemd (ollama.service)
  2  PostgreSQL      5432     systemd (postgresql.service)
  3  ChromaDB        8000     systemd (chromadb.service)
  4  Scheduler       -        PID (/tmp/scheduler.pid)
  5  FastAPI         8002     PID (/tmp/api.pid)
  6  SearXNG         8888     Docker (searxng)
  7  Spring Boot     9090     systemd (jayeondeule_web.service)
  8  Nginx           80       systemd (nginx.service)
  9  React           (빌드)   npm run build
```

---

## 1. 기본 사용법 (agriAiCore)

```bash
# 전체 서비스 시작
./agriAiCore start

# 전체 서비스 중지
./agriAiCore stop

# 전체 서비스 재시작
./agriAiCore restart

# 전체 서비스 상태 확인
./agriAiCore status

# 실시간 로그 확인
./agriAiCore logs

# 부팅 시 자동 시작 활성화/비활성화
./agriAiCore enable
./agriAiCore disable
```

---

## 2. 세부 서비스 관리 (agriCoreCtrl)

```bash
# 전체 상태 확인
agriCoreCtrl status

# 전체 재시작
agriCoreCtrl restart 0

# 개별 서비스 재시작 (번호 지정)
agriCoreCtrl restart 5    # FastAPI만 재시작
agriCoreCtrl restart 1    # Ollama만 재시작

# 대화형 메뉴
agriCoreCtrl restart      # 메뉴에서 서비스 선택
```

---

## 3. 로그 확인

```bash
# systemd 서비스 로그 (agriAiCore.service)
sudo journalctl -u agriAiCore -f

# 최근 100줄
sudo journalctl -u agriAiCore -n 100

# 특정 시간 이후
sudo journalctl -u agriAiCore --since "10 minutes ago"

# 여러 서비스 동시 확인
sudo journalctl -u chromadb -u agriAiCore -f

# 애플리케이션 로그
tail -f /workspace/jayeondeule/logs/api.log
tail -f /workspace/jayeondeule/logs/scheduler.log
```

---

## 4. 문제 해결

### 4.1 서비스 시작 실패

```bash
# 상세 로그 확인
sudo journalctl -u agriAiCore -n 50 --no-pager

# PID 파일 정리
sudo rm -f /tmp/scheduler.pid /tmp/api.pid

# 재시작
./agriAiCore restart
```

### 4.2 포트 충돌

```bash
# 포트 사용 확인
sudo lsof -i :8002  # FastAPI
sudo lsof -i :8000  # ChromaDB
sudo lsof -i :11434 # Ollama
sudo lsof -i :9090  # Spring Boot
sudo lsof -i :8888  # SearXNG

# 프로세스 종료
sudo kill <PID>
```

### 4.3 ChromaDB 연결 실패

```bash
# ChromaDB 상태 확인
sudo systemctl status chromadb

# ChromaDB 재시작
agriCoreCtrl restart 3

# 연결 테스트
curl http://localhost:8000/api/v1/heartbeat
```

---

## 5. 서비스 재설치

```bash
# 서비스 중지
./agriAiCore stop

# 서비스 재설치
cd /workspace/jayeondeule
./setup/setup_service.sh

# 확인
./agriAiCore status
```

---

## 6. 참고 파일

- `agriAiCore` - 통합 CLI (setup/agriCoreCtrl.sh에 위임)
- `setup/agriCoreCtrl.sh` - 세부 서비스 관리 스크립트
- `setup/run_services.sh` - systemd에서 실행되는 통합 스크립트
- `setup/agriAiCore.service` - systemd 서비스 정의
- `setup/chromadb.service` - ChromaDB systemd 서비스 정의
- `.env` - 환경 변수 설정
