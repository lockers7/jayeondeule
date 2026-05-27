# ══════════════════════════════════════════════════════════════════════════════
# test_mode_and_thresholds — 운용방식 전환·임계값 변경 도구 검증 (농장주 명세)
#
# 명세: 관리자가 변경할 수 있는 정보는 로컬 AI 도 변경 가능해야 한다.
# ⛔ 핵심: mnul_ctrl_flag 는 이름과 반대(False=수동) — 도구 매핑이 런타임
#   판정(manual_control)과 반드시 일치해야 한다 (2026-07-15 실사고: 반전 매핑).
#
# 파일 시작 함수 목록:
#   test_mode_mapping_runtime_consistent : manual/algorithm/ai → flag·ctrl_type 매핑
#   test_threshold_set_column_and_guard  : key→컬럼 매핑 + 범위/순서 가드
#   test_threshold_farm_access           : 농장사용자 타 농장 거부
#   test_mode_switch_safety_net          : 명령형 전환 발화 미이행 시 자동 실행
# ══════════════════════════════════════════════════════════════════════════════
import pytest

from agri_ai_core.src.ai import tools_admin as ta


class _FakeDB:
    def __init__(self, rows=None, one=None):
        self.rows = rows or []
        self.one = one
        self.updates = []

    def fetch_all(self, query=None, vals=None, as_dict=True):
        return self.rows

    def fetch_one(self, query=None, vals=None, **kw):
        return self.one

    def execute_query(self, q, vals=None):
        self.updates.append((q, vals))
        return True


class _FakeSession:
    def __init__(self, db): self.db = db
    def __enter__(self): return self.db
    def __exit__(self, *a): return False


def _patch_db(monkeypatch, db):
    monkeypatch.setattr("agri_ai_core.src.postgresql.connection.db_session",
                        lambda: _FakeSession(db))


def test_mode_mapping_runtime_consistent(monkeypatch):
    monkeypatch.setattr("agri_ai_core.src.control.manual_control.trigger_algorithm_now",
                        lambda f, h: None, raising=False)
    # 런타임 판정과 동일해야 함: manual→(False,algorithm) / algorithm→(True,algorithm) / ai→(True,ai)
    expect = {"manual": (False, "algorithm"),
              "algorithm": (True, "algorithm"),
              "ai": (True, "ai")}
    before_by_mode = {"manual": (True, "ai"), "algorithm": (False, "algorithm"),
                      "ai": (False, "algorithm")}   # 목표와 다른 이전 상태 (변경 발생 보장)
    for mode, (flag, ctype) in expect.items():
        b_flag, b_type = before_by_mode[mode]
        db = _FakeDB(rows=[{"farm_id": 1, "hous_id": 1, "hous_name": "1호",
                            "mnul_ctrl_flag": b_flag, "ctrl_type": b_type}])
        _patch_db(monkeypatch, db)
        r = ta.set_house_control_mode("1", mode, farm_id="1", auth_farm_id=None)
        assert r["success"], r
        q, vals = db.updates[0]
        assert vals[0] is flag and vals[1] == ctype, f"{mode}: {vals[:2]}"


def test_threshold_set_column_and_guard(monkeypatch):
    row = {"setn_dttm": "2026-07-01", "tprt_min": 20.0, "tprt_max": 25.0,
           "co2_min": 300.0, "co2_max": 1200.0}
    db = _FakeDB(rows=[{"hous_id": 1}, {"hous_id": 2}], one=row)
    _patch_db(monkeypatch, db)
    # 정상 set — CO2_HIGH 2000, house all → 2개 재배사 UPDATE, co2_max 컬럼
    r = ta.override_ai_thresholds("set", key="CO2_HIGH", value=2000,
                                  farm_id="1", house_id="all", auth_farm_id=None)
    assert r["success"] and len(db.updates) == 2
    assert "co2_max" in db.updates[0][0]
    # 범위 가드 — CO2 20000 거부
    assert not ta.override_ai_thresholds("set", key="CO2_HIGH", value=20000,
                                         farm_id="1", auth_farm_id=None)["success"]
    # 순서 가드 — TEMP_HIGH 를 min(20) 이하로 → 거부
    db2 = _FakeDB(rows=[{"hous_id": 1}], one=row)
    _patch_db(monkeypatch, db2)
    r2 = ta.override_ai_thresholds("set", key="TEMP_HIGH", value=19,
                                   farm_id="1", house_id="1", auth_farm_id=None)
    assert not r2["success"] and not db2.updates


