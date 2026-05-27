# ══════════════════════════════════════════════════════════════════════════════
# test_trading_selfimprove — 주식 자동매매 데이터층 + 자가개선 루프(최소단위)
#
# 수치=PostgreSQL trading_*, 판단·분석·학습=전용 VectorDB(농장관리와 분리).
# 자가개선: 과거 학습 회상 주입 → 실행 결과 자동 학습 → 실적 인사이트 학습.
#
# 파일 시작 함수 목록:
#   test_separable_collection    : trading_knowledge 가 농장 컬렉션과 분리
#   test_knowledge_save_list_recall : 저장→목록→회상(구조 정규화)
#   test_build_learning_context  : 과거 학습 주입 컨텍스트
#   test_auto_learn_from_run     : 실행 결과 자동 학습 저장
#   test_learn_from_performance  : 실적 집계 인사이트 학습
#   test_user_prompt_and_data    : 사용자 프롬프트·데이터 저장/조회
#   test_candidate_list          : trading_candidate 조회
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.ai import trading_store as ts


def test_separable_collection():
    from agri_ai_core.src.chroma.collections import trading_knowledge_collection, document_collection
    assert trading_knowledge_collection() == "trading_knowledge"
    assert trading_knowledge_collection() != document_collection()    # 농장과 분리


def test_knowledge_save_list_recall():
    r = ts.save_trading_knowledge("자기주식취득 이벤트 종목은 발표 다음날 단기 강세, +5% 익절 유효",
                                  category="학습", key="ut_learn_recall")
    assert r["success"]
    lst = ts.list_trading_knowledge(category="학습", limit=20)
    assert any("자기주식취득" in (x.get("text") or "") for x in lst)
    rec = ts.recall_trading_knowledge("자기주식취득 이벤트 매매 판단")   # 구조 정규화로 회상 동작
    assert isinstance(rec, list) and len(rec) >= 1


def test_build_learning_context():
    ts.save_trading_knowledge("실적개선 어닝서프라이즈 종목은 갭상승 후 눌림목 매수 유효",
                              category="학습", key="ut_learn_ctx")
    ctx = ts.build_learning_context(query="어닝서프라이즈 매매")
    assert "과거 매매 학습" in ctx and len(ctx) > 30


def test_auto_learn_from_run():
    cands = [{"stock_name": "테스트A", "stock_code": "000001"},
             {"stock_name": "테스트B", "stock_code": "000002"}]
    r = ts.auto_learn_from_run(cands, final="호재 2종목 선정")
    assert r["success"]
    assert any("자동선정" in (x.get("text") or "") for x in ts.list_learning())


def test_learn_from_performance():
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        d.execute_query("DELETE FROM trading_performance WHERE stock_code='UTPERF'", ())
    ts.record_performance("UTPERF", "실적테스트", buy_price=1000, sell_price=1100, qty=10, pnl=1000, return_pct=10)
    r = ts.learn_from_performance()
    assert r["success"]
    with db_session() as d:
        d.execute_query("DELETE FROM trading_performance WHERE stock_code='UTPERF'", ())


def test_user_prompt_and_data():
    assert ts.set_user_prompt("이벤트 기반 소수정예")["success"]
    assert ts.get_user_prompt() == "이벤트 기반 소수정예"
    assert ts.set_user_data({"capital": "5000000"})["count"] == 1
    assert ts.get_user_data().get("capital") == "5000000"


def test_candidate_list():
    ts.ensure_tables()
    out = ts.list_candidates()           # 오류 없이 리스트 반환
    assert isinstance(out, list)
