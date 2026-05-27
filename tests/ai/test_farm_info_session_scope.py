# ══════════════════════════════════════════════════════════════════════════════
# test_farm_info_session_scope — 답변 프롬프트 [농장 기본 정보]의 세션 농장 필터
#
# 농장주 룰: 특정 농장 세션이면 그 농장 기준으로만 답한다 (타 농장 주소가
# 프롬프트에 섞이면 답변 LLM 이 타 지역까지 답변 — 콩국수/고흥 실사고).
# 시스템 농장(관리자, farm_id None/'0') 세션만 전체 농장을 나열한다.
#
# 파일 시작 함수 목록:
#   test_single_farm_session_filters   : farm_id 지정 시 해당 농장 정보만
#   test_admin_session_lists_all       : None/'0' 세션은 전체 농장 나열
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.ai.llm_response_processing import _build_farm_info_text


def _farms_in(text):
    return (text or "").count("농장명:")


def test_single_farm_session_filters():
    info = _build_farm_info_text("1")
    assert info and _farms_in(info) == 1
    assert "자연들에" in info and "고흥" not in info
    # 재배사 목록도 세션 농장 것만
    assert "재배사:" in info


def test_admin_session_lists_all():
    for fid in (None, "0"):
        info = _build_farm_info_text(fid)
        assert info and _farms_in(info) >= 2


def test_system_status_scope():
    # 시스템 세션(0) → 전체 실농장 순회(개발 99호 제외) / 개별 농장 → 단일
    from agri_ai_core.src.ai.tools_data import get_system_status
    r = get_system_status("0")
    assert r.get("scope") == "all_farms" and len(r.get("farms", [])) >= 2
    assert all(h["house_id"] != "99" for f in r["farms"] for h in f.get("houses", []))
    r1 = get_system_status("1")
    assert r1.get("farm_id") == "1" and "farms" not in r1


def test_system_status_operation_mode():
    # 유효 운용방식 3값 — mnul_ctrl_flag=False 가 수동(필드명과 반대 의미) 불변식
    from agri_ai_core.src.ai.tools_data import get_system_status
    r = get_system_status("0")
    for f in r["farms"]:
        for h in f["houses"]:
            assert h["operation_mode"] in ("수동(사용자 직접입력)", "알고리즘", "AI")
            assert (not h["mnul_ctrl_flag"]) == h["operation_mode"].startswith("수동")
            if h["operation_mode"] == "AI":
                assert h["mnul_ctrl_flag"] and h["ctrl_type"] == "ai"
