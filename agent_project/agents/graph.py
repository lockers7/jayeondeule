"""
LangGraph Multi-Agent 플로우 정의
라우터 → (RAG / 도구 에이전트) → 종합 응답
"""
from langgraph.graph import StateGraph, START, END

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.state import AgentState
from agents.nodes import (
    router_node,
    rag_node,
    tool_agent_node,
    synthesizer_node,
)


def route_by_type(state: AgentState) -> str:
    """질문 유형에 따라 다음 노드 결정 (조건부 엣지)"""
    query_type = state.get("query_type", "general")

    if query_type in ("crop_knowledge", "pest_diagnosis"):
        # 작물 지식, 병해충 → RAG 먼저, 그 후 도구
        return "rag"
    elif query_type == "environment":
        # 환경 관리 → RAG + 도구 병행 (RAG 먼저)
        return "rag"
    else:
        # 일반 질문 → 도구 에이전트 (웹검색 등)
        return "tool_agent"


def after_rag(state: AgentState) -> str:
    """RAG 후 도구 에이전트 필요 여부 판단"""
    query_type = state.get("query_type", "")
    query = state.get("query", "").lower()

    # 환경/일반 질문이거나 최신 정보가 필요한 키워드가 있으면 도구도 실행
    needs_tool_keywords = ["가격", "시세", "날씨", "기상", "최근", "올해", "뉴스",
                           "비료", "시비량", "계산", "일정", "재배달력"]
    if query_type == "environment" or any(kw in query for kw in needs_tool_keywords):
        return "tool_agent"
    return "synthesizer"


def build_graph() -> StateGraph:
    """멀티에이전트 그래프 구축

    플로우:
        START → router → (조건) → rag → (조건) → tool_agent → synthesizer → END
                                    ↘                          ↗
                                     → synthesizer → END
                          → tool_agent → synthesizer → END
    """
    graph = StateGraph(AgentState)

    # 노드 추가
    graph.add_node("router", router_node)
    graph.add_node("rag", rag_node)
    graph.add_node("tool_agent", tool_agent_node)
    graph.add_node("synthesizer", synthesizer_node)

    # 엣지 정의
    graph.add_edge(START, "router")

    # 라우터 → 조건부 분기
    graph.add_conditional_edges(
        "router",
        route_by_type,
        {
            "rag": "rag",
            "tool_agent": "tool_agent",
        }
    )

    # RAG 후 → 도구 필요 여부에 따라 분기
    graph.add_conditional_edges(
        "rag",
        after_rag,
        {
            "tool_agent": "tool_agent",
            "synthesizer": "synthesizer",
        }
    )

    # 도구 에이전트 → 종합 응답
    graph.add_edge("tool_agent", "synthesizer")

    # 종합 응답 → 종료
    graph.add_edge("synthesizer", END)

    return graph.compile()


# 컴파일된 그래프 (싱글톤)
_compiled_graph = None

def get_graph():
    """컴파일된 그래프 반환 (싱글톤)"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


if __name__ == "__main__":
    # 그래프 구조 확인
    graph = build_graph()
    print("그래프 빌드 성공!")
    print(f"노드: router, rag, tool_agent, synthesizer")

    # Mermaid 다이어그램 출력
    try:
        print("\n--- Mermaid 다이어그램 ---")
        print(graph.get_graph().draw_mermaid())
    except Exception:
        print("(Mermaid 출력 불가)")
