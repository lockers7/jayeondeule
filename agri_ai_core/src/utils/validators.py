# ════════════════════════════════════════════════════════════════════
# 데이터 검증 — 불리언/센서값 정규화 헬퍼.
# --->
# is_true            : 문자열을 불리언 참/거짓으로 판단 (환경변수 등)
# clean_sensor_value : 센서 값을 float 로 정리·변환 (소수점 2자리)
# parse_boolean     : 다양한 형태의 값을 불리언으로 변환
# ════════════════════════════════════════════════════════════════════
import re
from decimal import Decimal


# ────────────────────────────────────────────────────────────────────
# 환경변수 등 문자열 값을 불리언 참/거짓으로 판단.
# ────────────────────────────────────────────────────────────────────
def is_true(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


# ────────────────────────────────────────────────────────────────────
# 센서 값을 float 로 정리·변환 (소수점 2자리). 실패 시 0.0.
# ────────────────────────────────────────────────────────────────────
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


# ────────────────────────────────────────────────────────────────────
# 다양한 형태(bool/int/float/str/None)의 값을 불리언으로 변환.
# ────────────────────────────────────────────────────────────────────
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


