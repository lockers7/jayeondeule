# ══════════════════════════════════════════════════════════════════════════════
# test_parse_time_default_now — schedule_monitor 빈 시각 허용
#
# 대상: agri_ai_core.src.ai.tools_agent._parse_time
#
# 목적:
#   · default_now=True 면 빈 값도 datetime 반환 (예외 없음)
#   · default_now=False (default) 이면 빈 값은 ValueError 유지 (회귀 방지)
#   · default_date 우선 적용 (now 폴백)
#   · 기존 형식 (HH:MM / ISO / YYYY-MM-DD HH:MM) 정상 파싱 유지 (회귀 방지)
#
# 파일 시작 함수 목록:
#   TestDefaultNowEmpty       : 빈 값 + default_now True/False 분기
#   TestDefaultDatePriority   : default_date 가 now 보다 우선
#   TestRegressionFormats     : ISO·HH:MM·풀포맷 회귀 방지
# ══════════════════════════════════════════════════════════════════════════════
from datetime import datetime, timedelta

import pytest

from agri_ai_core.src.ai.tools_agent import _parse_time


# ────────────────────────────────────────────────────────────────────
# 빈 값 + default_now 분기
# ────────────────────────────────────────────────────────────────────
class TestDefaultNowEmpty:
    def test_empty_default_now_true_returns_datetime(self):
        result = _parse_time("", default_now=True)
        assert isinstance(result, datetime)

    def test_empty_default_now_true_with_none(self):
        result = _parse_time(None, default_now=True)
        assert isinstance(result, datetime)

    def test_empty_default_now_false_raises(self):
        with pytest.raises(ValueError, match="시각이 비어있습니다"):
            _parse_time("", default_now=False)

    def test_empty_default_false_default_is_false(self):
        with pytest.raises(ValueError):
            _parse_time("")

    def test_whitespace_default_now_true(self):
        result = _parse_time("   ", default_now=True)
        assert isinstance(result, datetime)


# ────────────────────────────────────────────────────────────────────
# default_date 우선
# ────────────────────────────────────────────────────────────────────
class TestDefaultDatePriority:
    def test_empty_with_default_date(self):
        anchor = datetime(2026, 6, 6, 10, 0, 0)
        result = _parse_time("", default_date=anchor, default_now=True)
        assert result == anchor

    def test_empty_default_now_no_default_date(self):
        before = datetime.now()
        result = _parse_time("", default_now=True)
        after = datetime.now()
        assert before <= result <= after + timedelta(seconds=1)


# ────────────────────────────────────────────────────────────────────
# 기존 포맷 회귀 방지
# ────────────────────────────────────────────────────────────────────
class TestRegressionFormats:
    def test_iso_full(self):
        result = _parse_time("2026-06-06T10:30:00")
        assert result == datetime(2026, 6, 6, 10, 30, 0)

    def test_iso_minutes(self):
        result = _parse_time("2026-06-06T10:30")
        assert result == datetime(2026, 6, 6, 10, 30)

    def test_full_with_seconds(self):
        result = _parse_time("2026-06-06 10:30:15")
        assert result == datetime(2026, 6, 6, 10, 30, 15)

    def test_full_no_seconds(self):
        result = _parse_time("2026-06-06 10:30")
        assert result == datetime(2026, 6, 6, 10, 30)

    def test_hhmm_past_rolls_to_next_day(self):
        anchor = datetime(2026, 6, 6, 12, 0, 0)
        result = _parse_time("06:00", default_date=anchor)
        assert result.date() == datetime(2026, 6, 7).date()
        assert result.hour == 6

    def test_hhmm_future_today_stays(self):
        anchor = datetime(2026, 6, 6, 8, 0, 0)
        result = _parse_time("18:00", default_date=anchor)
        assert result == datetime(2026, 6, 6, 18, 0, 0)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="시각 형식 인식 실패"):
            _parse_time("notatime")
