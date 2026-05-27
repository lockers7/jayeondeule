# ══════════════════════════════════════════════════════════════════════════════
# test_rule_mining_no_fallback — 마이닝 fallback 오염 제거 검증
#
# 룰 후보 마이닝(analyze_decision_patterns)이 [algorithm_fallback] 결정을
# 포함하면 장애기간 알고리즘 행동이 승인 → LLM 지식으로 굳음(LLM 100% 원칙 위배).
# 쿼리 제외 필터 + 실DB 표본으로 회귀 방지.
#
# 파일 시작 함수 목록:
#   test_query_excludes_fallback      : 소스 쿼리에 제외 필터 존재
#   test_live_samples_have_no_fallback: 실DB 마이닝 표본에 fallback 사유 0건
# ══════════════════════════════════════════════════════════════════════════════
import inspect


def test_query_excludes_fallback():
    from agri_ai_core.src.control import ai_self_evolve as m
    src = inspect.getsource(m.analyze_decision_patterns)
    assert "NOT LIKE '[algorithm_fallback]%%'" in src


def test_live_samples_have_no_fallback():
    from agri_ai_core.src.control.ai_self_evolve import analyze_decision_patterns
    # 필터가 없으면 fallback 표본이 섞일 수 있는 14일 창으로 검증
    rows = analyze_decision_patterns(1, days=14, min_freq=3, top_k=20)
    bad = [
        r for r in rows
        for reason in (r.get('sample_reasons') or [])
        if str(reason).startswith('[algorithm_fallback]')
    ]
    assert bad == [], f"fallback 표본 잔존: {bad[:2]}"
