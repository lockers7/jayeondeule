# ══════════════════════════════════════════════════════════════════════════════
# test_routing_matrix_llm — ANALYZER 질문→도구 라우팅 매트릭스(실 LLM, opt-in)
#
# 실제 gemma3:27b ANALYZER 로 15개 대표 질의를 라우팅해 기대 도구가 계획에
# 포함되는지 검증한다. GPU 직렬 추론이라 쿼리당 ~2분(총 ~30분) 소요 → 기본 SKIP.
# 실행: RUN_LLM_ROUTING=1 pytest tests/ai/test_routing_matrix_llm.py
#
# 종합 역량감사(2026-07-25)에서 15/15 PASS 실측한 라우팅 기대치를 영구 보존한다.
# 하나라도 기대 도구가 빠지면 회귀 — 교훈(manage_analysis_lesson) 또는 시스템지식
# (manage_system_knowledge) 시드로 교정(코드 수정 아님이 1순위).
#
# 파일 시작 함수 목록:
#   test_routing_matrix : (질의, 기대도구 후보) 15쌍 — 하나라도 포함이면 PASS
# ══════════════════════════════════════════════════════════════════════════════
import os
import pytest

# 기대 도구 후보 — 하나라도 계획에 포함되면 PASS(라우팅 다양성 허용)
MATRIX = [
    ("1호 재배사 라즈베리파이 서버정보 알려줘", ["remote_status"]),
    ("1호와 2호 재배사 소스 비교해서 다른 파일 알려줘", ["compare_remote_sources"]),
    ("각 재배사 라즈베리파이 하드웨어 스펙을 재배사별로 알려줘",
     ["remote_status", "compare_remote_sources"]),
    ("1호 라즈베리파이에서 디스크 사용량 명령 실행해줘", ["remote_run", "remote_status"]),
    ("자율 성장 기능 스케줄과 학습 유형을 분석해줘",
     ["db_read_query", "search_farm_knowledge"]),
    ("상황버섯 재배할 때 습도 얼마로 관리해야 해", ["search_farm_knowledge"]),
    ("오늘 에러 로그 있었나", ["search_logs"]),
    ("1호 재배사 지금 온도랑 습도 상태 알려줘",
     ["get_all_house_status", "get_farm_realtime_data", "db_read_query"]),
    ("sensor_l_recording 테이블 최근 데이터 조회해줘", ["db_read_query"]),
    ("상황버섯 최신 연구논문 찾아줘", ["mcp_call", "search_web"]),
    ("오늘 정읍 날씨 알려줘", ["get_weather_forecast", "mcp_call"]),
    ("위키백과에서 상황버섯 정보 찾아줘", ["mcp_call", "search_web"]),
    ("앞으로 자사주 매입 종목 위주로 매매해줘", ["set_trading_strategy"]),
    ("파이썬으로 30 이하 소수 구하는 코드 작성해서 실행해줘",
     ["write_script", "run_script"]),
    ("1호 카메라로 지금 재배사 상태 봐줘", ["get_camera_view"]),
    # ── 전 역량군 커버 확장(2026-07-25) ──
    ("1호 재배사 배기팬 꺼줘", ["control_relay", "set_house_control_mode"]),
    ("앞으로 수온이 20도 넘으면 히터 꺼라, 이 규칙 저장해줘", ["save_domain_knowledge"]),
    ("앞으로 이유를 물으면 AI 결정기록을 근거로 답해줘", ["manage_analysis_lesson"]),
    ("카카오 발송은 kakao_notify가 담당한다는 걸 시스템 지식으로 기억해줘",
     ["manage_system_knowledge"]),
    ("서버 CPU랑 메모리 사용량 알려줘", ["get_server_resources"]),
    ("지금 실행 중인 서비스 목록 보여줘", ["list_services"]),
    ("compare_remote_sources 함수가 어느 파일에 있어?",
     ["source_search", "source_read"]),
    ("10분마다 1호 재배사 상태를 감시해줘", ["schedule_monitor", "agent_subscribe"]),
    ("대기 중인 경고 알림 있어?", ["get_pending_alerts"]),
    ("등록된 MCP 서버 목록 보여줘", ["manage_mcp_server", "mcp_list_tools"]),
]

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LLM_ROUTING") != "1",
    reason="실 LLM 라우팅(직렬 GPU ~30분) — RUN_LLM_ROUTING=1 로만 실행")


@pytest.mark.parametrize("query,expected", MATRIX)
def test_routing_matrix(query, expected):
    from agri_ai_core.src.ai.pipeline.question_analyzer import analyze_question
    r = analyze_question(query, farm_id=1, house_id=1)
    tools = [d.get("tool") for d in (r.get("required_data") or [])]
    assert any(e in tools for e in expected), (
        f"라우팅 회귀: '{query}' 기대 {expected} 중 하나도 없음 → {tools}")
