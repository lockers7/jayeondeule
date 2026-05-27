# ══════════════════════════════════════════════════════════════════════════════
# test_tools_db_and_prompt — LLM 자율 DB조회·프롬프트 자가관리 도구 검증
#
# 파일 시작 함수 목록:
#   test_db_list_tables            : 테이블 목록 실조회
#   test_db_describe_table         : 컬럼 구조 실조회
#   test_db_read_query_select      : SELECT 정상 + LIMIT 자동 부가
#   test_db_read_query_blocks_dml  : 쓰기/DDL/다중문장 전부 거부
#   test_db_write_guards           : 쓰기 도구 다층 가드 (관리자·WHERE·보호테이블 등)
#   test_db_write_roundtrip        : 실쓰기 왕복 + 백업·감사 기록
#   test_manage_prompt_list_get    : 프롬프트 블록 목록·본문 조회
#   test_manage_prompt_update_admin_only : update 는 관리자 전용 + 실갱신·복원
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.ai.tools_db import db_list_tables, db_describe_table, db_read_query
from agri_ai_core.src.ai.tools_admin import manage_control_prompt


def test_db_list_tables():
    r = db_list_tables()
    assert r["success"] is True and r["count"] > 10
    assert "farm_m_info" in r["tables"]


def test_db_describe_table():
    r = db_describe_table("farm_m_info")
    assert r["success"] is True and "farm_name" in r["columns"]
    assert db_describe_table("no_such; drop")["success"] is False


def test_db_read_query_select():
    r = db_read_query("SELECT farm_id, farm_name FROM farm_m_info ORDER BY farm_id")
    assert r["success"] is True and r["count"] >= 2
    assert "고흥뜰에" in r["rows"]


def test_db_read_query_blocks_dml():
    assert db_read_query("UPDATE farm_m_info SET farm_name='x'")["success"] is False
    assert db_read_query("DELETE FROM shop_user")["success"] is False
    assert db_read_query("SELECT 1; DROP TABLE farm_m_info")["success"] is False
    assert db_read_query("DROP TABLE farm_m_info")["success"] is False
    # 서브쿼리 위장 거부 (키워드 단어경계)
    assert db_read_query("SELECT * FROM farm_m_info WHERE farm_id IN (SELECT 1) FOR UPDATE")["success"] is False


def test_manage_prompt_list_get():
    r = manage_control_prompt("list")
    assert r["success"] is True and "CTRL_" in r["blocks"]
    g = manage_control_prompt("get", block_id="CTRL_ROLE")
    assert g["success"] is True and len(g["block"]["body_text"] or "") > 10


def test_manage_prompt_update_admin_only():
    # 비관리자(농장계정) 거부
    r = manage_control_prompt("update", block_id="CTRL_ROLE",
                              body_text="x", auth_farm_id="1")
    assert r["success"] is False and "관리자" in r["error"]
    # 관리자 실갱신 → 즉시 복원 (라이브 프롬프트 무영향 왕복 검증)
    orig = manage_control_prompt("get", block_id="CTRL_ROLE")["block"]["body_text"]
    up = manage_control_prompt("update", block_id="CTRL_ROLE",
                               body_text=orig + "\n<!--test-->", auth_farm_id=None)
    assert up["success"] is True
    now = manage_control_prompt("get", block_id="CTRL_ROLE")["block"]["body_text"]
    assert now.endswith("<!--test-->")
    back = manage_control_prompt("update", block_id="CTRL_ROLE",
                                 body_text=orig, auth_farm_id=None)
    assert back["success"] is True
    assert manage_control_prompt("get", block_id="CTRL_ROLE")["block"]["body_text"] == orig


