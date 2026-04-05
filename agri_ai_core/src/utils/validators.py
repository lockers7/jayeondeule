# ═════════════════════════════════════════════════════════════════════════════
# 데이터 검증 모듈 - is_true, clean_sensor_value, parse_boolean 등 유효성 검사.
# ═════════════════════════════════════════════════════════════════════════════

import re
from decimal import Decimal


# ═══════════════════════════════════════════════
# 환경변수 등 문자열 값을 불리언 참/거짓으로 판단
# ═══════════════════════════════════════════════
def is_true(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


# ══════════════════════════════════════════
# 센서 값을 float로 정리/변환 (소수점 2자리)
# ══════════════════════════════════════════
def clean_sensor_value(value):
    try:
        if value is None:
            return 0.0

        if isinstance(value, (int, float, Decimal)):
            return round(float(value), 2)

        if isinstance(value, str):
            value = value.strip()
            if not value:
                return 0.0

            match = re.search(r"[-+]?[0-9]*\.?[0-9]+", value)
            if match:
                return round(float(match.group()), 2)

        return round(float(value), 2)
    except (ValueError, TypeError):
        return 0.0


# ══════════════════════════════════
# 다양한 형태의 값을 불리언으로 변환
# ══════════════════════════════════
def parse_boolean(value):
    if value is None:
        return False

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    if isinstance(value, str):
        return value.lower() in ('true', 't', 'yes', 'y', '1')

    return False


