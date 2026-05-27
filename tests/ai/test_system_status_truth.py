# ══════════════════════════════════════════════════════════════════════════════
# test_system_status_truth — get_system_status 가 거짓을 말하지 않는지 (2026-07-17)
#
# ⛔ 실측 사고: 농장주가 "각 서비스 상태 확인하고 보고하라" 하자 LLM 이
#   "AI 제어 루프 실행 중이지 않음 / 스케줄러 실행 중이지 않음 / 마지막 센서
#   2025-12-02" 라고 보고했다. 전부 거짓이었고 LLM 잘못이 아니라 도구가
#   거짓 데이터를 준 것이다. 원인 3가지 — 전부 같은 뿌리(프로세스 경계):
#     ① _ai_loop_running  : 스케줄러 프로세스의 메모리 변수 → FastAPI 에선 항상 False
#     ② task_scheduler._scheduler : 동일 → running=False, jobs=[]
#     ③ last_get_dttm     : UPDATE 코드 0건인 죽은 컬럼 (2025-12-02 고정)
#
# 파일 시작 함수 목록:
#   test_no_cross_process_memory_flags : 메모리 변수로 running 판정 금지
#   test_no_dead_column_for_sensor     : 죽은 last_get_dttm 사용 금지
#   test_running_reflects_reality      : running 이 실제 프로세스 상태와 일치
#   test_sensor_time_is_fresh          : 센서 시각이 실데이터 (수개월 전 금지)
#   test_no_fake_empty_jobs            : 조회 불가한 jobs 를 빈 배열로 주지 않음
# ══════════════════════════════════════════════════════════════════════════════
import inspect
from datetime import datetime, timedelta

import pytest

from agri_ai_core.src.ai import tools_data as td


def test_no_cross_process_memory_flags():
    # ⛔ 다른 프로세스의 메모리 변수를 읽어 상태를 판정하면 항상 거짓이 된다
    src = inspect.getsource(td.get_system_status)
    assert '"_ai_loop_running"' not in src, "_ai_loop_running getattr 부활 — 항상 False 보고"
    assert "task_scheduler import _scheduler" not in src, "_scheduler 직접 참조 부활"


def test_no_dead_column_for_sensor():
    src = inspect.getsource(td.get_system_status)
    assert 'r["last_get_dttm"]' not in src, "죽은 컬럼 last_get_dttm 사용 — 2025-12-02 오보"


def test_running_reflects_reality():
    from agri_ai_core.src.ai.tools_service import _health
    r = td.get_system_status("1")
    actual = _health(("proc", "agri_ai_core.scheduler"))
    assert r["ai_control_loop"]["running"] is actual, "AI 루프 running 이 실제와 불일치"
    assert r["scheduler"]["running"] is actual, "스케줄러 running 이 실제와 불일치"


def test_sensor_time_is_fresh():
    r = td.get_system_status("1")
    houses = [h for h in r.get("houses", []) if h.get("last_sensor_time")]
    if not houses:
        pytest.skip("센서 데이터 없음")
    for h in houses:
        t = datetime.fromisoformat(h["last_sensor_time"])
        age = datetime.now() - t
        # 죽은 컬럼(7개월 전)을 다시 쓰면 여기서 걸린다
        assert age < timedelta(days=30), (
            f"{h['house_id']}호 센서시각이 {age.days}일 전 — 죽은 컬럼 사용 의심")


def test_no_fake_empty_jobs():
    # 다른 프로세스의 APScheduler Job 은 조회 불가하다. 빈 배열을 주면
    # LLM 이 "등록된 작업이 없다"고 오보한다 — 아예 키를 넣지 않아야 한다.
    r = td.get_system_status("1")
    assert "jobs" not in r["scheduler"], "조회 불가한 jobs 를 빈 배열로 반환 — 오보 유발"
    assert "note" in r["scheduler"], "조회 불가 사유 안내 누락"
