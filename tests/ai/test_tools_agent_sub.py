# ══════════════════════════════════════════════════════════════════════════════
# test_tools_agent_sub — 구독/알림 도구 4개 검증
#
# 대상:
#   · agent_subscribe              : agent_subscriptions INSERT
#   · list_agent_subscriptions     : SELECT active
#   · cancel_agent_subscription    : UPDATE active=FALSE
#   · get_pending_alerts           : agent_user_alerts SELECT + mark_read
#
# 정책: 실 DB 사용 + 테스트 종료 시 cleanup (reason/intent 마커).
#
# 파일 시작 함수 목록:
#   TestSubscribeValidation   : 인자 범위/검증
#   TestSubscribeReal         : 실 DB INSERT/cleanup
#   TestListAndCancel         : list + cancel idempotent
#   TestPendingAlerts         : alert 조회 + mark_read
# ══════════════════════════════════════════════════════════════════════════════
import pytest


# ────────────────────────────────────────────────────────────────────
# 공통 cleanup fixture — '__pytest_sub_*' marker
# ────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def cleanup():
    yield
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM agent_user_alerts "
                        "WHERE title LIKE '__pytest%' OR body LIKE '__pytest%'")
                    cur.execute(
                        "DELETE FROM agent_subscriptions "
                        "WHERE intent LIKE '__pytest%' OR task LIKE '__pytest%'")
                    conn.commit()
            finally:
                db._putconn(conn)
    except Exception:
        pass


# ────────────────────────────────────────────────────────────────────
# 1) agent_subscribe — 인자 검증
# ────────────────────────────────────────────────────────────────────
class TestSubscribeValidation:
    def test_empty_task(self):
        from agri_ai_core.src.ai.tools_agent_sub import agent_subscribe
        r = agent_subscribe(task="", interval_min=30)
        assert r["success"] is False
        assert r["reason"] == "invalid_args"

    def test_interval_too_small(self):
        from agri_ai_core.src.ai.tools_agent_sub import agent_subscribe
        r = agent_subscribe(task="__pytest_sub_a__", interval_min=2)
        assert r["success"] is False
        assert "범위" in r["message"]

    def test_interval_too_large(self):
        from agri_ai_core.src.ai.tools_agent_sub import agent_subscribe
        r = agent_subscribe(task="__pytest_sub_b__", interval_min=99999)
        assert r["success"] is False

    def test_invalid_interval_type(self):
        from agri_ai_core.src.ai.tools_agent_sub import agent_subscribe
        r = agent_subscribe(task="__pytest_sub_c__", interval_min="bogus")
        assert r["success"] is False


# ────────────────────────────────────────────────────────────────────
# 2) agent_subscribe — 실제 DB INSERT
# ────────────────────────────────────────────────────────────────────
class TestSubscribeReal:
    def test_basic_insert(self):
        from agri_ai_core.src.ai.tools_agent_sub import agent_subscribe
        r = agent_subscribe(task="__pytest_sub_basic__", interval_min=60,
                            farm_id=1, user_id="pytest_user",
                            intent="__pytest_sub_basic_intent__")
        assert r["success"] is True
        assert r["subscription_id"] is not None
        assert r["interval_min"] == 60

        # DB 에 row 확인
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            row = d.fetch_one(
                "SELECT id, user_id, farm_id, interval_min, task, active "
                "FROM agent_subscriptions WHERE id=%s",
                (r["subscription_id"],))
        assert row is not None
        assert row["user_id"] == "pytest_user"
        assert row["active"] is True

    def test_per_user_limit(self):
        from agri_ai_core.src.ai.tools_agent_sub import agent_subscribe
        # 5건 등록
        # 유사 구독 자동 대체에 걸리지 않도록 서로 성격이 다른 과제 사용
        distinct_tasks = [
            "__pytest__ 야간 저온 임계 이탈만 감시하고 이상 시 알림",
            "__pytest__ 수확량 집계를 주간 단위로 요약 보고",
            "__pytest__ 카메라 영상에서 갓 크기 변화를 관찰",
            "__pytest__ 전력 사용량 급증 여부를 점검",
            "__pytest__ 배지 오염 징후 키워드를 결정 이력에서 탐지",
        ]
        for t in distinct_tasks:
            r = agent_subscribe(task=t, interval_min=60, farm_id=1,
                                user_id="pytest_limit_user")
            assert r["success"] is True, r
        # 6번째 차단 (역시 상이한 과제)
        r6 = agent_subscribe(task="__pytest__ 환기팬 소음 이상 진동 감시", interval_min=60,
                             farm_id=1, user_id="pytest_limit_user")
        assert r6["success"] is False
        assert r6["reason"] == "limit"


