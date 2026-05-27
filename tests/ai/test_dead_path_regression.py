# ══════════════════════════════════════════════════════════════════════════════
# test_dead_path_regression — 조용히 죽어있던 경로 4건의 재발 방지
#
# 배경(2026-07-17 전수조사): 관리자지시 NameError(12일 은폐)와 동일한 패턴이
#   더 있었다. 공통 구조는 "미import/인자불일치 → 예외 → except 가 삼킴 → 무증상".
#
#   S1 llm_response_processing:33  os/is_true 미import → _emit_question_log_once
#      즉사 → llm_client:669 가 삼킴 → 3단계 파이프라인 폴백 전체가 3개월 사망.
#      폴백이 필요한 바로 그 순간 폴백이 죽어 사용자는 항상 사과문만 받았다.
#   S6 llm_response_processing:288 json 미import → JSON 재시도 분기 사망(S1 내부).
#   S2 conversation_store:325      인자 불일치 → 대화 요약 저장 4.5개월 100% 실패.
#      logger.debug 가 은폐. 임베딩만 계산하고 매번 버렸다.
#   S3 api/app.py:453              datetime 미import → alerts SSE 첫 yield 즉사.
#
# 이 파일은 "함수가 예외 없이 실제로 실행되는가" 를 본다 — 단위 로직이 아니라
#   배선(wiring)을 검증한다. 그것이 위 4건이 숨은 이유다.
#
# 파일 시작 함수 목록:
#   test_emit_question_log_runs        : S1 — NameError 없이 실행
#   test_check_answer_retry_json_branch: S6 — json 분기 도달
#   test_no_undefined_names            : ⛔ pyflakes 로 미정의 이름 0 (S1·S3·S6 검출법)
#   test_conversation_upsert_signature : S2 — 호출 인자가 정의와 일치
#   test_app_datetime_importable       : S3 — 모듈 스코프에 datetime 존재
# ══════════════════════════════════════════════════════════════════════════════
import ast
import inspect
import os
import subprocess
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ⛔ 이 경로들은 "미정의 이름" 사고가 실제로 난 파일이다. 새 파일 추가는 환영.
_PYFLAKES_TARGETS = [
    "agri_ai_core/src/ai/llm_response_processing.py",
    "agri_ai_core/src/ai/llm_client.py",
    "agri_ai_core/src/ai/conversation_store.py",
    "agri_ai_core/api/app.py",
    "agri_ai_core/src/control/ai_control.py",
    "agri_ai_core/src/control/admin_directive.py",
    "agri_ai_core/src/ai/mcp_client.py",
]


# ⛔ S1: 3개월간 이 함수가 NameError 로 즉사해 파이프라인 폴백 전체가 죽어있었다.
def test_emit_question_log_runs():
    from agri_ai_core.src.ai import llm_response_processing as lrp

    # 예외 없이 끝나야 한다. NameError 가 나면 폴백 경로가 다시 죽는다.
    lrp._emit_question_log_once("테스트 질문", "자연들에", 5, 52)


# ⛔ S6: json 미import 로 JSON 재시도 분기가 죽어있었다 (S1 안의 dead).
def test_check_answer_retry_json_branch():
    from agri_ai_core.src.ai import llm_response_processing as lrp

    # LLM 이 JSON 원문을 뱉은 상황 → 자연어 재생성 지시가 나와야 한다
    out = lrp._check_answer_retry(
        '{"answer": "raw json 그대로"}', "질문", [], 1, 5, "stop", False, {})
    assert out, "JSON 원문 응답인데 재시도 지시가 없음 — json 분기가 죽었다"


# ⛔ 재발 방지의 핵심: 위 3건은 전부 pyflakes 한 줄로 잡힌다.
def test_no_undefined_names():
    paths = [os.path.join(_ROOT, p) for p in _PYFLAKES_TARGETS]
    r = subprocess.run([sys.executable, "-m", "pyflakes", *paths],
                       capture_output=True, text=True, cwd=_ROOT)
    undefined = [ln for ln in (r.stdout or "").splitlines() if "undefined name" in ln]
    assert not undefined, (
        "미정의 이름 발견 — 호출 즉시 NameError 로 경로가 죽는다:\n" + "\n".join(undefined))


# ⛔ S2: 인자 불일치는 pyflakes 가 못 잡는다. 호출부 인자를 정의와 직접 대조한다.
def test_conversation_upsert_signature():
    from agri_ai_core.src.ai import conversation_store
    from agri_ai_core.src.chroma.operations import upsert_documents_with_embedding

    params = list(inspect.signature(upsert_documents_with_embedding).parameters)
    assert params == ["collection_name", "docs"], f"정의가 바뀜: {params}"

    # 호출부가 ChromaDB 원시 API 형태(ids=/documents=/embeddings=/metadatas=)면 TypeError
    src = inspect.getsource(conversation_store)
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "upsert_documents_with_embedding"]
    assert calls, "호출부를 찾지 못함 — 테스트 갱신 필요"
    for c in calls:
        kw = {k.arg for k in c.keywords}
        bad = kw & {"ids", "documents", "embeddings", "metadatas"}
        assert not bad, (
            f"ChromaDB 원시 API 인자 {bad} 사용 — 정의는 (collection_name, docs) 라 TypeError")
        assert len(c.args) == 2, f"위치인자 2개(collection_name, docs)여야 함 (현재 {len(c.args)})"


# ⛔ S3: alerts SSE 는 첫 yield 에서 datetime 을 쓴다. 모듈 스코프에 없으면 즉사.
def test_app_datetime_importable():
    src_path = os.path.join(_ROOT, "agri_ai_core", "api", "app.py")
    with open(src_path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    names = set()
    for node in tree.body:            # 모듈 스코프만 — 함수 안 로컬 import 는 SSE 에서 못 쓴다
        if isinstance(node, ast.Import):
            names.update(a.asname or a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names)
    assert "datetime" in names, (
        "app.py 모듈 스코프에 datetime 없음 — /api/v1/alerts/stream 이 첫 yield 에서 NameError")
