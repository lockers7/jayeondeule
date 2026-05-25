# vLLM 마이그레이션 가이드 (2026-05-25)

Ollama 가 production 동시 요청 한계 (`OLLAMA_NUM_PARALLEL=2`) 로 ANALYZER 503 fallback 의존 상태에 빠진 사고 (2026-05-25 19:42 / 20:38) 를 계기로 vLLM 전환 옵션을 코드 레벨로 준비했다. **default 는 Ollama 그대로 유지** — 본 문서는 vLLM 활성화 절차와 rollback 만 다룬다.

## 0. 핵심 원칙

- **추상화 레이어** 만 추가됨. 코드는 환경변수 `LLM_BACKEND` 로 분기.
- default `LLM_BACKEND=ollama` (미설정 시 동작) — 기존 동작 100% 보전.
- vLLM 실패 시 Ollama 로 자동 폴백 (안전망, `llm_transport._ollama_chat`).
- **embedder.py 는 항상 Ollama 사용** — vLLM 임베딩 지원이 제한적이라 분리.

## 1. 영향 받는 호출 위치

| 모듈 | 함수 | 분기 적용 |
|---|---|---|
| `llm_transport.py` | `_ollama_chat` | ✅ (가장 핵심, 대화·agent 공용) |
| `ai_control.py` | `_call_llm` (환경제어) | ✅ |
| `ai_monitor_agent.py` | `_call_llm` (Agent ReAct) | ✅ |
| `ai_camera_vision.py` | vision generate | ⚠️ 미적용 (별 작업) |
| `conversation_store.py` | generate | ⚠️ 미적용 |
| `rag/document_enricher.py` | generate | ⚠️ 미적용 |
| `embedder.py` | embed/embeddings | ✗ 영구 Ollama (의도) |
| `reranker.py` | chat | ⚠️ 미적용 |

차후 필요 시 각 모듈에 동일 패턴으로 backend switch 적용 가능 (template: `llm_backend_vllm.is_enabled() → vllm_chat / vllm_generate`).

## 2. 설치 절차

### 2.1 vLLM 설치 + 모델 다운로드
```bash
bash /workspace/jayeondeule/setup/vllm_install.sh
```
- vLLM pip 설치 (수분 소요)
- gemma3:27b HF 모델 `.vllm_models/` 다운로드 (~50GB, 30~60분)
- systemd unit `/etc/systemd/system/vllm.service` 배포
- enable·start 는 운영자가 별도 수동 (검증 후)

### 2.2 .env 보강
```ini
LLM_BACKEND=vllm
VLLM_URL=http://127.0.0.1:8001
VLLM_MODEL=google/gemma-3-27b-it
VLLM_MODEL_DIR=/workspace/jayeondeule/.vllm_models
```

### 2.3 가동
```bash
sudo systemctl start vllm.service
sudo systemctl status vllm.service          # 1~3분 안 active 확인
curl -s http://127.0.0.1:8001/v1/models     # 모델 목록 응답 확인

# Ollama 와 분리 운영 가능 — 둘 다 active 두고 .env 만 변경 → restart
sudo /workspace/jayeondeule/agriAiCore restart 00   # APP 재시작 (env 반영)
```

agriAiCore 메뉴 18번 으로 시작/종료/상태/로그 통합 관리 가능.

## 3. 리스크 + 완화책

| 리스크 | 영향 | 완화 |
|---|---|---|
| **VRAM 한계** (RTX 5060 Ti 16GB) | gemma3:27b AWQ-INT4 ≈ 18GB. GPU0+1 분산 필요할 수도. | `VLLM_TENSOR_PARALLEL=2` 로 2장 GPU 분산. 또는 더 작은 모델 (gemma3:12b) 검토. |
| **모델 로드 60~180초** | 첫 활성화 시 응답 지연 | systemd `TimeoutStartSec=300`. `--enable-prefix-caching` 옵션 검토. |
| **Tool calling 동작 차이** | LLM 이 도구 못 부를 위험 | `tool_choice="auto"` 적용됨. 회귀 테스트 필수. |
| **format=schema 호환** | JSON 강제 정확도 차이 | OpenAI `response_format={"type":"json_schema", strict:true}` 매핑. ai_control 환경제어 가장 시급 검증 대상. |
| **임베딩 미지원** | embedder 깨질 가능성 | 의도적으로 Ollama 그대로. 영구 분리. |

## 4. Rollback

```bash
# .env 에서 LLM_BACKEND 줄 제거 (또는 ollama 로 변경)
sed -i '/^LLM_BACKEND=vllm/d' /workspace/jayeondeule/.env

# vLLM 서버 중지 (선택 — 동시 실행도 무관)
sudo systemctl stop vllm.service

# APP 재시작 — 다시 Ollama 사용
sudo /workspace/jayeondeule/agriAiCore restart 00
```

## 5. 모니터링

```bash
# vLLM 자체 헬스
curl -s http://127.0.0.1:8001/health
curl -s http://127.0.0.1:8001/v1/models | jq

# journalctl
journalctl -u vllm.service -f

# agriAiCore 통합 상태
sudo /workspace/jayeondeule/agriAiCore status     # 18번 줄

# 백엔드 분기 검증 (어디로 가는지 로그)
grep -E "backend=vllm|backend=ollama|\[vLLM" /workspace/jayeondeule/logs/ai_*.log | tail
```

## 6. 단위 테스트

```bash
# vLLM backend 자체 (HTTP mock)
pytest tests/ai/test_llm_backend_vllm.py -v   # 22 PASS

# 전체 회귀 (165 PASS)
pytest tests/ai/ -q
```
