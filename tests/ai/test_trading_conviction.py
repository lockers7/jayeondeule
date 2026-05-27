# ══════════════════════════════════════════════════════════════════════════════
# test_trading_conviction — 자동매매 3종 개선(데이터/로직층) 단위테스트
#
# A) 팩터 컨빅션 분해·종합점수  B) 근거 데이터 커버리지  C) 포트폴리오 집중도
# ⛔전통 TA 아님 — 우리 이벤트드리븐 팩터를 LLM 이 0~100 판단, 코드는 표시·합산만.
#
# 파일 시작 함수 목록:
#   test_composite_present_only      : 존재하는 팩터만 가중평균
#   test_composite_missing_none      : 팩터 없으면 None(정직)
#   test_composite_weights           : 가중치 반영
#   test_coverage_summary            : 근거 커버리지 요약·신뢰도 레벨
#   test_concentration_warning       : 편중 경고·HHI
#   test_concentration_empty         : 빈 후보 안전
#   test_factor_weights_roundtrip    : 가중치 저장/조회(DB)
#   test_candidate_roundtrip_derived : 후보 저장→list_candidates 파생필드(DB)
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.ai import trading_store as ts


def test_composite_present_only():
    # 3개 팩터만 존재 → 평균 (나머지는 무시, 0 취급 안 함)
    fs = {"event_novelty": 90, "magnitude": 60, "persistence": 30}
    assert ts.composite_conviction(fs) == 60.0


def test_composite_missing_none():
    assert ts.composite_conviction({}) is None
    assert ts.composite_conviction({"unknown": 50}) is None
    assert ts.composite_conviction(None) is None


def test_composite_weights():
    fs = {"event_novelty": 100, "sentiment": 0}
    # event_novelty 3배 가중 → (100*3 + 0*1)/4 = 75
    w = {"event_novelty": 3, "sentiment": 1}
    assert ts.composite_conviction(fs, w) == 75.0
    # 범위 클램프(120→100, -20→0)
    assert ts.composite_conviction({"magnitude": 120, "regime_fit": -20}) == 50.0


def test_coverage_summary():
    dc = {"disclosure": True, "news": True, "supply_demand": False,
          "alt_data": False, "fundamentals": True}
    s = ts.coverage_summary(dc)
    assert s["count"] == 3 and s["total"] == 5
    assert s["ratio"] == 0.6 and s["level"] == "높음"
    assert "수급" in s["missing_labels"] and "공시" in s["available_labels"]
    # 전무 → 낮음
    assert ts.coverage_summary({})["level"] == "낮음"


def test_concentration_warning():
    cands = [
        {"event_type": "자사주취득", "sector": "반도체"},
        {"event_type": "자사주취득", "sector": "반도체"},
        {"event_type": "자사주취득", "sector": "바이오"},
        {"event_type": "실적서프라이즈", "sector": "2차전지"},
    ]
    r = ts.portfolio_concentration(cands, warn_threshold=0.4)
    assert r["total"] == 4
    assert r["by_event_type"]["자사주취득"]["count"] == 3
    assert r["max_concentration"]["group"] == "자사주취득"
    assert abs(r["max_concentration"]["share"] - 0.75) < 1e-6
    assert r["warning"] is True and r["notes"]
    assert r["hhi"] is not None


def test_concentration_empty():
    r = ts.portfolio_concentration([])
    assert r["total"] == 0 and r["warning"] is False
    assert r["max_concentration"] is None


def test_factor_weights_roundtrip():
    ts.set_factor_weights({"event_novelty": 2.0, "sentiment": 0.5})
    w = ts.get_factor_weights()
    assert w["event_novelty"] == 2.0 and w["sentiment"] == 0.5
    # 미지정 팩터는 기본 1.0
    assert w["magnitude"] == 1.0
    # 원복(다른 테스트 오염 방지)
    ts.set_factor_weights({k: 1.0 for k in ts.FACTOR_KEYS})


