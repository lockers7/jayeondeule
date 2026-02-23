# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 질의 통계 수집기
# LLM 응답 시간, 도구 호출 패턴, 검색 성공률 등을 인메모리로 수집하여 /api/v1/stats로 제공
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import time
import threading
from collections import defaultdict
from typing import Any, Dict, List, Optional


class StatsCollector:
    """Thread-safe 인메모리 통계 수집기."""

    def __init__(self, max_recent: int = 100):
        self._lock = threading.Lock()
        self._max_recent = max_recent

        # 카운터
        self._query_count = 0
        self._query_success = 0
        self._query_error = 0

        # 도구 사용 빈도
        self._tool_usage: Dict[str, int] = defaultdict(int)

        # 응답 유형 빈도
        self._response_types: Dict[str, int] = defaultdict(int)

        # 검색 provider 빈도
        self._search_providers: Dict[str, int] = defaultdict(int)
        self._search_failures = 0

        # 최근 N건 응답 시간 (슬라이딩 윈도우)
        self._recent_times: List[float] = []

        # 시작 시간
        self._start_time = time.time()

    def record_query(
        self,
        success: bool,
        processing_time: float,
        tools_used: Optional[List[str]] = None,
        response_type: Optional[str] = None,
        search_provider: Optional[str] = None,
    ):
        """질의 결과를 기록."""
        with self._lock:
            self._query_count += 1
            if success:
                self._query_success += 1
            else:
                self._query_error += 1

            # 응답 시간 기록
            self._recent_times.append(processing_time)
            if len(self._recent_times) > self._max_recent:
                self._recent_times = self._recent_times[-self._max_recent:]

            # 도구 사용 기록
            if tools_used:
                for tool in tools_used:
                    self._tool_usage[tool] += 1

            # 응답 유형 기록
            if response_type:
                self._response_types[response_type] += 1

    def record_search(self, provider: str, success: bool):
        """검색 provider 사용을 기록."""
        with self._lock:
            if success:
                self._search_providers[provider] += 1
            else:
                self._search_failures += 1

    def get_stats(self) -> Dict[str, Any]:
        """현재 통계 반환."""
        with self._lock:
            uptime = time.time() - self._start_time

            # 응답 시간 통계
            times = self._recent_times
            avg_time = sum(times) / len(times) if times else 0
            min_time = min(times) if times else 0
            max_time = max(times) if times else 0

            return {
                "uptime_seconds": round(uptime, 1),
                "queries": {
                    "total": self._query_count,
                    "success": self._query_success,
                    "error": self._query_error,
                    "success_rate": round(
                        self._query_success / self._query_count * 100, 1
                    ) if self._query_count > 0 else 0,
                },
                "response_time": {
                    "avg": round(avg_time, 2),
                    "min": round(min_time, 2),
                    "max": round(max_time, 2),
                    "recent_count": len(times),
                },
                "tools": dict(self._tool_usage),
                "response_types": dict(self._response_types),
                "search": {
                    "providers": dict(self._search_providers),
                    "failures": self._search_failures,
                },
            }

    def reset(self):
        """통계 초기화."""
        with self._lock:
            self._query_count = 0
            self._query_success = 0
            self._query_error = 0
            self._tool_usage.clear()
            self._response_types.clear()
            self._search_providers.clear()
            self._search_failures = 0
            self._recent_times.clear()
            self._start_time = time.time()


# 글로벌 싱글턴
_stats_instance: Optional[StatsCollector] = None
_stats_lock = threading.Lock()


def get_stats_collector() -> StatsCollector:
    global _stats_instance
    if _stats_instance is None:
        with _stats_lock:
            if _stats_instance is None:
                _stats_instance = StatsCollector()
    return _stats_instance
