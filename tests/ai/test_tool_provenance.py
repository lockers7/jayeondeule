# ══════════════════════════════════════════════════════════════════════════════
# test_tool_provenance — 직전 답변 도구이력 기억·주입(GAP5) 검증
#
# "어떤 로그/도구/데이터로 답했나" 후속 질문이 직전 행위를 정직히 답하도록,
# 세션별 직전 사용도구를 기억했다가 다음 질문 컨텍스트에 시스템 노트로 주입한다.
#
# 파일 시작 함수 목록:
#   test_remember_dedup        : 도구목록 기억(중복제거·순서보존) + 빈값 무시
#   test_inject_into_context   : load_hybrid_context 가 직전 도구 노트를 주입
#   test_no_note_when_unknown  : 기억이 없으면 노트 미주입
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.ai import conversation_context as cc


def _isolate(monkeypatch):
    # 저장소·과거대화 격리 (직전 도구 노트만 검증)
    class _Store:
        def get_recent_turns(self, session_id, n_turns=2):
            return []
    monkeypatch.setattr(cc, "get_conversation_store", lambda: _Store())
    monkeypatch.setattr(cc, "_search_related_conversations", lambda q, f: None)
    cc._last_tools.clear()


def test_remember_dedup():
    cc._last_tools.clear()
    cc.remember_last_tools("s1", ["db_read_query", "search_farm_knowledge", "db_read_query"])
    assert cc._last_tools["s1"] == "db_read_query, search_farm_knowledge"   # 중복제거·순서보존
    # 빈값/None 은 무시
    cc.remember_last_tools("s2", [])
    cc.remember_last_tools(None, ["x"])
    assert "s2" not in cc._last_tools and None not in cc._last_tools


def test_inject_into_context(monkeypatch):
    _isolate(monkeypatch)
    cc.remember_last_tools("sess", ["search_logs", "db_read_query"])
    hist = cc.load_hybrid_context("sess", "어떤 로그 확인했나?", farm_id="1")
    assert hist is not None
    joined = " ".join(t["content"] for t in hist if t.get("role") == "system")
    assert "직전 답변에서 실제 사용한 도구" in joined
    assert "search_logs" in joined and "db_read_query" in joined


def test_no_note_when_unknown(monkeypatch):
    _isolate(monkeypatch)
    hist = cc.load_hybrid_context("sess_없음", "아무 질문", farm_id="1")
    assert hist is None                       # 기억 없음 + 맥락 없음 → None
