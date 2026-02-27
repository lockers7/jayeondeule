"""재배사 정렬 유틸리티 (control 모듈 공용)"""


def to_sortable_int(value):
    """숫자로 변환 가능한 값을 정수로 반환, 실패 시 큰 수 반환."""
    try:
        return int(value)
    except Exception:
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        if digits:
            try:
                return int(digits)
            except Exception:
                pass
    return 10**9


def sort_houses(houses):
    """재배사 목록을 farm_id, hous_id 순으로 정렬."""
    return sorted(
        houses or [],
        key=lambda house: (
            to_sortable_int(house.get("farm_id")),
            to_sortable_int(house.get("hous_id")),
            str(house.get("hous_id") or ""),
        ),
    )
