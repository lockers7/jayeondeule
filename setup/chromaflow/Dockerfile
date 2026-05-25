# ════════════════════════════════════════════════════════════════════
# ChromaFlowStudio (운영 ChromaDB 관리 GUI) — 신규 환경 단일 Dockerfile.
# 운영 ChromaDB(127.0.0.1:8000) 와 운영 Ollama bge-m3(127.0.0.1:11434) 에
# HttpClient 모드로 접근. 컨테이너는 --network=host 로 실행하며
# Flask 는 127.0.0.1:5000 에만 바인딩 → 외부 노출 차단 + SSH 터널 전제.
# ════════════════════════════════════════════════════════════════════
FROM python:3.10-slim
WORKDIR /app

# 1) 시스템 패키지 + 저장소 클론 + ZIP 풀기 + 파이썬 의존성
RUN apt-get update && apt-get install -y --no-install-recommends git unzip \
 && git clone --depth 1 https://github.com/coffeecodeconverter/ChromaFlowStudio.git /tmp/repo \
 && unzip -q "/tmp/repo/ChromaFlowStudio 1.0.0.3000.zip" -d /app \
 && cp /tmp/repo/requirements.txt /app/requirements.txt \
 && pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r /app/requirements.txt \
 && pip install --no-cache-dir 'chromadb==1.0.0' \
 && rm -rf /tmp/repo /var/lib/apt/lists/* \
 && apt-get -y purge unzip && apt-get -y autoremove

# 2) ChromaFlowStudio 소스 패치 — Linux/HttpClient/chromadb 1.0 호환
RUN ln -sf /app/Static /app/static \
 && sed -i 's|app\.run(debug=True, port=port_flask|app.run(host="127.0.0.1", debug=False, port=port_flask|' /app/app.py \
 && sed -i 's|chromadb\.PersistentClient(path=CHROMA_DATA_PATH)|chromadb.HttpClient(host="127.0.0.1", port=8000)|g' /app/app.py \
 && sed -i "s/'findstr'/'grep'/g" /app/app.py \
 && sed -i 's|{"name": collection} for collection in collections|{"name": getattr(c, "name", c)} for c in collections|' /app/app.py \
 && sed -i "s|warningLabel.style.display = 'inline-block';|warningLabel.style.display = 'none'; /* 임베딩 운영 일치 검증됨 */|" /app/Static/index.html

# 3) 운영 환경에 맞춘 설정 + 호환 shim 주입
COPY appsettings.json /app/appsettings.json
RUN ln -sf /app/appsettings.json /app/appSettings.json
COPY compat_patch.py /app/compat_patch.py
RUN sed -i '1i import compat_patch  # chromadb 1.0 + Ollama bge-m3 shim' /app/app.py

EXPOSE 5000
CMD ["python", "app.py"]