# 2026-07-17 농장주 지시로 전면 개방 — 보호 테이블 4개만 경계로 남았다.
# ⛔ 이 테스트는 실 DB 를 건드리므로 절대 실테이블에 성공하는 SQL 을 쓰지 말 것.
#   (구 버전은 "WHERE 필수" 를 검증한다며 UPDATE farm_m_info SET addr='x' 를
#    실행했고, 개방 후 실제로 전 농장 주소를 덮어썼다 — 감사백업으로 복원함.)
def test_db_write_guards():
    from agri_ai_core.src.ai.tools_db import db_write_query
    # 보호 테이블 — 모든 구문으로 차단(우회 불가)
    for sql in ("DELETE FROM relay_l_recording WHERE farm_id=1",
                "DROP TABLE relay_l_recording",
                "TRUNCATE TABLE sensor_l_recording",
                "ALTER TABLE kakao_token_m ADD COLUMN x int",
                "DELETE FROM db_write_audit",
                "DROP TABLE public.relay_l_recording",
                "CREATE VIEW v AS SELECT * FROM relay_l_recording"):
        r = db_write_query(sql, auth_farm_id=None)
        assert r["success"] is False, f"보호 테이블 우회됨: {sql}"
        assert "보호 테이블" in r["error"], f"차단 사유 불명확: {sql}"
    # 관리자 전용
    assert "관리자" in db_write_query(
        "UPDATE farm_m_info SET addr=addr WHERE farm_id=1", auth_farm_id="1")["error"]
    # 다중 문장 금지 (보호 테이블 검사 우회 방지의 전제)
    assert db_write_query("UPDATE external_api_m SET x=1 WHERE 1=1; DROP TABLE y",
                          auth_farm_id=None)["success"] is False
    # 쓰기 구문이 아니면 거부
    assert db_write_query("SELECT 1", auth_farm_id=None)["success"] is False


def test_db_write_allows_delete_and_ddl():
    # 보호 테이블 외에는 DELETE·DDL 전면 허용 (2026-07-17 개방)
    from agri_ai_core.src.ai.tools_db import db_write_query
    assert db_write_query("CREATE TABLE _t_guard (id int)", reason="pytest")["success"] is True
    assert db_write_query("INSERT INTO _t_guard VALUES (1)", reason="pytest")["success"] is True
    r = db_write_query("DELETE FROM _t_guard", reason="pytest")   # WHERE 없어도 허용
    assert r["success"] is True and r["verb"] == "DELETE"
    assert db_write_query("ALTER TABLE _t_guard ADD COLUMN z int", reason="pytest")["success"] is True
    assert db_write_query("DROP TABLE _t_guard", reason="pytest")["success"] is True


def test_db_write_roundtrip():
    from agri_ai_core.src.ai.tools_db import db_write_query
    from agri_ai_core.src.postgresql.connection import db_session
    r1 = db_write_query(
        "UPDATE external_api_m SET response_hint = response_hint || ' [pytest]' "
        "WHERE api_name='kma_air_diffusion'", reason="pytest 왕복", auth_farm_id=None)
    assert r1["success"] is True and r1["rows_affected"] == 1 and r1["audit_id"]
    r2 = db_write_query(
        "UPDATE external_api_m SET response_hint = REPLACE(response_hint, ' [pytest]', '') "
        "WHERE api_name='kma_air_diffusion'", reason="pytest 원복", auth_farm_id=None)
    assert r2["success"] is True
    with db_session() as d:
        a = d.fetch_one("SELECT backup_rows IS NOT NULL bk FROM db_write_audit WHERE id=%s",
                        (r1["audit_id"],))
        assert a["bk"] is True  # 변경 전 백업 보존


# ⛔ 회귀 방지 (2026-07-17): db_read_query 는 임의 SELECT 를 허용하므로
#   농장 격리가 없으면 농장주 세션이 타 농장 데이터를 읽을 수 있다.
#   실제 등록 농장: 0(시스템)/1(자연들에)/2(고흥뜰에) — 위험이 실재한다.
def test_farm_isolation_blocks_other_farm():
    from agri_ai_core.src.ai.tools_db import db_read_query
    r = db_read_query("SELECT * FROM farm_m_info WHERE farm_id = 2", auth_farm_id="1")
    assert r["success"] is False
    assert "권한" in r["error"]


def test_farm_isolation_requires_filter_on_scoped_table():
    from agri_ai_core.src.ai.tools_db import db_read_query
    r = db_read_query("SELECT * FROM relay_l_recording", auth_farm_id="1")
    assert r["success"] is False
    assert "farm_id" in r["error"]


def test_farm_isolation_allows_own_farm():
    from agri_ai_core.src.ai.tools_db import db_read_query
    r = db_read_query("SELECT farm_id FROM farm_m_info WHERE farm_id = 1", auth_farm_id="1")
    assert r["success"] is True


def test_system_admin_unrestricted():
    from agri_ai_core.src.ai.tools_db import db_read_query
    for auth in (None, "0"):
        r = db_read_query("SELECT farm_id FROM farm_m_info", auth_farm_id=auth)
        assert r["success"] is True, f"시스템관리자(auth={auth}) 가 차단됨"
