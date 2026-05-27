# ══════════════════════════════════════════════════════════════════════════════
# Agent 전용 외부접속 read-only 도구 모음
#
# 주기 Agent(ai_monitor_agent.run_agent)가 MCP·웹·기상 등 외부 정보를 주기적으로
# 확인해 농장관리에 도움되는 정보를 수집·판단하고 send_user_alert 로 통지하도록 한다.
# 농장주 요청 예: "매일 상황버섯 재배 논문/농자재 시세/병해충 정보를 외부에서 확인해 알려줘".
#
# 설계 원칙 (tools_agent_read 와 동형):
#   · 전부 read-only — 외부 조회만, 제어·쓰기 없음(농장 위험 0).
#   · 채팅 파이프라인의 검증된 구현(search_web·mcp_call·…)을 얇게 래핑 — 중복 구현 금지.
#   · 항상 dict 반환(성공·실패 모두) — agent ReAct loop 가 동일 형식으로 파싱.
#   · 예외는 잡아 {"error": "..."} — loop 가 다음 step 결정.
#
# 파일 시작 함수 목록:
#   agent_search_web        : 웹 검색(제목·요약·URL)
#   agent_fetch_url         : URL 본문 가져오기
#   agent_mcp_list_tools    : MCP 서버·도구 목록/스키마 조회
#   agent_mcp_call          : MCP 서버 도구 호출(논문/지역/쇼핑/지식 검색 등)
#   agent_get_weather       : 농장 위치 기상예보
#   TOOL_REGISTRY           : 도구명 → 함수 (agent loop 사용)
#   TOOL_SPECS / tool_specs_text : LLM 프롬프트 주입용 스펙
# ══════════════════════════════════════════════════════════════════════════════
from typing import Any, Dict

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)


def agent_search_web(query: str = None, max_results: int = 5) -> Dict[str, Any]:
    if not query or not str(query).strip():
        return {"error": "query(검색어)는 필수입니다."}
    try:
        from agri_ai_core.src.ai.tools_search import search_web
        n = max_results if isinstance(max_results, int) and 1 <= max_results <= 10 else 5
        return search_web(query=str(query).strip(), n_results=n)
    except Exception as e:
        logger.warning(f"[Agent외부] search_web 실패: {e}")
        return {"error": f"웹검색 실패: {e}"}


def agent_fetch_url(url: str = None) -> Dict[str, Any]:
    if not url or not str(url).strip():
        return {"error": "url 은 필수입니다."}
    try:
        from agri_ai_core.src.ai.tools_search import fetch_url_content
        return fetch_url_content(str(url).strip())
    except Exception as e:
        logger.warning(f"[Agent외부] fetch_url 실패: {e}")
        return {"error": f"URL 조회 실패: {e}"}


def agent_mcp_list_tools(server: str = None) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.ai.tools_mcp_gateway import mcp_list_tools
        return mcp_list_tools(server=server)
    except Exception as e:
        logger.warning(f"[Agent외부] mcp_list_tools 실패: {e}")
        return {"error": f"MCP 목록 조회 실패: {e}"}


def agent_mcp_call(server: str = None, tool: str = None,
                   args: Any = None, timeout: int = 45, **kwargs) -> Dict[str, Any]:
    if not server or not tool:
        return {"error": "server 와 tool 은 필수입니다. mcp_list_tools 로 확인하세요."}
    try:
        from agri_ai_core.src.ai.tools_mcp_gateway import mcp_call
        to = timeout if isinstance(timeout, int) and 1 <= timeout <= 120 else 45
        # LLM 이 MCP 도구 인자(query·max_results 등)를 args 로 감싸지 않고 최상위로
        # 평탄하게 넘기는 자연스러운 호출을 관용 — 잉여 kwargs 를 args 에 자동 병합
        # (2026-07-25 자율 web_scan 에서 paper-search 3회 실패 실측). 제약 대신 적응.
        merged = dict(args) if isinstance(args, dict) else {}
        for k, v in kwargs.items():
            merged.setdefault(k, v)
        return mcp_call(server=str(server), tool=str(tool), args=merged, timeout=to)
    except Exception as e:
        logger.warning(f"[Agent외부] mcp_call 실패: {e}")
        return {"error": f"MCP 호출 실패: {e}"}


def agent_get_weather(farm: Any = None, house: Any = None) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.ai.tools_data import get_weather_forecast
        return get_weather_forecast(
            farm_id=str(farm) if farm is not None else None,
            house_id=str(house) if house is not None else None)
    except Exception as e:
        logger.warning(f"[Agent외부] get_weather 실패: {e}")
        return {"error": f"기상예보 조회 실패: {e}"}


