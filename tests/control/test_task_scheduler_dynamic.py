# ═══════════════════════════════════════════════════════════════════════════
# 단위테스트 — task_scheduler 동적 스케줄 (SCHEDULE_M_SETTING 기반).
#
# 검증 항목:
#   1) _add_job_from_row 가 interval row → IntervalTrigger 등록
#   2) _add_job_from_row 가 cron row → CronTrigger 등록
#   3) _add_job_from_row 가 매핑 없는 task → False 반환
#   4) _reload_jobs_from_db 가 enabled=false row → remove_job
#   5) _reload_jobs_from_db 가 ai_control_loop → skip (별도 스레드)
#   6) _schedule_polling_tick 이 max(updt_dttm) 변경 감지 → reload
#   7) cron_expr 변경 후 reload → 새 trigger 적용
#
# APScheduler 의 _scheduler 와 DB reader 를 monkeypatch 로 격리.
# ═══════════════════════════════════════════════════════════════════════════
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import agri_ai_core.src.control.task_scheduler as ts


# ════════════════════════════════════════════════════════════════════
# 헬퍼 — fake APScheduler 와 callable 매핑 셋업
# ════════════════════════════════════════════════════════════════════
class FakeScheduler:
    """APScheduler 흉내 — add_job/get_job/remove_job 만 지원."""
    def __init__(self):
        self.jobs = {}    # id -> {func, trigger}
        self.running = True

    def add_job(self, func, trigger=None, id=None, replace_existing=True, **kwargs):
        self.jobs[id] = {'func': func, 'trigger': trigger}

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def remove_job(self, job_id):
        self.jobs.pop(job_id, None)


@pytest.fixture
def fake_scheduler(monkeypatch):
    fs = FakeScheduler()
    monkeypatch.setattr(ts, '_scheduler', fs)
    return fs


@pytest.fixture
def callables_setup(monkeypatch):
    fns = {
        'relay_control_job': MagicMock(name='manual_control_func'),
        'stats_job':         MagicMock(name='stats_func'),
        'learning_job':      MagicMock(name='learning_func'),
        'lotto_weekly_job':  MagicMock(name='lotto_func'),
    }
    monkeypatch.setattr(ts, '_JOB_CALLABLES', fns)
    return fns


# ════════════════════════════════════════════════════════════════════
# 1) interval row 등록
# ════════════════════════════════════════════════════════════════════
def test_add_job_from_row_interval(fake_scheduler, callables_setup):
    row = {
        'task_name': 'relay_control_job',
        'enabled': True,
        'schedule_type': 'interval',
        'interval_seconds': 5,
        'cron_expr': None,
    }
    ok = ts._add_job_from_row(row)
    assert ok is True
    job = fake_scheduler.get_job('relay_control_job')
    assert job is not None
    assert isinstance(job['trigger'], IntervalTrigger)


# ════════════════════════════════════════════════════════════════════
# 2) cron row 등록
# ════════════════════════════════════════════════════════════════════
def test_add_job_from_row_cron(fake_scheduler, callables_setup):
    row = {
        'task_name': 'lotto_weekly_job',
        'enabled': True,
        'schedule_type': 'cron',
        'interval_seconds': None,
        'cron_expr': '0 22 * * 6',
    }
    ok = ts._add_job_from_row(row)
    assert ok is True
    job = fake_scheduler.get_job('lotto_weekly_job')
    assert job is not None
    assert isinstance(job['trigger'], CronTrigger)


# ════════════════════════════════════════════════════════════════════
# 3) callable 매핑 없는 task 는 등록 안 됨
# ════════════════════════════════════════════════════════════════════
def test_add_job_from_row_unknown_task(fake_scheduler, callables_setup):
    row = {
        'task_name': '__no_such_task__',
        'enabled': True,
        'schedule_type': 'interval',
        'interval_seconds': 5,
    }
    ok = ts._add_job_from_row(row)
    assert ok is False
    assert fake_scheduler.get_job('__no_such_task__') is None


# ════════════════════════════════════════════════════════════════════
# 4) cron_expr 잘못된 표현식 — False 반환, 등록 안 됨
# ════════════════════════════════════════════════════════════════════
def test_add_job_from_row_invalid_cron(fake_scheduler, callables_setup):
    row = {
        'task_name': 'lotto_weekly_job',
        'enabled': True,
        'schedule_type': 'cron',
        'cron_expr': 'INVALID CRON',
    }
    ok = ts._add_job_from_row(row)
    assert ok is False
    assert fake_scheduler.get_job('lotto_weekly_job') is None