def test_threshold_farm_access(monkeypatch):
    db = _FakeDB(rows=[{"hous_id": 1}], one={"setn_dttm": "x", "tprt_max": 30.0})
    _patch_db(monkeypatch, db)
    r = ta.override_ai_thresholds("set", key="TEMP_HIGH", value=29,
                                  farm_id="2", auth_farm_id="1")
    assert not r["success"] and "권한" in r["error"]


def test_mode_switch_safety_net(monkeypatch):
    from agri_ai_core.src.ai.pipeline.data_collector import DataCollector
    executed = {}
    dc = DataCollector(default_tool_args={}, raw_user_query="인공지능모드로 전환하여, 너의 판단에 따라 제어하라")
    # 실패한 호출 기록 (house 0 거부 시나리오)
    dc.tool_calls_detail = [{"tool": "set_house_control_mode", "success": False}]
    monkeypatch.setattr(dc, "_execute_tasks",
                        lambda tasks, q: executed.update(tasks=tasks))
    dc._ensure_control_mode()
    assert executed["tasks"][0]["args"] == {"house_id": "all", "mode": "ai"}
    # 성공한 호출이 있으면 미발동
    executed.clear()
    dc.tool_calls_detail = [{"tool": "set_house_control_mode", "success": True}]
    dc._ensure_control_mode()
    assert not executed
    # 의문형은 미발동
    dc2 = DataCollector(default_tool_args={}, raw_user_query="인공지능 모드로 전환하면 어때?")
    monkeypatch.setattr(dc2, "_execute_tasks",
                        lambda tasks, q: executed.update(tasks=tasks))
    dc2._ensure_control_mode()
    assert not executed
    # 호기 명시 시 해당 호기만
    dc3 = DataCollector(default_tool_args={}, raw_user_query="2호 재배사를 알고리즘 모드로 바꿔줘")
    monkeypatch.setattr(dc3, "_execute_tasks",
                        lambda tasks, q: executed.update(tasks=tasks))
    dc3._ensure_control_mode()
    assert executed["tasks"][0]["args"] == {"house_id": "2", "mode": "algorithm"}


def test_subscription_similarity_dedupe():
    # 유사 구독 자동 대체 판정 — 동일 지시 재등록은 대체, 성격 다른 구독은 보존
    from agri_ai_core.src.ai.tools_agent_sub import (_task_similarity,
                                                      SIMILAR_TASK_RATIO, SIMILAR_WARN_RATIO)
    a = "각 재배사 센서값과 릴레이 제어값을 표로 작성하여 제공. CO2는 2000 이하, 온도는 30도 이하 유지."
    b = "각 재배사 센서값 및 릴레이 제어 상태, 제어 이유를 요약하여 카카오톡으로 알림"
    c = ("농장 1 자율 환경 제어 사이클. 각 호기의 센서값을 읽고 임계값과 비교하라. "
         "임계 초과 호기는 set_relay 로 릴레이를 직접 제어하고 send_user_alert 로 알려라.")
    assert _task_similarity(a, a) >= SIMILAR_TASK_RATIO          # 동일 지시 → 자동 대체
    s_ab = _task_similarity(a, b)                                # 표현만 바꾼 재지시 → 경고 구간
    assert SIMILAR_WARN_RATIO <= s_ab < SIMILAR_TASK_RATIO
    assert _task_similarity(a, c) < SIMILAR_WARN_RATIO           # 자율제어 구독은 무관 판정
    assert _task_similarity(b, c) < SIMILAR_WARN_RATIO


def test_cancel_monitor_delegates_subscription(monkeypatch):
    # 순수 숫자 job_id(=구독 ID)면 cancel_agent_subscription 으로 위임
    import agri_ai_core.src.ai.tools_agent as tg
    called = {}
    monkeypatch.setattr("agri_ai_core.src.ai.tools_agent_sub.cancel_agent_subscription",
                        lambda *, subscription_id, reason=None:
                        called.update(sid=subscription_id) or {"success": True, "cancelled_id": subscription_id})
    r = tg.cancel_monitor("1579")
    assert r["success"] and called["sid"] == 1579 and r["delegated_from"] == "cancel_monitor"
    # 'agent_monitor_...' 형태는 기존 Job 취소 경로 (스케줄러 미초기화 시 그 오류)
    monkeypatch.setattr("agri_ai_core.src.control.task_scheduler._scheduler", None, raising=False)
    r2 = tg.cancel_monitor("agent_monitor_123")
    assert r2["success"] is False and "delegated_from" not in r2


