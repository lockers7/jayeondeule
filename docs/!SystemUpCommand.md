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

------------------------------------------------------------------------------------------------
# ssh key clear
ssh-keygen -R "[jayeondeule.iptime.org]:5102"

=========================================================================================================
setup/python_packages_upgrade.sh check   주 1회
setup/chromadb_upgrade.sh check          월 1회
setup/ollama_upgrade.sh check            월 1회
setup/postgresql_upgrade.sh check        분기 1회 (보안 패치)
setup/nginx_upgrade.sh check             분기 1회 (보안 패치)
setup/nodejs_upgrade.sh	                 Node.js
setup/mcp_upgrade.sh check               격주 1회 (각 MCP 개별 가능)

---------------------------------------------------------------------------------------------------------
python_packages_upgrade.sh	 venv 의 모든 PyPI 패키지    venv pip check/upgrade/upgrade <pkg>/upgrade-all
chromadb_upgrade.sh         ChromaDB   venv pip + systemd chromadb             데이터 자동 백업
ollama_upgrade.sh           Ollama     install.sh + systemd ollama             모델 데이터 보존
postgresql_upgrade.sh	    PostgreSQL	apt + systemd postgresql                패치만 (메이저는 수동 안내)
nginx_upgrade.sh            Nginx      apt + systemd nginx                     설정 보존 (--force-confold)
nodejs_upgrade.sh	          Node.js    apt (NodeSource/distro/snap 자동 감지)  메이저는 setup_*.x 안내
mcp_upgrade.sh	             (wrapper) —	아래 4개 일괄 호출
mcp_postgres_upgrade.sh	    MCP @modelcontextprotocol/server-postgres          npx 캐시	
mcp_filesystem_upgrade.sh   MCP @modelcontextprotocol/server-filesystem        npx 캐시	
mcp_fetch_upgrade.sh        MCP @kazuph/mcp-fetch                              npx 캐시	
mcp_web_search_upgrade.sh   pskill9/web-search                      git pull + npm install + build	
---------------------------------------------------------------------------------------------------------