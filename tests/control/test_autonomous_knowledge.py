# ══════════════════════════════════════════════════════════════════════════════
# test_autonomous_knowledge — 자율 지식성장 체인 검증
#
# Agent 가 웹에서 찾은 정보를 스스로 저장가치 판단 후 web_knowledge 에 저장(자율성장).
# ⛔ 저장은 web_knowledge(채팅 회수·제어 미읽음)에만 → 제어 오염 없음(안전).
# 안전장치: 일일한도·중복 dedup·출처메타·농장주 삭제 가능.
#
# 파일 시작 함수 목록:
#   test_save_validates_content     : 짧은 content 거부
#   test_save_dedup_skips           : 임베딩 근접 중복이면 저장 생략
#   test_save_daily_limit           : 일일 한도 도달 시 저장 생략
#   test_save_success_metadata      : 저장 성공 + web_knowledge·file_name·출처 메타
#   test_save_registered_in_agent   : Agent TOOL_REGISTRY 에 save_knowledge 결합
#   test_webscan_task_routes_external : web_scan task 가 외부라우팅에 매칭
#   test_prompt_has_save_step        : CTRL_AGENT_EXTERNAL 에 save_knowledge 저장단계
#   test_delete_covers_web_knowledge : delete_farm_knowledge 가 web_knowledge 커버
# ══════════════════════════════════════════════════════════════════════════════
import inspect

from agri_ai_core.src.ai import tools_agent_knowledge as ak


def test_save_validates_content():
    assert not ak.agent_save_knowledge(title="t", content="짧음")["success"]     # _MIN_LEN 미만


def test_save_dedup_skips(monkeypatch):
    monkeypatch.setattr(ak, "_saved_today_count", lambda: 0)
    monkeypatch.setattr("agri_ai_core.src.ai.embedder.embed_text", lambda t: [0.1] * 1024)
    monkeypatch.setattr(ak, "_is_duplicate", lambda emb: True)
    r = ak.agent_save_knowledge(title="상황버섯 고온관리",
                                content="여름 고온기 32도 넘으면 생육 둔화, 차광·환기 강화 필요.")
    assert r.get("skipped") and not r["success"]              # 중복 → 생략


def test_save_daily_limit(monkeypatch):
    monkeypatch.setattr(ak, "_saved_today_count", lambda: ak._DAILY_LIMIT)
    r = ak.agent_save_knowledge(title="t", content="충분히 긴 실질 내용입니다 " * 2)
    assert r.get("skipped") and "한도" in r.get("message", "")   # 일일한도 → 생략


def test_save_success_metadata(monkeypatch):
    saved = {}
    monkeypatch.setattr(ak, "_saved_today_count", lambda: 0)
    monkeypatch.setattr(ak, "_is_duplicate", lambda emb: False)
    monkeypatch.setattr("agri_ai_core.src.ai.embedder.embed_text", lambda t: [0.2] * 1024)

    def fake_add(collection_name, doc_id, text, metadata, embedding=None):
        saved.update(coll=collection_name, id=doc_id, text=text, meta=metadata, emb=embedding)
        return {"success": True}

    monkeypatch.setattr("agri_ai_core.src.chroma.operations.add_document", fake_add)
    wk = {"v": 0}
    monkeypatch.setattr("agri_ai_core.src.chroma.collections.web_knowledge_collection",
                        lambda: "web_knowledge")

    r = ak.agent_save_knowledge(title="상황버섯 습도관리",
                                content="자실체 형성기 습도 90% 유지, 과습 시 배기순환.",
                                category="재배정보", source_url="https://rda.go.kr/x", farm=1)
    assert r["success"] and r["knowledge_id"].startswith("webk_")
    m = saved["meta"]
    assert m["data_type"] == "web_knowledge_auto" and m["source"] == "agent_web_scan"
    assert m["file_name"] == "자율웹지식"          # 농장주 일괄삭제 그룹키
    assert m["source_url"] == "https://rda.go.kr/x" and m["farm_id"] == "1"
    assert saved["emb"] is not None               # 0벡터 방지
    assert "출처:" in saved["text"]


def test_save_registered_in_agent():
    from agri_ai_core.src.control import ai_monitor_agent as ama
    assert "save_knowledge" in ama.TOOL_REGISTRY
    assert "save_knowledge" not in ama._WRITE_TOOL_NAMES   # 제어-write 큐 대상 아님
    assert "지식저장 도구" in ama.tool_specs_text()


