# ══════════════════════════════════════════════════════════════════════════════
# test_fallback_gating_degraded — LLM 실패 연속카운트가 모든 실패모드를 세는지
#
# 배경(2026-07-18): manual_control 의 _LLM_FAIL_COUNTER 게이팅이
#   `action=='keep' and 'LLM' in message` 문자열 매칭이라, control_ai_environment 의
#   실패 반환 중 메시지에 'LLM' 이 없는 것들("파싱 실패","안전 검증 실패")이
#   연속실패로 안 세어졌다 → LLM 이 계속 깨진 응답을 내도 3회 algorithm 폴백이
#   발동하지 않았다(safety fallback 무력화). 구조화된 degraded 플래그로 교체.
#
# 파일 시작 함수 목록:
#   test_all_failure_paths_marked_degraded : 3개 실패 반환에 degraded=True
#   test_normal_keep_not_degraded          : 정상 keep 은 degraded 아님
#   test_gating_uses_degraded_flag         : manual_control 이 degraded 로 판정
# ══════════════════════════════════════════════════════════════════════════════
import inspect
import re

from agri_ai_core.src.control import ai_control, manual_control


def test_all_failure_paths_marked_degraded():
    src = inspect.getsource(ai_control.control_ai_environment)
    # 세 실패 '반환'(message 에 "AI 제어:" 접두어) 이 모두 degraded=True 를 달고 있어야
    # 한다. (같은 문구가 _log_ai_decision 로그 인자에도 있으므로 접두어로 return 을 겨냥)
    for msg in ("AI 제어: LLM 실패 → 현상 유지",
                "AI 제어: 파싱 실패 → 현상 유지",
                "AI 제어: 안전 검증 실패"):
        idx = src.find(msg)
        assert idx != -1, f"실패 반환 '{msg}' 을 찾지 못함 — 테스트 갱신 필요"
        window = src[idx:idx + 160]
        assert "degraded" in window and "True" in window, (
            f"'{msg}' 반환에 degraded=True 가 없음 — 이 실패가 폴백 카운트에서 누락된다")


def test_normal_keep_not_degraded():
    src = inspect.getsource(ai_control.control_ai_environment)
    # 정상 keep 2종(현상유지 재구성 / 현상 유지)에는 degraded 가 붙으면 안 된다
    for msg in ("현상유지 재구성 (", "현상 유지 ("):
        idx = src.find(f'"AI 제어: {msg}')
        assert idx != -1
        window = src[idx:idx + 120]
        assert "degraded" not in window, f"정상 keep '{msg}' 에 degraded 가 잘못 붙음"


def test_gating_uses_degraded_flag():
    src = inspect.getsource(manual_control)
    # ⛔ 'LLM' in message 문자열 매칭이 부활하면 안 된다
    assert "result.get('degraded')" in src or 'result.get("degraded")' in src, (
        "폴백 게이팅이 degraded 플래그를 쓰지 않음")
    assert not re.search(r"'LLM'\s+in\s+str\(result", src), (
        "'LLM' 문자열 매칭이 남아있음 — 파싱/검증 실패가 다시 안 세어진다")