# ════════════════════════════════════════════════════════════════════
# 5) _reload_jobs_from_db — enabled=false row 는 등록 해제
# ════════════════════════════════════════════════════════════════════
def test_reload_disables_when_enabled_false(fake_scheduler, callables_setup, monkeypatch):
    # 사전: 이미 stats_job 등록되어 있음
    fake_scheduler.add_job(callables_setup['stats_job'], trigger=IntervalTrigger(seconds=600), id='stats_job')

    fake_rows = [{
        'task_name': 'stats_job', 'enabled': False,
        'schedule_type': 'interval', 'interval_seconds': 600, 'cron_expr': None,
    }]

    def _fake_read_settings(): return fake_rows
    def _fake_read_max_updt(): return datetime.now()
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_schedule_settings', _fake_read_settings)
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_schedule_max_updt', _fake_read_max_updt)

    ok = ts._reload_jobs_from_db()
    assert ok is True
    assert fake_scheduler.get_job('stats_job') is None  # 제거됨


# ════════════════════════════════════════════════════════════════════
# 6) _reload_jobs_from_db — ai_control_loop 은 skip
# ════════════════════════════════════════════════════════════════════
def test_reload_skips_ai_control_loop(fake_scheduler, callables_setup, monkeypatch):
    fake_rows = [
        {'task_name': 'ai_control_loop', 'enabled': True,
         'schedule_type': 'interval', 'interval_seconds': 60, 'cron_expr': None},
        {'task_name': 'stats_job', 'enabled': True,
         'schedule_type': 'interval', 'interval_seconds': 600, 'cron_expr': None},
    ]

    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_schedule_settings', lambda: fake_rows)
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_schedule_max_updt', lambda: datetime.now())

    ts._reload_jobs_from_db()
    assert fake_scheduler.get_job('ai_control_loop') is None  # 등록 안 됨
    assert fake_scheduler.get_job('stats_job') is not None    # 정상 등록


# ════════════════════════════════════════════════════════════════════
# 7) _schedule_polling_tick — max_updt 변경 감지 시 reload
# ════════════════════════════════════════════════════════════════════
def test_polling_tick_reloads_on_change(fake_scheduler, callables_setup, monkeypatch):
    base_time = datetime.now()
    state = {'updt': base_time, 'reload_count': 0}

    def _fake_max_updt(): return state['updt']
    def _fake_settings():
        return [{'task_name': 'stats_job', 'enabled': True,
                 'schedule_type': 'interval', 'interval_seconds': 600, 'cron_expr': None}]
    def _fake_reload():
        state['reload_count'] += 1
        ts._LAST_SCHEDULE_UPDT = state['updt']
        return True

    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_schedule_max_updt', _fake_max_updt)
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_schedule_settings', _fake_settings)
    monkeypatch.setattr(ts, '_reload_jobs_from_db', _fake_reload)

    # 초기 상태
    ts._LAST_SCHEDULE_UPDT = base_time

    # 변경 없음 → reload 안 호출
    ts._schedule_polling_tick()
    assert state['reload_count'] == 0

    # updt_dttm 변경 → reload 호출
    state['updt'] = base_time + timedelta(seconds=10)
    ts._schedule_polling_tick()
    assert state['reload_count'] == 1


# ════════════════════════════════════════════════════════════════════
# 8) _schedule_polling_tick — DB 조회 실패 시 silent (예외 누설 X)
# ════════════════════════════════════════════════════════════════════
def test_polling_tick_silent_on_db_error(fake_scheduler, callables_setup, monkeypatch):
    def _broken(*a, **k):
        raise RuntimeError("DB down")

    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_schedule_max_updt', _broken)

    # 예외 누설 안 됨
    ts._schedule_polling_tick()  # No raise


# ════════════════════════════════════════════════════════════════════
# 9) cron_expr 변경 후 reload → 새 trigger 등록 (기존 교체)
# ════════════════════════════════════════════════════════════════════
def test_reload_replaces_trigger_on_cron_change(fake_scheduler, callables_setup, monkeypatch):
    # 사전: lotto 가 매주 토 22:00 으로 등록되어 있음
    fake_scheduler.add_job(callables_setup['lotto_weekly_job'],
                           trigger=CronTrigger.from_crontab('0 22 * * 6'),
                           id='lotto_weekly_job')

    new_rows = [{
        'task_name': 'lotto_weekly_job', 'enabled': True,
        'schedule_type': 'cron', 'interval_seconds': None,
        'cron_expr': '30 23 * * 6',  # 22:00 → 23:30 변경
    }]

    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_schedule_settings', lambda: new_rows)
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_schedule_max_updt', lambda: datetime.now())

    ts._reload_jobs_from_db()

    job = fake_scheduler.get_job('lotto_weekly_job')
    assert job is not None
    assert isinstance(job['trigger'], CronTrigger)
    # CronTrigger 의 hour 필드 확인
    fields = {f.name: str(f) for f in job['trigger'].fields}
    assert fields.get('hour') == '23'
    assert fields.get('minute') == '30'
