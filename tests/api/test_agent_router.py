# ══════════════════════════════════════════════════════════════════════════════
# test_agent_router — Phase 4 W: FastAPI agent_router endpoint 검증 [2026-05-25]
#
# 대상: agri_ai_core.api.agent_router
#   9개 endpoint (history, pending, cancel_pending, trigger, subscriptions,
#                 subscribe, cancel_sub, alerts, history detail)
#
# 정책:
#   · FastAPI TestClient + DB 직접 사용 (test row 마커로 cleanup)
#   · run_agent (LLM 호출) 는 mock — 실 LLM 호출 안 함
#
# 파일 시작 함수 목록:
#   client                : TestClient fixture
#   cleanup               : 테스트 row 자동 삭제
#   TestHistory           : /history GET
#   TestPending           : /pending GET + cancel
#   TestTriggerMocked     : /trigger POST (run_agent mock)
#   TestSubscriptions     : /subscribe / list / cancel
#   TestAlerts            : /alerts GET
# ══════════════════════════════════════════════════════════════════════════════
from unittest.mock import patch

import pytest


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from agri_ai_core.api.agent_router import agent_router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(agent_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM agent_pending_actions WHERE reason LIKE '__pytest_api%'")
                    cur.execute("DELETE FROM agent_user_alerts WHERE title LIKE '__pytest_api%' OR body LIKE '__pytest_api%'")
                    cur.execute("DELETE FROM agent_subscriptions WHERE intent LIKE '__pytest_api%' OR task LIKE '__pytest_api%'")
                    conn.commit()
            finally:
                db._putconn(conn)
    except Exception:
        pass


# ────────────────────────────────────────────────────────────────────
# 1) /history GET
# ────────────────────────────────────────────────────────────────────
class TestHistory:
    def test_history_basic(self, client):
        r = client.get("/api/v1/agent/history?limit=5")
        assert r.status_code == 200
        d = r.json()
        assert d["success"] is True
        assert "items" in d
        assert "total" in d
        assert isinstance(d["items"], list)

    def test_history_filter_trigger_type(self, client):
        r = client.get("/api/v1/agent/history?trigger_type=schedule&limit=3")
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert it["trigger_type"] == "schedule"

    def test_history_pagination(self, client):
        r = client.get("/api/v1/agent/history?limit=2&offset=0")
        assert r.status_code == 200
        assert len(r.json()["items"]) <= 2

    def test_history_detail_not_found(self, client):
        r = client.get("/api/v1/agent/history/99999999")
        assert r.status_code == 404


# ────────────────────────────────────────────────────────────────────
# 2) /pending GET + cancel
# ────────────────────────────────────────────────────────────────────
class TestPending:
    def _insert_pending(self):
        from agri_ai_core.src.postgresql.connection import db
        import json
        conn = db._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO agent_pending_actions "
                    "(execute_at, trigger_type, tool_name, args, reason, status) "
                    "VALUES (NOW() + INTERVAL '1 hour', 'user', 'send_user_alert', "
                    " %s::jsonb, '__pytest_api_pending__', 'pending') RETURNING id",
                    (json.dumps({"level":"info","message":"test"}),))
                aid = cur.fetchone()[0]
                conn.commit()
                return aid
        finally:
            db._putconn(conn)

    def test_pending_list(self, client):
        aid = self._insert_pending()
        r = client.get("/api/v1/agent/pending?status=pending&limit=50")
        assert r.status_code == 200
        ids = [it["id"] for it in r.json()["items"]]
        assert aid in ids

    def test_cancel_pending(self, client):
        aid = self._insert_pending()
        r = client.post(f"/api/v1/agent/pending/{aid}/cancel",
                        json={"user_id": "pytest", "reason": "__pytest_api_cancel__"})
        assert r.status_code == 200
        d = r.json()
        assert d["success"] is True

        # 다시 cancel 시도 — 이미 cancelled 라 404
        r2 = client.post(f"/api/v1/agent/pending/{aid}/cancel",
                         json={"user_id": "pytest"})
        assert r2.status_code == 404


# ────────────────────────────────────────────────────────────────────
# 3) /trigger POST (run_agent mock)
# ────────────────────────────────────────────────────────────────────
class TestTriggerMocked:
    def test_trigger_success(self, client):
        fake = {
            "success": True, "final": "테스트 정상", "duration_sec": 5.0,
            "steps": [{"tool":"get_sensor_window"}], "log_id": 999,
        }
        with patch("agri_ai_core.src.control.ai_monitor_agent.run_agent",
                   return_value=fake):
            r = client.post("/api/v1/agent/trigger",
                            json={"task": "__pytest_api_trigger__", "farm_id": 1})
        assert r.status_code == 200
        d = r.json()
        assert d["success"] is True
        assert d["log_id"] == 999
        assert d["final"] == "테스트 정상"
        assert d["steps"] == 1

    def test_trigger_validation_missing_task(self, client):
        r = client.post("/api/v1/agent/trigger", json={"farm_id": 1})
        assert r.status_code == 422  # pydantic validation


