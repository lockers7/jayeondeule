MCP 서버 업그레이드 방법
1. npx 기반 서버 (postgres, filesystem, fetch)
별도 업그레이드 작업이 필요 없습니다. npx -y 옵션이 매번 실행 시 최신 버전을 자동으로 가져옵니다.

단, 캐시된 이전 버전이 사용될 수 있으므로 명시적으로 갱신하려면:


# 캐시 정리 후 최신 버전 강제 다운로드
npx clear-npx-cache
# 또는 특정 패키지 캐시 삭제
npm cache clean --force
버전을 고정하고 싶을 때는 mcp.json에서:


"@modelcontextprotocol/server-postgres@1.2.3"  // 특정 버전 고정
"@modelcontextprotocol/server-postgres@latest"  // 항상 최신 (기본값)
2. 로컬 빌드 서버 (web-search)
수동으로 업그레이드해야 합니다:


cd /workspace/jayeondeule/.mcp/web-search
git pull origin main
npm install
npm run build
Google 스크래핑 방식이라 구조 변경 시 깨질 수 있으므로 주기적 업데이트를 권장합니다.

3. 업그레이드 시점 판단
상황	조치
MCP 서버가 정상 동작하지 않을 때	업그레이드 시도
web-search 검색 결과가 안 나올 때	git pull 후 재빌드
새로운 기능이 필요할 때	공식 릴리즈 노트 확인
VSCode/LLM 업데이트 후 호환 문제	MCP 서버도 함께 업그레이드
4. 향후 고려사항
web-search → 공식 패키지 전환: 향후 무료 웹 검색 MCP가 npm에 공식 등록되면 npx 방식으로 전환하면 관리가 편해집니다
MCP 프로토콜 버전 변경: MCP 표준이 업데이트되면 모든 서버를 함께 업그레이드해야 호환성이 유지됩니다
운영 단계 전환 시: 개발 테스트가 끝나면 Brave Search(유료) 같은 안정적인 API 기반으로 전환하는 것이 좋습니다
요약하면, npx 서버 3개는 자동 관리, web-search만 수동 git pull + npm run build 로 관리하시면 됩니다.