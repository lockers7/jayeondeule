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
