# ══════════════════════════════════════════════════════════
# 날짜 유틸리티 모듈 - 날짜 파싱 및 포맷 변환 함수.
# ══════════════════════════════════════════════════════════

from datetime import datetime


# 다양한 형식의 날짜/시간 문자열을 datetime 객체로 변환
# ══════════════════════════════════════════════════════════
def parse_datetime(dt_str, default_formats=None):
    if not dt_str:
        return None

    if isinstance(dt_str, datetime):
        return dt_str

    formats = default_formats or [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d"
    ]

    for fmt in formats:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue

    return None


