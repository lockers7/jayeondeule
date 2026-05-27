# ══════════════════════════════════════════════════════════════════════════════
# test_selfgrow_autolearn — 자가교정→지식 환류(GAP2) 검증
#
# db_read_query 가 컬럼/타입 오류로 실제 스키마를 알아내면 그 사실을
# system_knowledge 에 영속 학습 → 같은 컬럼 환각의 영구 재발을 차단한다(자율성장 시동).
#
# 파일 시작 함수 목록:
#   test_worker_saves_real_columns : 워커가 실제 컬럼을 db_schema 지식으로 저장
#   test_worker_skips_empty        : 컬럼 조회 실패 테이블은 저장 생략
#   test_from_error_gated_by_pgcode: 스키마 오류코드에만 학습 트리거
#   test_integration_bad_column    : 실 db_read_query 컬럼오류 → 자가학습 발동(통합)
# ══════════════════════════════════════════════════════════════════════════════
import threading
import time

from agri_ai_core.src.ai import tools_db


def _join_daemons(timeout=3):
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon:
            t.join(timeout=timeout)


def test_worker_saves_real_columns(monkeypatch):
    saved = []
    monkeypatch.setattr(tools_db, "_columns_of",
                        lambda t: ["farm_id", "hous_id", "recd_dttm"] if t == "relay_l_recording" else [])

    def fake_save(text, category="general", source="learned", key=None):
        saved.append({"text": text, "category": category, "source": source, "key": key})
        return {"success": True}

    monkeypatch.setattr("agri_ai_core.src.ai.system_knowledge.save_system_knowledge", fake_save)

    tools_db._autolearn_schema_worker(["relay_l_recording"])
    assert len(saved) == 1
    s = saved[0]
    assert s["key"] == "cols_relay_l_recording"
    assert s["category"] == "db_schema" and s["source"] == "auto_selfheal"
    assert "hous_id" in s["text"] and "recd_dttm" in s["text"]


def test_worker_skips_empty(monkeypatch):
    saved = []
    monkeypatch.setattr(tools_db, "_columns_of", lambda t: [])   # 조회 실패
    monkeypatch.setattr("agri_ai_core.src.ai.system_knowledge.save_system_knowledge",
                        lambda *a, **k: saved.append(1))
    tools_db._autolearn_schema_worker(["no_such_table"])
    assert saved == []                                           # 저장 생략


def test_from_error_gated_by_pgcode(monkeypatch):
    spawned = {"n": 0}
    monkeypatch.setattr(tools_db, "_autolearn_schema_worker", lambda tables: spawned.__setitem__("n", spawned["n"] + 1))

    class Exc:
        def __init__(self, code):
            self.pgcode = code

    # 스키마 오류 → 학습 트리거
    tools_db._autolearn_schema_from_error("SELECT x FROM relay_l_recording", Exc("42703"))
    _join_daemons()
    assert spawned["n"] == 1

    # 비-스키마 오류(예: 구문오류) → 트리거 안 함
    tools_db._autolearn_schema_from_error("SELECT 1 FROM relay_l_recording", Exc("42601"))
    _join_daemons()
    assert spawned["n"] == 1


def test_integration_bad_column(monkeypatch):
    # 실 DB 에 존재하는 테이블 + 없는 컬럼 → 자가교정 힌트 + 자가학습 발동.
    # save_system_knowledge 는 캡처(실 임베딩/ChromaDB 오염 방지).
    captured = []
    monkeypatch.setattr("agri_ai_core.src.ai.system_knowledge.save_system_knowledge",
                        lambda text, **k: (captured.append((text, k)), {"success": True})[1])

    r = tools_db.db_read_query("SELECT no_such_col_xyz FROM relay_l_recording", limit=1)
    assert r["success"] is False
    assert "💡" in r.get("error", "")            # 자가교정 힌트 동봉
    _join_daemons()                              # 비동기 학습 완료 대기
    assert any(k.get("key") == "cols_relay_l_recording" for _, k in captured)
    learned = next(t for t, k in captured if k.get("key") == "cols_relay_l_recording")
    assert "hous_id" in learned                  # 실제 컬럼 반영