# ────────────────────────────────────────────────────────────────────
# 4) /subscribe / /subscriptions / /cancel
# ────────────────────────────────────────────────────────────────────
class TestSubscriptions:
    def test_subscribe_and_list(self, client):
        r = client.post("/api/v1/agent/subscribe", json={
            "task": "__pytest_api_sub__", "interval_min": 60,
            "farm_id": 1, "user_id": "pytest_api_user",
        })
        assert r.status_code == 200, r.text
        sub_id = r.json()["subscription_id"]
        assert sub_id is not None

        r2 = client.get("/api/v1/agent/subscriptions?user_id=pytest_api_user")
        assert r2.status_code == 200
        ids = [s["id"] for s in r2.json()["subscriptions"]]
        assert sub_id in ids

    def test_subscribe_invalid_interval(self, client):
        # interval_min 2 < 5 — pydantic Field(ge=5) 검증
        r = client.post("/api/v1/agent/subscribe", json={
            "task": "__pytest_api_sub__", "interval_min": 2,
        })
        assert r.status_code == 422

    def test_cancel_subscription(self, client):
        r = client.post("/api/v1/agent/subscribe", json={
            "task": "__pytest_api_sub_cancel__", "interval_min": 30,
            "user_id": "pytest_api_user",
        })
        sub_id = r.json()["subscription_id"]
        rc = client.post(f"/api/v1/agent/subscriptions/{sub_id}/cancel",
                         json={"user_id": "pytest_api_user"})
        assert rc.status_code == 200
        assert rc.json()["success"] is True

    def test_cancel_other_user_forbidden(self, client):
        r = client.post("/api/v1/agent/subscribe", json={
            "task": "__pytest_api_sub_other__", "interval_min": 30,
            "user_id": "owner_pytest",
        })
        sub_id = r.json()["subscription_id"]
        rc = client.post(f"/api/v1/agent/subscriptions/{sub_id}/cancel",
                         json={"user_id": "intruder_pytest"})
        # tools_agent_sub.cancel_agent_subscription 가 forbidden 반환 → 400
        assert rc.status_code == 400


# ────────────────────────────────────────────────────────────────────
# 5) /alerts GET
# ────────────────────────────────────────────────────────────────────
class TestAlerts:
    def _insert_alert(self, user_id):
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO agent_user_alerts (user_id, level, title, body) "
                    "VALUES (%s, 'info', '__pytest_api_alert__', '__pytest_api_alert_body__') "
                    "RETURNING id",
                    (user_id,))
                aid = cur.fetchone()[0]
                conn.commit()
                return aid
        finally:
            db._putconn(conn)

    def test_get_alerts_unread(self, client):
        aid = self._insert_alert("pytest_api_alert_user")
        r = client.get("/api/v1/agent/alerts?user_id=pytest_api_alert_user&mark_read=false")
        assert r.status_code == 200
        d = r.json()
        assert d["success"] is True
        ids = [a["id"] for a in d["alerts"]]
        assert aid in ids

    def test_alerts_mark_read(self, client):
        self._insert_alert("pytest_api_alert_user2")
        r1 = client.get("/api/v1/agent/alerts?user_id=pytest_api_alert_user2&mark_read=true")
        assert r1.json()["count"] >= 1
        # 두 번째 호출 — 동일 알림 안 보임
        r2 = client.get("/api/v1/agent/alerts?user_id=pytest_api_alert_user2")
        for a in r2.json()["alerts"]:
            assert "__pytest_api_alert_body__" not in (a["body"] or "")


# ────────────────────────────────────────────────────────────────────
# 6) /stream SSE (단위 — connect + hello event + 1 alert + 끊김)
# ────────────────────────────────────────────────────────────────────
class TestSSE:
    def _insert_alert(self, user_id, body="__pytest_api_sse_body__"):
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO agent_user_alerts (user_id, level, title, body) "
                    "VALUES (%s, 'info', '__pytest_api_sse_t__', %s) RETURNING id",
                    (user_id, body))
                aid = cur.fetchone()[0]
                conn.commit()
                return aid
        finally:
            db._putconn(conn)

    def test_sse_hello_event(self, client):
        # SSE_POLL_INTERVAL_SEC=5 가 큼 — 빠른 검증을 위해 stream 첫 chunk 만 받고 끊음
        with client.stream("GET", "/api/v1/agent/stream?user_id=pytest_sse&since_id=99999999",
                            timeout=3) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            chunks = []
            for chunk in resp.iter_text():
                chunks.append(chunk)
                if len(chunks) >= 1:
                    break
        joined = "".join(chunks)
        assert "event: hello" in joined
        assert '"user_id": "pytest_sse"' in joined


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