def test_candidate_roundtrip_derived():
    from agri_ai_core.src.ai.tools_agent_trade import agent_save_trade_candidate
    import time
    code = "T" + time.strftime("%H%M%S")
    r = agent_save_trade_candidate(
        stock_code=code, stock_name="테스트컨빅션", event_type="자사주취득",
        thesis="단위테스트", expected_return_pct=7, confidence=0.7,
        sector="반도체",
        factor_scores={"event_novelty": 80, "magnitude": 70, "persistence": 60},
        data_coverage={"disclosure": True, "news": True})
    assert r["success"]
    rows = ts.list_candidates()
    mine = next((c for c in rows if c["stock_code"] == code), None)
    assert mine is not None
    assert mine["sector"] == "반도체"
    assert mine["conviction"] == 70.0            # (80+70+60)/3
    assert mine["coverage"]["count"] == 2         # 공시·뉴스
    assert mine["coverage"]["level"] == "보통"    # 2/5=0.4
    # 정리
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        d.execute_query("DELETE FROM trading_candidate WHERE stock_code=%s", (code,))


def test_rationale_roundtrip():
    # LLM 서술(rationale)이 저장→조회로 왕복(사람이 읽는 글)
    from agri_ai_core.src.ai.tools_agent_trade import agent_save_trade_candidate
    from agri_ai_core.src.postgresql.connection import db_session
    import time
    code = "R" + time.strftime("%H%M%S")
    story = ("자사주 3천억 취득 공시. 주주환원+저평가 시그널로 단기 수급 개선 기대. "
             "반도체 업황 회복과 맞물려 발표 후 수일 드리프트 가능. 리스크: 선반영 시 효과 제한.")
    r = agent_save_trade_candidate(stock_code=code, stock_name="서술테스트",
                                   event_type="자사주취득", thesis="자사주 취득",
                                   selection_type="추천", data_coverage={"disclosure": True},
                                   rationale=story)
    assert r["success"]
    c = next(x for x in ts.list_candidates() if x["stock_code"] == code)
    assert c["rationale"] == story
    assert c["selection_type"] == "추천"      # 근거(공시) 있어 추천 유지
    with db_session() as d:
        d.execute_query("DELETE FROM trading_candidate WHERE stock_code=%s", (code,))


def test_honest_selection_type():
    # 실제 호재 이벤트 → 추천 유지
    assert ts.honest_selection_type("추천", "자사주취득", {"disclosure": True}, "자사주 취득 공시") == "추천"
    # 이벤트 없음 + 근거 전무 → '추천'이라도 '임의'로 정직 강등(농장주 지적 케이스)
    assert ts.honest_selection_type("추천", "없음", {"disclosure": False, "news": False}, "호재 없음") == "임의"
    assert ts.honest_selection_type("추천", "", None, None) == "임의"
    # 이벤트 없어도 근거 커버리지 하나라도 있으면 추천 유지(LLM 판단 존중)
    assert ts.honest_selection_type("추천", "없음", {"news": True}, "뉴스 기반") == "추천"
    # 임의·불가는 그대로, 잘못된 값은 임의
    assert ts.honest_selection_type("임의", "없음", None, None) == "임의"
    assert ts.honest_selection_type("불가", "감자", None, "악재") == "불가"
    assert ts.honest_selection_type("이상값", None, None, None) == "임의"


def test_selection_type_roundtrip_and_order():
    # 추천/임의/불가 저장 → 정렬(추천 우선) 확인
    from agri_ai_core.src.ai.tools_agent_trade import agent_save_trade_candidate
    from agri_ai_core.src.postgresql.connection import db_session
    import time
    base = time.strftime("%H%M%S")
    picks = [("A" + base, "임의", 3), ("B" + base, "추천", 5), ("C" + base, "불가", 0)]
    for code, sel, ret in picks:
        agent_save_trade_candidate(stock_code=code, stock_name="선정" + sel,
                                   event_type="테스트", expected_return_pct=ret,
                                   selection_type=sel)
    rows = [c for c in ts.list_candidates() if c["stock_code"] in {p[0] for p in picks}]
    types = [c["selection_type"] for c in rows]
    assert types == ["추천", "임의", "불가"]      # 정렬 우선순위
    # 잘못된 값·미지정은 '임의'로 방어(근거 없는 추천 남발 금지)
    agent_save_trade_candidate(stock_code="Z" + base, stock_name="방어",
                               event_type="테스트", selection_type="이상값")
    z = next(c for c in ts.list_candidates() if c["stock_code"] == "Z" + base)
    assert z["selection_type"] == "임의"
    with db_session() as d:
        for code, _, _ in picks:
            d.execute_query("DELETE FROM trading_candidate WHERE stock_code=%s", (code,))
        d.execute_query("DELETE FROM trading_candidate WHERE stock_code=%s", ("Z" + base,))