def test_save_alert_cooldown_gate(monkeypatch):
    # _save_alert: 쿨다운 이내면 카카오 skip, 채팅 알림(INSERT)·제어는 유지
    from datetime import datetime, timedelta
    import agri_ai_core.src.control.agent_scheduler as sched

    class _Cur:
        def __init__(self, outer): self.outer = outer
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, vals=None):
            self.outer.calls.append((sql.split()[0], vals))
            self._last = sql
        def fetchone(self):
            # alert_cooldown_min=120, last_kakao_at=10분 전 → 쿨다운 이내
            return (120, datetime.now() - timedelta(minutes=10))

    class _Conn:
        def __init__(self): self.calls = []
        def cursor(self): return _Cur(self)
        def commit(self): pass
        def rollback(self): pass

    conn = _Conn()
    class _DB:
        def _getconn(self): return conn
        def _putconn(self, c): pass
    monkeypatch.setattr("agri_ai_core.src.postgresql.connection.db", _DB(), raising=False)
    pushed = []
    monkeypatch.setattr("agri_ai_core.src.ai.kakao_notify.push_alert",
                        lambda *a, **k: pushed.append(a))
    sched._save_alert("u", 309, 1, "warning", "제목", "본문")
    # 채팅 알림 INSERT 는 실행됐고, 쿨다운으로 카카오는 skip
    assert any(c[0] == "INSERT" for c in conn.calls)
    assert pushed == []


def test_save_alert_sends_after_cooldown(monkeypatch):
    from datetime import datetime, timedelta
    import agri_ai_core.src.control.agent_scheduler as sched

    class _Cur:
        def __init__(self, outer): self.outer = outer
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, vals=None): self.outer.calls.append((sql.split()[0], vals))
        def fetchone(self):
            return (120, datetime.now() - timedelta(minutes=200))   # 쿨다운 경과
    class _Conn:
        def __init__(self): self.calls = []
        def cursor(self): return _Cur(self)
        def commit(self): pass
        def rollback(self): pass
    conn = _Conn()
    class _DB:
        def _getconn(self): return conn
        def _putconn(self, c): pass
    monkeypatch.setattr("agri_ai_core.src.postgresql.connection.db", _DB(), raising=False)
    pushed = []
    monkeypatch.setattr("agri_ai_core.src.ai.kakao_notify.push_alert",
                        lambda *a, **k: pushed.append(a))
    sched._save_alert("u", 309, 1, "warning", "제목", "본문")
    assert len(pushed) == 1
    assert any(c[0] == "UPDATE" for c in conn.calls)   # last_kakao_at 갱신


def test_set_alert_interval_farm_scope(monkeypatch):
    from agri_ai_core.src.ai import tools_agent_sub as tas
    updates = []
    class _DB:
        def fetch_all(self, sql, vals=None, as_dict=True):
            return [{"id": 309}, {"id": 1744}]
        def execute_query(self, sql, vals=None):
            # 파라미터 없는 DDL(ensure_policy_table 의 CREATE TABLE 등)은 검증 대상 아님 —
            # 격리 실행 시 _policy_ensured 미트립으로 섞여 들어오는 것을 제외(테스트 격리 안정화).
            if vals:
                updates.append(vals)
    class _S:
        def __enter__(self): return _DB()
        def __exit__(self, *a): return False
    monkeypatch.setattr("agri_ai_core.src.postgresql.connection.db_session", lambda: _S())
    r = tas.set_alert_interval(interval_min=120, farm_id="1", auth_farm_id=None)
    assert r["success"] and set(r["affected_subscription_ids"]) == {309, 1744}
    assert all(v[0] == 120 for v in updates)
    # 0 = 해제 (NULL 저장)
    updates.clear()
    r0 = tas.set_alert_interval(interval_min=0, farm_id="1", auth_farm_id=None)
    assert r0["success"] and all(v[0] is None for v in updates)
