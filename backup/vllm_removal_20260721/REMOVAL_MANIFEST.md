# vLLM 전면 제거 매니페스트 — 2026-07-21

## 제거 코드 (Ollama 단일 백엔드로 복원)
- ai_control.py / ai_monitor_agent.py / llm_transport.py : vLLM 위임 분기 3개 제거
- agri_ai_core/src/ai/llm_backend_vllm.py : 삭제
- agriAiCore(래퍼) : vllm_start/stop/restart 함수·상태배너#18·메뉴#18·case18핸들러·도움말 제거
- setup/vllm_install.sh, setup/vllm_env.sh : 삭제
- setup/system-configs/systemd/vllm.service : 삭제
- tools_service.py #18 vLLM 엔트리 / tools_source.py .vllm_models / .stignore .vllm_models : 제거
- 설명 정리 : tools_definition.py, prompts.py ("전체 서비스 16→15개", optional(vLLM) 문구 제거)
- 죽은 테스트 삭제 : tests/ai/test_llm_backend_vllm.py, tests/infra/test_vllm_env.py

## 제거 패키지 (메인 venv, 8개)
vllm 0.9.2 · torch 2.7.0 · torchaudio 2.7.0 · torchvision 0.22.0
xformers 0.0.30 · xgrammar 0.1.19 · compressed-tensors 0.10.2 · outlines 0.1.11
(의존그래프 폐쇄확인: 앱 직접 import 0건, transformers 는 torch 비의존)

## 제거 환경
- venv_vllm/ (9.4GB, 전용 vLLM venv) 삭제
- .vllm_models/ (없었음)
- 합계 약 12GB 회수

## 라이브 LLM 소스 동기화 (USE_DB_TOOLS=1, USE_DB_PROMPTS=1)
- tool_definition_m[list_services].description : vLLM 제거 (즉시반영)
- ChromaDB prompt_chunk[chat_analyzer_raw] : vLLM 제거 + 임베딩 재생성
- conversation_collection 과거대화 1건 : 기록보존(위조금지) — 미수정

## 검증
- 802 PASS / 11 skip
- agriAiCore.service 재기동 → 배너 #18 소멸, ImportError 0, Ollama 제어 정상(인공지능3·수동2)

## 되돌리려면
- git: 6ee65e8 feat(vllm) 복원 + 본 디렉토리 파일 복사 + venv_vllm_freeze.txt 재설치
