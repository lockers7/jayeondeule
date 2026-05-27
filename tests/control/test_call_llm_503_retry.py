# ══════════════════════════════════════════════════════════════════════════════
# test_call_llm_503_retry — Ollama transient retry + call slot lock
#
# 대상: agri_ai_core.src.control.ai_control._call_llm
#
# 검증:
#   · 1차 200 → 즉시 return
#   · 503 / timeout / 500 transient → backoff 후 재시도
#   · 지속 transient 실패 → None (algorithm fallback 위임)
#   · 예외/404 등 비 transient → 재시도 없이 break
#   · scheduled LLM call slot lock 사용
# ══════════════════════════════════════════════════════════════════════════════
from contextlib import contextmanager
from unittest.mock import patch

from agri_ai_core.src.control import ai_control


def _make_resp(status: int, body: dict = None, err: str = ""):
    """(status_code, data, error_text) 튜플 생성."""
    return (status, body or {}, err)


@contextmanager
def _fake_lock(label, wait_sec=None):
    yield


# ────────────────────────────────────────────────────────────────────
# 1차 200 → 즉시 응답
# ────────────────────────────────────────────────────────────────────
class TestImmediateSuccess:
    def test_returns_response_no_retry(self):
        lock_calls = []

        @contextmanager
        def fake_lock(label, wait_sec=None):
            lock_calls.append((label, wait_sec))
            yield

        with patch.object(ai_control, "http_json_request") as mock_http, \
             patch.object(ai_control, "llm_call_lock", side_effect=fake_lock), \
             patch.object(ai_control, "time") as mock_time:
            mock_time.time.return_value = 0.0
            mock_http.return_value = _make_resp(200, {"response": '{"action":"keep"}'})
            r = ai_control._call_llm("sys", "user")
        assert r == '{"action":"keep"}'
        assert mock_http.call_count == 1
        assert lock_calls == [("ai_control", ai_control.AI_CONTROL_LLM_LOCK_WAIT)]


# ────────────────────────────────────────────────────────────────────
# 1차 503 + 2차 200 → 응답 반환
# ────────────────────────────────────────────────────────────────────
class Test503ThenSuccess:
    def test_retries_once_and_returns(self):
        responses = [
            _make_resp(503, None, '{"error":"server busy"}'),
            _make_resp(200, {"response": '{"action":"change"}'}),
        ]
        with patch.object(ai_control, "http_json_request") as mock_http, \
             patch.object(ai_control, "llm_call_lock", side_effect=_fake_lock), \
             patch.object(ai_control, "_control_llm_retry_backoffs", return_value=[1.5]), \
             patch.object(ai_control.time, "sleep") as mock_sleep, \
             patch.object(ai_control.time, "time", return_value=0.0):
            mock_http.side_effect = responses
            r = ai_control._call_llm("sys", "user")
        assert r == '{"action":"change"}'
        assert mock_http.call_count == 2
        mock_sleep.assert_called_once_with(1.5)


# ────────────────────────────────────────────────────────────────────
# timeout 텍스트도 transient 로 보고 재시도
# ────────────────────────────────────────────────────────────────────
class TestTimeoutThenSuccess:
    def test_timeout_text_retries_and_returns(self):
        with patch.object(ai_control, "http_json_request") as mock_http, \
             patch.object(ai_control, "llm_call_lock", side_effect=_fake_lock), \
             patch.object(ai_control, "_control_llm_retry_backoffs", return_value=[2.0]), \
             patch.object(ai_control.time, "sleep") as mock_sleep, \
             patch.object(ai_control.time, "time", return_value=0.0):
            mock_http.side_effect = [
                _make_resp(503, None, "Direct HTTP connection error: timed out"),
                _make_resp(200, {"response": '{"action":"keep"}'}),
            ]
            r = ai_control._call_llm("sys", "user")
        assert r == '{"action":"keep"}'
        assert mock_http.call_count == 2
        mock_sleep.assert_called_once_with(2.0)


