# ══════════════════════════════════════════════════════════════════════════════
# test_tools_resources — 서버 리소스 조회 도구 (2026-07-17)
#
# 배경: 농장주가 "서버 리소스 상태 분석해줘" 라고 묻자 LLM 이 search_web 으로
#   리눅스 모니터링 일반론 기사를 233초 걸려 가져왔다. 원인은 LLM 이 아니라
#   **도구 부재** — CPU/메모리/디스크/GPU 를 물어볼 곳이 없었다.
#   ⛔ 절대 룰 "시스템 내부 질문에 search_web 금지" 는 물어볼 도구가 있어야 성립한다.
#
# 파일 시작 함수 목록:
#   test_returns_all_sections   : CPU·메모리·디스크·GPU·서비스 전 항목 반환
#   test_cpu_shape              : CPU 필드 (코어·사용률·부하평균)
#   test_memory_shape           : 메모리 필드 (GB 단위)
#   test_disk_shape             : 디스크 경로별 사용량
#   test_gpu_optional           : GPU 없는 환경에서도 실패하지 않음
#   test_services_reuses_whitelist : 서비스는 tools_service 화이트리스트 재사용(중복구현 금지)
#   test_registered_in_5_places : 5중 등록
# ══════════════════════════════════════════════════════════════════════════════
from unittest.mock import patch

from agri_ai_core.src.ai import tools_resources as tr


def test_returns_all_sections():
    r = tr.get_server_resources()
    assert r["success"] is True
    for k in ("cpu", "memory", "disk", "gpu", "services", "services_down", "collected_at"):
        assert k in r, f"{k} 누락 — 농장주가 요청한 항목"


def test_cpu_shape():
    c = tr._cpu()
    assert c.get("cores", 0) > 0
    assert 0 <= c.get("usage_pct", -1) <= 100
    assert len(c.get("load_avg", [])) == 3
    assert c.get("load_per_core") is not None    # 코어 대비 부하 — 판단 근거


def test_memory_shape():
    m = tr._memory()
    assert m.get("total_gb", 0) > 0
    assert m.get("used_gb", -1) >= 0
    assert 0 <= m.get("usage_pct", -1) <= 100


def test_disk_shape():
    d = tr._disk()
    assert len(d) >= 1
    for x in d:
        if "error" in x:
            continue
        assert x["total_gb"] > 0 and 0 <= x["usage_pct"] <= 100
        assert "free_gb" in x


def test_gpu_optional():
    # nvidia-smi 없는 환경에서도 예외 없이 빈 list
    with patch.object(tr.subprocess, "run", side_effect=FileNotFoundError()):
        assert tr._gpu() == []


def test_services_reuses_whitelist():
    # 서비스 목록을 중복 구현하지 않고 tools_service 를 재사용해야 한다
    from agri_ai_core.src.ai.tools_service import _ALLOWED
    with patch("agri_ai_core.src.ai.tools_service._health", lambda spec: True):
        s = tr._services()
    assert len(s) == len(_ALLOWED)
    assert all(x["healthy"] for x in s)


def test_registered_in_5_places():
    from agri_ai_core.src.ai.tools_definition import get_available_tools
    from agri_ai_core.src.ai.pipeline.question_analyzer import _VALID_TOOLS
    names = [t["function"]["name"] for t in get_available_tools()]
    assert "get_server_resources" in names, "LLM 미노출 — search_web 오라우팅 재발"
    assert "get_server_resources" in _VALID_TOOLS, "ANALYZER 누락"


# ⛔ 회귀 방지 (2026-07-17 실측 사고): ANALYZER 시스템 프롬프트가 도구 증가로
#   8,401 토큰이 됐는데 num_ctx 가 8,192 라 앞부분이 잘렸다. LLM 이 JSON 형식
#   지시를 못 봐서 빈 코드블록(```)만 반환 → 유효성 실패 → 키워드 fallback
#   (web_search) 으로 강등 → "서버 리소스" 질문에 웹 기사를 답했다.
#   도구를 더 추가할 때 이 테스트가 깨지면 num_ctx 를 올려야 한다.
def test_analyzer_ctx_exceeds_prompt():
    from agri_ai_core.src.ai.pipeline.question_analyzer import _ANALYZER_NUM_CTX
    from agri_ai_core.src.ai.pipeline.prompts import get_analyzer_system_prompt

    prompt = get_analyzer_system_prompt()
    # 한글 ~2.1자/토큰 (2026-07-17 Ollama tokenize 실측: 17,860자 → 8,401토큰).
    # 보수적으로 2자/토큰으로 추정하고, 질문+교훈(~500자)+대화맥락을 위해
    # 프롬프트의 1.5배 이상을 요구한다. 사고 당시는 8,192 < 8,401 로 프롬프트조차
    # 못 담았다.
    est_tokens = len(prompt) / 2
    assert _ANALYZER_NUM_CTX > est_tokens, (
        f"num_ctx({_ANALYZER_NUM_CTX}) 가 시스템 프롬프트(~{est_tokens:.0f}토큰)보다 작다 — "
        f"앞부분이 잘려 LLM 이 JSON 지시를 잃고 키워드 fallback 으로 강등된다")
    assert _ANALYZER_NUM_CTX >= est_tokens * 1.5, (
        f"num_ctx({_ANALYZER_NUM_CTX}) 여유 부족 — 프롬프트 ~{est_tokens:.0f}토큰에 "
        f"질문·교훈·대화맥락이 더해진다. 도구를 늘렸다면 num_ctx 를 올려라")
