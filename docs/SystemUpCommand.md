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