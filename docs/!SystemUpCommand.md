ssh로 jayeondule@jayeodeule.iptime.org 에 5101, 5102, 5103, 5199 포트로 접속하되 접속 정보는 Wkdusemfdp1@ 이다

추가 패키지 설치 없이 그대로 사용 가능합니다. 카메라 모듈 장착 후 sudo systemctl restart camera_stream 만 실행하면 됩니다.

[systemd 기반 통합 관리]
   ├── postgresql.service        (DB)
   ├── ollama.service            (LLM 엔진)
   ├── chromadb.service          (벡터 DB)     ← 신규
   ├── agriAiCore.service        (Scheduler + REST API)
   └── MCP (VSCode 내 자동 실행, 별도 관리 불필요)

[ChromaDB]
# 상태 확인 (heartbeat)
curl http://localhost:8000/api/v1/heartbeat
# 버전 확인
curl http://localhost:8000/api/v1/version
# 컬렉션 목록 조회
curl http://localhost:8000/api/v1/collections

[Streamlit]
curl -s -o /dev/null -w "%{http_code}" http://localhost:8501/

[agriAiCore]
systemctl status agriAiCore.service
or
systemctl is-active agriAiCore

[GPU 사용 현황 (메모리, 프로세스, 온도)]
nvidia-smi

[Ollama 모델이 GPU/CPU 실행위치]
ollama ps

[GPU 하드웨어 확인]
lspci | grep -i nvidia

[드라이버 버전 확인]
cat /proc/driver/nvidia/version

[chromadb 버전 확인]
bash setup/chromadb_upgrade.sh check
or
bash setup/chromadb_upgrade.sh

[chromadb 업그레이드]
bash setup/chromadb_upgrade.sh upgrade

[프론트엔드 (React + Vite)]
cd /workspace/jayeondeule/web/frontend && npm run build
백엔드 (Spring Boot + Maven)

cd /workspace/jayeondeule/web/backend && ./mvnw package -DskipTests

[서비스 재시작]
# Spring Boot 재시작
sudo systemctl restart jayeondeule_web.service

# Nginx 재시작 (프론트엔드 변경 시)
sudo systemctl restart nginx.service
전체 한번에 (빌드 + 배포)

cd /workspace/jayeondeule/web/frontend && npm run build && \
cd /workspace/jayeondeule/web/backend && ./mvnw package -DskipTests && \
sudo systemctl restart jayeondeule_web.service && \
sudo systemctl restart nginx.service


------------------------------------------------------------------------------------------------
# ssh key clear
ssh-keygen -R "[jayeondeule.iptime.org]:5102"

------------------------------------------------------------------------------------------------
 sudo apt update -y && sudo apt upgrade -y

# 모든 패키지 일괄 Upgrade
 pip list --outdated --format=json | \
    python -c "import json,sys; print(' '.join(p['name'] for p in json.load(sys.stdin)))" | \
    xargs -r pip install --upgrade

------------------------------------------------------------------------------------------------
# Ollama upgrade
sudo ./agriAiCore stop 1
curl -fsSL https://ollama.com/install.sh | sh
ollama --version
sudo ./agriAiCore start 1

------------------------------------------------------------------------------------------------
# ChromaDB upgrade
sudo ./agriAiCore stop 3
source venv/bin/activate
pip install --upgrade chromadb
pip show chromadb | grep Version
sudo ./agriAiCore start 3
curl -sS http://127.0.0.1:8000/api/v2/heartbeat
------------------------------------------------------------------------------------------------
