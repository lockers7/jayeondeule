# ══════════════════════════════════════════════════════════════════════════════
# test_kakao_notify_policy — 카카오 발송 정책(간격·심각도) LLM 요청 이행 검증
#
# 원칙: 정책 값은 코드가 정하지 않는다. 농장주가 채팅으로 요청하면 LLM 이
#   set_alert_interval / set_alert_level 도구로 kakao_notify_config 에 기록하고,
#   push_alert 가 그 값을 이행할 뿐이다.
# 농장주 지시: critical(비상) 은 어떤 정책에도 억제되지 않고 항상 즉시 발송.
#
# 파일 시작 함수 목록:
#   test_cooldown_off_sends_every_time    : 쿨다운 해제(0) — 매번 발송
#   test_llm_interval_suppresses          : LLM 이 정한 간격 내 재발송 억제
#   test_critical_bypasses_cooldown       : critical 은 쿨다운 무시 발송
#   test_llm_level_filters_below          : LLM 이 정한 심각도 미달은 미발송
#   test_critical_bypasses_level_filter   : min_level=critical 이어도 critical 발송
#   test_level_alias_and_validation       : 한국어 별칭 수용 / 잘못된 값 거부
#   test_policy_read_failure_falls_back   : 정책 조회 실패 시 기존 동작(발송) 보전
# ══════════════════════════════════════════════════════════════════════════════
import threading
from unittest.mock import patch

import pytest

from agri_ai_core.src.ai import kakao_notify as kn
from agri_ai_core.src.ai.tools_agent_sub import set_alert_interval, set_alert_level


def _drain():
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon:
            t.join(timeout=1)


@pytest.fixture
def sender():
    sent = []

    def _fake(text, web_url=None):
        sent.append(text)

    with patch.object(kn, "send_to_me", _fake), patch.object(kn, "_rest_key", lambda: "TESTKEY"):
        def _push(level, title="t", body="b"):
            sent.clear()
            kn.push_alert(level, title, body)
            _drain()
            return len(sent)
        yield _push


@pytest.fixture(autouse=True)
def _reset_policy():
    # 실 DB 단일행을 공유하므로 원래 정책을 snapshot 후 정확히 복원 —
    # 미설정(NULL)을 'info' 등으로 덮으면 env 폴백을 쓰는 기존 테스트가 깨진다.
    before = kn.get_notify_policy()
    yield
    kn.set_notify_cooldown(before.get("cooldown_min"))
    kn.set_notify_min_level(before.get("min_level"))


def test_cooldown_off_sends_every_time(sender):
    kn.set_notify_cooldown(0)
    kn.set_notify_min_level("info")
    assert sender("info") == 1
    assert sender("info") == 1          # 해제 상태 — 연속 발송 억제 없음


def test_llm_interval_suppresses(sender):
    kn.set_notify_min_level("info")
    kn.set_notify_cooldown(0)
    assert sender("info") == 1          # 기준점(last_sent_at) 생성
    # 농장주 "카카오는 2시간마다만" → LLM 이 도구 호출
    r = set_alert_interval(interval_min=120, farm_id=1, auth_farm_id="1")
    assert r["success"] is True
    assert kn.get_notify_policy()["cooldown_min"] == 120
    assert sender("info") == 0          # 창 안 — 억제


def test_critical_bypasses_cooldown(sender):
    kn.set_notify_min_level("info")
    kn.set_notify_cooldown(0)
    sender("info")                      # 기준점
    kn.set_notify_cooldown(120)
    assert sender("info") == 0          # 일반은 억제
    assert sender("critical") == 1      # 비상은 관통 (농장주 지시)


def test_llm_level_filters_below(sender):
    kn.set_notify_cooldown(0)
    # 농장주 "심각한 문제일 때만 알려줘" → LLM 이 도구 호출
    r = set_alert_level(level="critical")
    assert r["success"] is True and r["level"] == "critical"
    assert kn.get_notify_policy()["min_level"] == "critical"
    assert sender("info") == 0
    assert sender("warning") == 0
    # "경고 이상만" 으로 완화하면 warning 통과
    set_alert_level(level="warning")
    assert sender("warning") == 1
    assert sender("info") == 0


def test_critical_bypasses_level_filter(sender):
    kn.set_notify_cooldown(0)
    kn.set_notify_min_level("critical")
    assert sender("critical") == 1


def test_level_alias_and_validation():
    assert set_alert_level(level="심각")["level"] == "critical"
    assert set_alert_level(level="경고")["level"] == "warning"
    assert set_alert_level(level="전체")["level"] == "info"
    bad = set_alert_level(level="아무거나")
    assert bad["success"] is False


def test_policy_read_failure_falls_back(sender):
    # 정책 조회가 깨져도 알림 흐름은 절대 멈추지 않는다(기존 동작 보전)
    with patch.object(kn, "get_notify_policy", lambda: {}):
        assert sender("info") == 1