# ── Agent 확장 read (카메라·서버리소스) — GAP3/4 보완, read-only ──
def agent_get_camera(house: Any = None, farm: Any = None) -> Dict[str, Any]:
    if house is None:
        return {"error": "house(재배사 번호)는 필수입니다. 카메라는 특정 재배사만 판독."}
    try:
        from agri_ai_core.src.ai.tools_data import get_camera_view
        return get_camera_view(farm_id=str(farm) if farm is not None else None,
                               house_id=str(house))
    except Exception as e:
        logger.warning(f"[Agent외부] get_camera 실패: {e}")
        return {"error": f"카메라 판독 실패: {e}"}


def agent_get_resources() -> Dict[str, Any]:
    try:
        from agri_ai_core.src.ai.tools_resources import get_server_resources
        return get_server_resources()
    except Exception as e:
        logger.warning(f"[Agent외부] get_resources 실패: {e}")
        return {"error": f"서버 리소스 조회 실패: {e}"}


# ────────────────────────────────────────────────────────────────────
# 레지스트리 — 채팅과 동일한 도구명(search_web/mcp_call/…)으로 노출.
# 전부 read-only 이므로 ai_monitor_agent 의 _WRITE_TOOL_NAMES 에 포함되지 않는다.
# ────────────────────────────────────────────────────────────────────
TOOL_REGISTRY = {
    "search_web":          agent_search_web,
    "fetch_url_content":   agent_fetch_url,
    "mcp_list_tools":      agent_mcp_list_tools,
    "mcp_call":            agent_mcp_call,
    "get_weather_forecast": agent_get_weather,
    "get_camera_view":      agent_get_camera,
    "get_server_resources": agent_get_resources,
}

TOOL_SPECS = [
    {
        "name": "search_web",
        "description": "웹 검색 — 농장관리에 도움되는 외부 정보(재배기술·병해충·농자재 시세·기상 이슈 등) 조회. 제목·요약·URL 반환.",
        "args": {
            "query": {"type": "str", "desc": "검색어 (예: '상황버섯 자실체 고온 관리')"},
            "max_results": {"type": "int", "desc": "결과 수 1~10, 기본 5"},
        },
    },
    {
        "name": "fetch_url_content",
        "description": "특정 URL 본문을 가져와 읽는다. search_web 결과 중 유용한 링크를 자세히 볼 때 사용.",
        "args": {"url": {"type": "str", "desc": "http(s) URL"}},
    },
    {
        "name": "mcp_list_tools",
        "description": "등록된 MCP 서버·도구 목록/스키마 조회. mcp_call 전 서버명·도구명·인자를 확인. server 생략 시 서버 목록.",
        "args": {"server": {"type": "str", "desc": "서버명(선택). 예: paper-search, naver-search, korea-weather"}},
    },
    {
        "name": "mcp_call",
        "description": "MCP 서버 도구 호출 — 학술논문(paper-search: arxiv/pubmed), 지역/쇼핑/지식iN(naver-search), 기상(korea-weather) 등 전문 외부검색. 인자를 모르면 mcp_list_tools 로 먼저 확인.",
        "args": {
            "server": {"type": "str", "desc": "MCP 서버명"},
            "tool":   {"type": "str", "desc": "그 서버의 도구명"},
            "args":   {"type": "dict", "desc": "도구 인자 (예: {'query':'Phellinus linteus cultivation'})"},
        },
    },
    {
        "name": "get_weather_forecast",
        "description": "농장 위치 기반 기상예보(기온·강수·특보). 저온·폭염·강우 대비 판단에 활용.",
        "args": {"farm": {"type": "int", "desc": "농장 ID(선택, 기본 세션 농장)"}},
    },
    {
        "name": "get_camera_view",
        "description": "지정 재배사 카메라 현재 프레임을 gemma3 비전으로 판독(곰팡이·오염·균상 상태). '균상/영상 상태 감시' 임무에 사용.",
        "args": {"house": {"type": "int", "desc": "재배사 번호(필수)"}},
    },
    {
        "name": "get_server_resources",
        "description": "서버 실측 리소스(CPU·메모리·디스크·GPU·서비스 가동). GPU OOM·서비스 다운 등 인프라 이상 감시에 사용.",
        "args": {},
    },
]


def tool_specs_text() -> str:
    lines = ["\n[외부 정보 조회 도구 — read-only, 농장관리 도움정보 수집용]"]
    for spec in TOOL_SPECS:
        arg_desc = ", ".join(f"{k}({v.get('type','')})" for k, v in spec["args"].items())
        lines.append(f"- {spec['name']}({arg_desc}): {spec['description']}")
    return "\n".join(lines) + "\n"
