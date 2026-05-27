# ══════════════════════════════════════════════════════════════════════════════
# test_control_prompts_api — /api/v1/admin/control-prompts CRUD 통합 테스트
#
# 검증:
#   1) GET /control-prompts       — 전체 목록 반환 (단순화 후 14블록, 필수 블록 존재)
#   2) GET /control-prompts?category=system_prompt
#   3) GET /control-prompts/{block_id}   — 단건 조회 (CTRL_ROLE)
#   4) GET /control-prompts/{block_id}   — 미존재 시 404
#   5) POST /control-prompts      — 신규 등록
#   6) PUT  /control-prompts/{id} — 부분 갱신 (name 변경)
#   7) PUT  /control-prompts/{id} — active_yn 토글
#   8) DELETE /control-prompts/{id} — 삭제
#   9) DELETE /control-prompts/{id} — 미존재 시 404
# ══════════════════════════════════════════════════════════════════════════════
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_TEST_BLOCK_ID = "__pytest_ctrl_test_block"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from agri_ai_core.api.app import app
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    # 테스트 row 정리
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM control_prompt_m WHERE block_id = %s",
                        (_TEST_BLOCK_ID,),
                    )
                    conn.commit()
            finally:
                db._putconn(conn)
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════
# 1) 전체 목록 — 단순화 후 필수 블록이 모두 존재
# ════════════════════════════════════════════════════════════════════
# LLM 제어 단순화(control_prompt_m 33→14블록)로 개수 자체가 아니라
# 필수 블록 존재를 검증한다.
_REQUIRED_BLOCKS = {
    "CTRL_ROLE", "CTRL_SEC1", "CTRL_SEC_SEASON", "CTRL_GUIDE",
    "CTRL_SEC6", "CTRL_SEC9", "CTRL_AGENT_SYSTEM",
}


def test_list_all(client):
    res = client.get("/api/v1/admin/control-prompts")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    ids = {p["block_id"] for p in data["prompts"]}
    missing = _REQUIRED_BLOCKS - ids
    assert not missing, f"필수 블록 누락: {missing}"


# ════════════════════════════════════════════════════════════════════
# 2) category 필터
# ════════════════════════════════════════════════════════════════════
def test_list_filter_category(client):
    res = client.get("/api/v1/admin/control-prompts?category=system_prompt")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    # system_prompt 카테고리만 반환
    for p in data["prompts"]:
        assert p["category"] == "system_prompt", f"필터 오류: {p['block_id']} category={p['category']}"
    # system_prompt 6개 (CTRL_ROLE, CTRL_SEC1, CTRL_SEC_SEASON, CTRL_GUIDE, CTRL_SEC6, CTRL_SEC9)
    assert len(data["prompts"]) >= 6


# ════════════════════════════════════════════════════════════════════
# 3) 단건 조회 — CTRL_ROLE 정상
# ════════════════════════════════════════════════════════════════════
def test_get_single_ctrl_role(client):
    res = client.get("/api/v1/admin/control-prompts/CTRL_ROLE")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    p = data["prompt"]
    assert p["block_id"] == "CTRL_ROLE"
    assert p["category"] == "system_prompt"
    assert p["body_text"], "body_text 비어 있음"


# ════════════════════════════════════════════════════════════════════
# 4) 단건 조회 — 미존재 시 404
# ════════════════════════════════════════════════════════════════════
def test_get_single_not_found(client):
    res = client.get("/api/v1/admin/control-prompts/CTRL_NOT_EXIST_XYZ")
    assert res.status_code == 404


# ════════════════════════════════════════════════════════════════════
# 5) 신규 등록 — 필수 필드 + 데이터 확인
# ════════════════════════════════════════════════════════════════════
def test_create_new(client):
    payload = {
        "block_id":    _TEST_BLOCK_ID,
        "section_key": "TEST_SEC",
        "category":    "user_message",
        "name":        "테스트 메시지",
        "body_text":   "테스트 내용 ${PLACEHOLDER}",
        "sort_order":  99,
        "active_yn":   "Y",
    }
    res = client.post("/api/v1/admin/control-prompts", json=payload)
    assert res.status_code == 200, f"등록 실패: {res.text}"
    data = res.json()
    assert data["success"] is True
    assert data["block_id"] == _TEST_BLOCK_ID

    # 등록 후 조회 확인
    res2 = client.get(f"/api/v1/admin/control-prompts/{_TEST_BLOCK_ID}")
    assert res2.status_code == 200
    p = res2.json()["prompt"]
    assert p["body_text"] == "테스트 내용 ${PLACEHOLDER}"
    assert p["category"] == "user_message"