# ────────────────────────────────────────────────────────────────────
# 3) list_agent_subscriptions + cancel_agent_subscription
# ────────────────────────────────────────────────────────────────────
class TestListAndCancel:
    def test_list_user_scope(self):
        from agri_ai_core.src.ai.tools_agent_sub import (
            agent_subscribe, list_agent_subscriptions)
        agent_subscribe(task="__pytest_sub_listA__", interval_min=30,
                        user_id="pytest_user_A")
        agent_subscribe(task="__pytest_sub_listB__", interval_min=30,
                        user_id="pytest_user_B")

        ra = list_agent_subscriptions(user_id="pytest_user_A")
        assert ra["success"] is True
        a_ids = [s["id"] for s in ra["subscriptions"]]
        # A 사용자의 항목만 보여야 함
        for sub in ra["subscriptions"]:
            assert sub["user_id"] == "pytest_user_A"

    def test_list_excludes_default_by_default(self):
        from agri_ai_core.src.ai.tools_agent_sub import list_agent_subscriptions
        r = list_agent_subscriptions()
        for sub in r["subscriptions"]:
            assert sub["intent"] != "__default_cron__"

    def test_cancel_basic(self):
        from agri_ai_core.src.ai.tools_agent_sub import (
            agent_subscribe, cancel_agent_subscription)
        ins = agent_subscribe(task="__pytest_sub_cancel__", interval_min=30,
                              user_id="pytest_cancel_user")
        sub_id = ins["subscription_id"]
        r = cancel_agent_subscription(subscription_id=sub_id,
                                      user_id="pytest_cancel_user")
        assert r["success"] is True

    def test_cancel_other_user_forbidden(self):
        from agri_ai_core.src.ai.tools_agent_sub import (
            agent_subscribe, cancel_agent_subscription)
        ins = agent_subscribe(task="__pytest_sub_other__", interval_min=30,
                              user_id="pytest_owner")
        r = cancel_agent_subscription(subscription_id=ins["subscription_id"],
                                      user_id="pytest_intruder")
        assert r["success"] is False
        assert r["reason"] == "forbidden"

    def test_cancel_idempotent(self):
        from agri_ai_core.src.ai.tools_agent_sub import (
            agent_subscribe, cancel_agent_subscription)
        ins = agent_subscribe(task="__pytest_sub_idem__", interval_min=30,
                              user_id="pytest_idem")
        sub_id = ins["subscription_id"]
        r1 = cancel_agent_subscription(subscription_id=sub_id,
                                       user_id="pytest_idem")
        assert r1["success"] is True
        r2 = cancel_agent_subscription(subscription_id=sub_id,
                                       user_id="pytest_idem")
        assert r2["success"] is False
        assert r2["reason"] == "already_inactive"


# ────────────────────────────────────────────────────────────────────
# 4) get_pending_alerts — 미읽 알림 + mark_read
# ────────────────────────────────────────────────────────────────────
class TestPendingAlerts:
    def _insert_alert(self, user_id, body, level="info"):
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO agent_user_alerts (user_id, level, title, body) "
                    "VALUES (%s, %s, %s, %s) RETURNING id",
                    (user_id, level, "__pytest_alert_t__", body))
                aid = cur.fetchone()[0]
                conn.commit()
                return aid
        finally:
            db._putconn(conn)

    def test_get_unread(self):
        from agri_ai_core.src.ai.tools_agent_sub import get_pending_alerts
        aid = self._insert_alert("pytest_alert_user", "__pytest_alert_body__")
        r = get_pending_alerts(user_id="pytest_alert_user", mark_read=False)
        assert r["success"] is True
        ids = [a["id"] for a in r["alerts"]]
        assert aid in ids

    def test_mark_read_idempotent(self):
        from agri_ai_core.src.ai.tools_agent_sub import get_pending_alerts
        self._insert_alert("pytest_alert_user2", "__pytest_alert_body__")
        # 첫 호출 — alert 포함 + mark_read=True
        r1 = get_pending_alerts(user_id="pytest_alert_user2", mark_read=True)
        assert r1["count"] >= 1
        # 두 번째 호출 — 동일 알림 안 보임 (이미 read)
        r2 = get_pending_alerts(user_id="pytest_alert_user2", mark_read=True)
        # r2 에는 read 안 한 새 알림만 — 우리 marker 알림은 없어야
        for a in r2["alerts"]:
            assert "__pytest_alert_body__" not in (a["body"] or "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