# ────────────────────────────────────────────────────────────────────
# 500 계열도 Ollama 재시작/일시 장애 가능성이 있어 재시도
# ────────────────────────────────────────────────────────────────────
class Test500ThenSuccess:
    def test_500_retries_and_returns(self):
        with patch.object(ai_control, "http_json_request") as mock_http, \
             patch.object(ai_control, "llm_call_lock", side_effect=_fake_lock), \
             patch.object(ai_control, "_control_llm_retry_backoffs", return_value=[1.0]), \
             patch.object(ai_control.time, "sleep") as mock_sleep, \
             patch.object(ai_control.time, "time", return_value=0.0):
            mock_http.side_effect = [
                _make_resp(500, None, "server disconnected"),
                _make_resp(200, {"response": '{"action":"change"}'}),
            ]
            r = ai_control._call_llm("sys", "user")
        assert r == '{"action":"change"}'
        assert mock_http.call_count == 2
        mock_sleep.assert_called_once_with(1.0)


# ────────────────────────────────────────────────────────────────────
# 지속 transient 실패 → None (fallback 위임)
# ────────────────────────────────────────────────────────────────────
class Test503Persistent:
    def test_double_503_returns_none_when_retry_budget_exhausted(self):
        with patch.object(ai_control, "http_json_request") as mock_http, \
             patch.object(ai_control, "llm_call_lock", side_effect=_fake_lock), \
             patch.object(ai_control, "_control_llm_retry_backoffs", return_value=[1.5]), \
             patch.object(ai_control.time, "sleep"), \
             patch.object(ai_control.time, "time", return_value=0.0):
            mock_http.side_effect = [
                _make_resp(503, None, '{"error":"busy"}'),
                _make_resp(503, None, '{"error":"busy"}'),
            ]
            r = ai_control._call_llm("sys", "user")
        assert r is None
        assert mock_http.call_count == 2


# ────────────────────────────────────────────────────────────────────
# 예외 발생 → backoff 재시도 후 소진 시 fallback
# 예외도 transient 로 간주해 backoff 재시도한다 (즉시 중단 아님).
# ────────────────────────────────────────────────────────────────────
class TestExceptionRetry:
    def test_exception_retries_then_fallback(self):
        with patch.object(ai_control, "http_json_request") as mock_http, \
             patch.object(ai_control, "llm_call_lock", side_effect=_fake_lock), \
             patch.object(ai_control, "_control_llm_retry_backoffs", return_value=[1.0, 2.0]), \
             patch.object(ai_control.time, "sleep") as mock_sleep, \
             patch.object(ai_control.time, "time", return_value=0.0):
            mock_http.side_effect = RuntimeError("connection refused")
            r = ai_control._call_llm("sys", "user")
        assert r is None
        # backoffs [0.0, 1.0, 2.0] → 총 3회 시도 후 소진
        assert mock_http.call_count == 3
        assert mock_sleep.call_count >= 1


# ────────────────────────────────────────────────────────────────────
# 404 등 비 transient → 재시도 안함
# ────────────────────────────────────────────────────────────────────
class TestNonTransientNoRetry:
    def test_404_no_retry(self):
        with patch.object(ai_control, "http_json_request") as mock_http, \
             patch.object(ai_control, "llm_call_lock", side_effect=_fake_lock), \
             patch.object(ai_control, "_control_llm_retry_backoffs", return_value=[1.0, 2.0]), \
             patch.object(ai_control.time, "sleep") as mock_sleep, \
             patch.object(ai_control.time, "time", return_value=0.0):
            mock_http.return_value = _make_resp(404, None, "not found")
            r = ai_control._call_llm("sys", "user")
        assert r is None
        assert mock_http.call_count == 1
        mock_sleep.assert_not_called()


class TestRetryBackoffParsing:
    def test_backoff_env_parsing_clamps_invalid_values(self):
        with patch.dict(
            ai_control.os.environ,
            {"AI_CONTROL_LLM_RETRY_BACKOFFS": "0, 2, bad, 999"},
        ):
            assert ai_control._control_llm_retry_backoffs() == [2.0, 120.0]

    def test_transient_failure_classifier(self):
        assert ai_control._is_transient_control_llm_failure(503, "server busy") is True
        assert ai_control._is_transient_control_llm_failure(500, "server disconnected") is True
        assert ai_control._is_transient_control_llm_failure(404, "not found") is False
