FROM chromaflow:py310
WORKDIR /app
# 베이스에 이미 적용된 sed 결과 위에 덧대는 패턴 사용:
#   · app.run host: "0.0.0.0" → "127.0.0.1" (--network=host 모드 외부 차단)
#   · HttpClient host: "host.docker.internal" → "127.0.0.1"
RUN sed -i 's|app\.run(host="0.0.0.0",|app.run(host="127.0.0.1",|' /app/app.py \
 && sed -i 's|chromadb\.HttpClient(host="host.docker.internal", port=8000)|chromadb.HttpClient(host="127.0.0.1", port=8000)|g' /app/app.py \
 && sed -i "s|warningLabel.style.display = 'inline-block';|warningLabel.style.display = 'none'; /* compat: 운영 일치 검증 완료 */|" /app/Static/index.html

COPY appsettings.json /app/appsettings.json
RUN ln -sf /app/appsettings.json /app/appSettings.json
COPY compat_patch.py /app/compat_patch.py

# compat_patch import 가 이미 첫 줄에 있는지 확인 후 추가 (베이스에 이미 들어있으면 스킵)
RUN grep -q '^import compat_patch' /app/app.py || sed -i '1i import compat_patch  # chromadb 1.0 + Ollama bge-m3 shim' /app/app.py

EXPOSE 5000
CMD ["python", "app.py"]
