"""
LangGraph 에이전트 노드 정의
각 노드는 AgentState를 받아 처리 후 상태를 업데이트
"""
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.state import AgentState
from agents.tools import ALL_TOOLS
from rag.chain import retrieve_documents, format_docs
from prompts.templates import (
    ROUTER_PROMPT, RAG_RESPONSE_PROMPT,
    TOOL_AGENT_PROMPT, SYNTHESIZER_PROMPT
)
from config import OLLAMA_BASE_URL, LLM_MODEL, RAG_TOP_K


def get_llm(temperature: float = 0.3) -> ChatOllama:
    """LLM 인스턴스 생성"""
    return ChatOllama(
        model=LLM_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=temperature,
    )


# ============================================================
# 노드 1: 라우터 - 질문 유형 분류
# ============================================================
def router_node(state: AgentState) -> dict:
    """사용자 질문을 분석하여 유형을 분류"""
    llm = get_llm(temperature=0.0)
    chain = ROUTER_PROMPT | llm

    result = chain.invoke({"query": state["query"]})
    query_type = result.content.strip().lower()

    # 유효한 카테고리로 정규화
    valid_types = ["crop_knowledge", "pest_diagnosis", "environment", "general"]
    if query_type not in valid_types:
        # 부분 매칭 시도
        for vt in valid_types:
            if vt in query_type:
                query_type = vt
                break
        else:
            query_type = "general"

    return {"query_type": query_type}


# ============================================================
# 노드 2: RAG 검색 - 벡터스토어에서 관련 문서 검색
# ============================================================
def rag_node(state: AgentState) -> dict:
    """ChromaDB에서 관련 농업 지식 검색"""
    query = state["query"]
    docs = retrieve_documents(query, k=RAG_TOP_K)
    context = format_docs(docs)

    # RAG 기반 응답 생성
    llm = get_llm()
    chain = RAG_RESPONSE_PROMPT | llm

    invoke_params = {"context": context, "query": query}
    if state.get("chat_history"):
        invoke_params["chat_history"] = state["chat_history"]

    result = chain.invoke(invoke_params)

    return {
        "rag_context": context,
        "collected_info": f"[RAG 검색 결과]\n{result.content}",
    }


# ============================================================
# 노드 3: 도구 에이전트 - ReAct 패턴으로 도구 사용
# ============================================================
def tool_agent_node(state: AgentState) -> dict:
    """ReAct 패턴으로 도구를 사용하여 정보 수집"""
    llm = get_llm(temperature=0.1)

    # LangGraph의 create_react_agent 사용
    react_agent = create_react_agent(
        model=llm,
        tools=ALL_TOOLS,
    )

    result = react_agent.invoke({
        "messages": [HumanMessage(content=state["query"])],
    })

    # 마지막 AI 메시지 추출
    last_msg = ""
    for msg in reversed(result.get("messages", [])):
        if isinstance(msg, AIMessage) and msg.content:
            last_msg = msg.content
            break

    tool_info = f"[도구 실행 결과]\n{last_msg}" if last_msg else ""

    # 기존 collected_info에 추가
    prev_info = state.get("collected_info", "")
    combined = f"{prev_info}\n\n{tool_info}" if prev_info else tool_info

    return {
        "tool_results": last_msg,
        "collected_info": combined,
    }


# ============================================================
# 노드 4: 종합 응답 생성 - 모든 정보를 종합하여 최종 답변
# ============================================================
def synthesizer_node(state: AgentState) -> dict:
    """수집된 모든 정보를 종합하여 최종 응답 생성"""
    llm = get_llm()
    chain = SYNTHESIZER_PROMPT | llm

    collected = state.get("collected_info", "수집된 정보가 없습니다.")

    invoke_params = {
        "query": state["query"],
        "query_type": state.get("query_type", "general"),
        "collected_info": collected,
    }
    if state.get("chat_history"):
        invoke_params["chat_history"] = state["chat_history"]

    result = chain.invoke(invoke_params)

    return {
        "final_response": result.content,
        "messages": [AIMessage(content=result.content)],
    }
