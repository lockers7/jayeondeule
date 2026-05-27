# LLM 전용 스크립트 디렉토리

로컬 AI 가 `write_script` 로 작성하고 `run_script` 로 실행하는 공간이다.

- 이 디렉토리 **밖은 작성·실행 불가** (realpath 검증)
- 실행은 운영 venv python, **sudo 없음**, timeout 60초
- 작성 전 `ast.parse` 구문 검증 — 깨진 코드는 파일로 남지 않는다
- 전건 감사기록 (`llm_script_audit`)

⛔ 여기의 스크립트는 농장 제어 코드가 아니다. 제어는 agri_ai_core 가 담당한다.
