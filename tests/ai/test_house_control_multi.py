# ══════════════════════════════════════════════════════════════════════════════
# set_house_control_mode 다중 호기 파싱 회귀 테스트
# 배경(2026-07-19): 채팅 "2·3호 인공지능 변경" 요청이 house_id='2,3' 으로 도구에
#   정확히 전달됐으나, normalize_id('2,3')가 첫 숫자('2')만 뽑아 3호를 조용히 유실.
#   → _normalize_house_list 로 콤마/공백/슬래시 구분 다중 호기를 분리 처리하도록 보완.
# 본 테스트는 DB 없이 파서 순수 로직만 검증(빠르고 CI 안전).
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.ai.tools_admin import _normalize_house_list


def test_comma_separated_houses():
    # 콤마 결합이 각 호기로 분리돼야 한다 (원 버그: '2,3' → '2' 로 축약)
    assert _normalize_house_list("2,3") == ["2", "3"]
    assert _normalize_house_list("1,2,3") == ["1", "2", "3"]


def test_various_separators():
    assert _normalize_house_list("2 3") == ["2", "3"]
    assert _normalize_house_list("2/3") == ["2", "3"]
    assert _normalize_house_list("2, 3 ") == ["2", "3"]


def test_korean_suffix_stripped():
    assert _normalize_house_list("2,3호") == ["2", "3"]
    assert _normalize_house_list("상황버섯2호,3호") == ["2", "3"]


def test_all_keyword_preserved():
    for kw in ("all", "전체", "모든", "모두", "전재배사"):
        assert _normalize_house_list(kw) == ["all"]


def test_single_house():
    assert _normalize_house_list("2") == ["2"]
    assert _normalize_house_list(3) == ["3"]


def test_empty_and_none():
    assert _normalize_house_list("") == []
    assert _normalize_house_list(None) == []


def test_dedup_preserves_order():
    assert _normalize_house_list("3,2,3") == ["3", "2"]