def test_webscan_task_routes_external():
    from agri_ai_core.src.control import agent_scheduler as sch
    from agri_ai_core.src.control.ai_monitor_agent import _is_external_info_task
    task = sch._build_web_scan_task(1)
    assert _is_external_info_task(task)                     # 외부 프롬프트로 라우팅됨
    assert "save_knowledge" in task                        # 저장 지시 포함


def test_prompt_has_save_step():
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        r = d.fetch_one("SELECT body_text FROM control_prompt_m WHERE block_id='CTRL_AGENT_EXTERNAL'", ())
    body = dict(r)["body_text"] if r else ""
    assert "save_knowledge" in body and "저장가치 3조건" in body


def test_delete_covers_web_knowledge():
    from agri_ai_core.src.ai import tools_data
    src = inspect.getsource(tools_data.delete_farm_knowledge)
    assert "web_knowledge_collection" in src               # 농장주 검토·삭제 커버


# ── 지역 정보 자율수집 (주 2회·off-peak) ──
def test_region_task_routes_external(monkeypatch):
    from agri_ai_core.src.control import agent_scheduler as sch
    from agri_ai_core.src.control.ai_monitor_agent import _is_external_info_task
    monkeypatch.setattr(sch, "_region_addr", lambda fid: "전북특별자치도 정읍시 영원면")
    task = sch._build_region_scan_task(1)
    assert "정읍시" in task and "영원면" in task              # 실제 주소 반영
    assert _is_external_info_task(task)                       # 외부 프롬프트 라우팅
    assert "save_knowledge" in task and "특산물" in task and "뉴스" in task


def test_next_region_window(monkeypatch):
    from agri_ai_core.src.control import agent_scheduler as sch
    monkeypatch.setattr(sch, "AGENT_OFFPEAK_HOURS", {2, 3, 4})
    monkeypatch.setattr(sch, "AGENT_REGION_SCAN_DAYS", {0, 3})   # 월,목
    dt = sch._next_region_window()
    assert dt.hour == 2 and dt.weekday() in {0, 3}              # off-peak 시작 + 지정 요일


def test_scan_window_gate(monkeypatch):
    from datetime import datetime
    from agri_ai_core.src.control import agent_scheduler as sch
    now = datetime.now()
    # 비-지역 intent → 게이트 무관(연기 안 함)
    assert sch._defer_if_not_scan_window({"id": 0, "intent": "__default_cron__"}) is False
    # 지역 intent + 지금이 실행창(현재 요일·시각 허용) → 실행(연기 안 함)
    monkeypatch.setattr(sch, "AGENT_REGION_SCAN_DAYS", {now.weekday()})
    monkeypatch.setattr(sch, "AGENT_OFFPEAK_HOURS", {now.hour})
    assert sch._defer_if_not_scan_window({"id": 0, "intent": "__default_region_scan__"}) is False
    # 지역 intent + 창 밖(요일 불일치) → 연기(실행 skip). id=0 은 실 UPDATE 0행(무해)
    monkeypatch.setattr(sch, "AGENT_REGION_SCAN_DAYS", {(now.weekday() + 2) % 7})
    assert sch._defer_if_not_scan_window({"id": 0, "intent": "__default_region_scan__"}) is True


def test_save_region_category(monkeypatch):
    monkeypatch.setattr(ak, "_saved_today_count", lambda: 0)
    monkeypatch.setattr(ak, "_is_duplicate", lambda emb: False)
    monkeypatch.setattr("agri_ai_core.src.ai.embedder.embed_text", lambda t: [0.2] * 1024)
    saved = {}
    monkeypatch.setattr("agri_ai_core.src.chroma.operations.add_document",
                        lambda c, i, t, m, embedding=None: saved.update(meta=m))
    monkeypatch.setattr("agri_ai_core.src.chroma.collections.web_knowledge_collection", lambda: "wk")
    r = ak.agent_save_knowledge(title="정읍 특산물", content="정읍은 단풍미인쌀과 유황오리로 유명하다.",
                                category="특산물", source_url="https://x")
    assert r["success"] and saved["meta"]["category"] == "특산물"   # 지역 카테고리 저장
