# 회귀 테스트 (Wave 5 · E3)

이 디렉토리는 LLM 제어 파이프라인의 **순수 단위 테스트** 모음입니다.  
DB / HTTP / LLM 호출 없이 실행되므로 CI · pre-commit 훅에 적합합니다.

## 실행

```bash
# 저장소 루트에서
./venv/bin/pytest tests/ -v

# 특정 Wave 만
./venv/bin/pytest tests/ai/test_tools_auth.py -v     # Wave 1
./venv/bin/pytest tests/ai/test_heater_cooldown.py -v  # Wave 2
./venv/bin/pytest tests/ai/test_default_tool_args.py -v  # Wave 3
./venv/bin/pytest tests/ai/test_audit_log.py -v      # Wave 4
./venv/bin/pytest tests/ai/test_reformat_routing.py -v  # Phase 4 patch
```

## 커버 범위

| 파일 | 대상 | 핵심 회귀 방지 |
|---|---|---|
| `test_tools_auth.py` | `tools_auth` L5 | Wave 1 A1/A2 — 0호 거부·농장 접근권 |
| `test_default_tool_args.py` | `tools_utils.build_default_tool_args` | Wave 3 D3 — 관리 도구 farm/auth 주입 |
| `test_heater_cooldown.py` | `tools_control._get_heater_cooldown_warning` | Wave 2 B2 — 히터 쿨다운 경고 |
| `test_audit_log.py` | `DataCollector._sanitize_args_for_audit / _record_tool_call` | Wave 4 E1 — 감사 마스킹·기록 |
| `test_reformat_routing.py` | `llm_response_processing._is_conversational_query` | patch1 — "표로 작성해줘" 맥락 유지 |

## 추가 가이드

- 신규 제어 도구를 추가하면 `test_default_tool_args.py::TestDeclarativeSpec`
  의 `test_all_admin_tools_registered` 또는 유사 검증을 갱신하세요.
- 권한 체계 변경 시 `test_tools_auth.py` 의 케이스를 반드시 업데이트.
- DB/LLM/HTTP 가 필요한 통합 테스트는 별도 `tests/integration/` 로
  분리하는 것을 권장합니다 (현재 Wave 5 범위 밖).