# ════════════════════════════════════════════════════════════════════
# 6) 신규 등록 중복 → 409
# ════════════════════════════════════════════════════════════════════
def test_create_duplicate(client):
    payload = {
        "block_id": _TEST_BLOCK_ID, "section_key": "TEST_SEC",
        "category": "user_message", "name": "중복", "body_text": "중복 내용",
    }
    client.post("/api/v1/admin/control-prompts", json=payload)
    res = client.post("/api/v1/admin/control-prompts", json=payload)
    assert res.status_code == 409


# ════════════════════════════════════════════════════════════════════
# 7) 갱신 — name 변경 후 확인
# ════════════════════════════════════════════════════════════════════
def test_update_name(client):
    # 먼저 등록
    client.post("/api/v1/admin/control-prompts", json={
        "block_id": _TEST_BLOCK_ID, "section_key": "TEST_SEC",
        "category": "user_message", "name": "원래이름", "body_text": "원래내용",
    })
    # 갱신
    res = client.put(
        f"/api/v1/admin/control-prompts/{_TEST_BLOCK_ID}",
        json={"name": "변경된이름", "body_text": "변경된내용"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "name" in data["updated_fields"]
    assert "body_text" in data["updated_fields"]

    # 갱신 후 조회
    p = client.get(f"/api/v1/admin/control-prompts/{_TEST_BLOCK_ID}").json()["prompt"]
    assert p["name"] == "변경된이름"
    assert p["body_text"] == "변경된내용"


# ════════════════════════════════════════════════════════════════════
# 8) active_yn 토글 N → Y
# ════════════════════════════════════════════════════════════════════
def test_update_active_yn(client):
    client.post("/api/v1/admin/control-prompts", json={
        "block_id": _TEST_BLOCK_ID, "section_key": "TEST_SEC",
        "category": "user_message", "name": "토글테스트", "body_text": "내용",
        "active_yn": "Y",
    })
    # N으로 변경
    res = client.put(
        f"/api/v1/admin/control-prompts/{_TEST_BLOCK_ID}",
        json={"active_yn": "N"},
    )
    assert res.status_code == 200
    p = client.get(f"/api/v1/admin/control-prompts/{_TEST_BLOCK_ID}").json()["prompt"]
    assert p["active_yn"] == "N"

    # 다시 Y
    client.put(f"/api/v1/admin/control-prompts/{_TEST_BLOCK_ID}", json={"active_yn": "Y"})
    p2 = client.get(f"/api/v1/admin/control-prompts/{_TEST_BLOCK_ID}").json()["prompt"]
    assert p2["active_yn"] == "Y"


# ════════════════════════════════════════════════════════════════════
# 9) 갱신 — 미존재 시 404
# ════════════════════════════════════════════════════════════════════
def test_update_not_found(client):
    res = client.put(
        "/api/v1/admin/control-prompts/CTRL_NOT_EXIST_XYZ",
        json={"name": "없는것"},
    )
    assert res.status_code == 404


# ════════════════════════════════════════════════════════════════════
# 10) 삭제 + 재조회 404
# ════════════════════════════════════════════════════════════════════
def test_delete(client):
    client.post("/api/v1/admin/control-prompts", json={
        "block_id": _TEST_BLOCK_ID, "section_key": "TEST_SEC",
        "category": "user_message", "name": "삭제테스트", "body_text": "내용",
    })
    res = client.delete(f"/api/v1/admin/control-prompts/{_TEST_BLOCK_ID}")
    assert res.status_code == 200
    assert res.json()["success"] is True

    # 삭제 후 조회 → 404
    res2 = client.get(f"/api/v1/admin/control-prompts/{_TEST_BLOCK_ID}")
    assert res2.status_code == 404


# ════════════════════════════════════════════════════════════════════
# 11) 삭제 — 미존재 시 404
# ════════════════════════════════════════════════════════════════════
def test_delete_not_found(client):
    res = client.delete("/api/v1/admin/control-prompts/CTRL_NOT_EXIST_XYZ")
    assert res.status_code == 404
