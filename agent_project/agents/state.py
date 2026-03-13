"""
LangGraph 상태 정의
Multi-Agent 플로우에서 공유되는 상태
"""
from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """멀티에이전트 그래프의 공유 상태"""
    # 사용자 원본 질문
    query: str
    # 질문 유형 분류 결과
    query_type: str
    # 대화 히스토리 (멀티턴)
    chat_history: Annotated[list[BaseMessage], add_messages]
    # RAG 검색 결과
    rag_context: str
    # 도구 실행 결과
    tool_results: str
    # 에이전트 메시지 (ReAct 스크래치패드)
    messages: Annotated[list[BaseMessage], add_messages]
    # 수집된 정보 종합
    collected_info: str
    # 최종 응답
    final_response: str
