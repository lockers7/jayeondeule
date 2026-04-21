# ════════════════════════════════════════════════════════════════════
# API 요청/응답 Pydantic 모델 정의 — REST 레이어와 도메인 레이어의 경계.
# --->
# QueryRequest    : /query · /query/stream 요청 body
# SourceItem      : 웹 검색 결과 출처 한 건 (title + url)
# QueryResponse   : LLM 질의 응답 (response/sources/tools_used/...)
# MessageItem     : 대화 한 턴 (role + content)
# RagSaveRequest  : /rag/save 요청 body — 대화 메시지 묶음 + 메타
# RagResponse     : /rag/perform · /rag/save 공통 응답 (success/message/time)
# ════════════════════════════════════════════════════════════════════
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class QueryRequest(BaseModel):
    query: str = Field(..., description="사용자 질문")
    session_id: Optional[str] = Field(default=None, description="대화 세션 ID (멀티턴 대화용)")
    farm_id: Optional[str] = Field(default=None, description="농장 ID (사이드바 선택, 실시간 데이터 조회용)")
    house_id: Optional[str] = Field(default=None, description="재배사 ID")
    farm_name: Optional[str] = Field(default=None, description="농장명")
    house_name: Optional[str] = Field(default=None, description="재배사명")
    speech_style: Optional[str] = Field(default=None, description="대화체 (male: 사무적, female: 부드러운)")
    auth_farm_id: Optional[str] = Field(default=None, description="인증 농장 ID (RAG 권한 결정용, 시스템관리자=None, 농장사용자=자기농장ID)")


class SourceItem(BaseModel):
    title: str = Field(..., description="출처 제목")
    url: str = Field(..., description="출처 URL")


class QueryResponse(BaseModel):
    success: bool
    response: str
    processing_time: float
    session_id: Optional[str] = Field(default=None, description="대화 세션 ID")
    sources: Optional[List[SourceItem]] = Field(default=None, description="웹 검색 출처 목록")
    tools_used: Optional[List[str]] = Field(default=None, description="사용된 도구 목록")
    response_type: Optional[str] = Field(default=None, description="응답 유형 (web_search|farm_data|knowledge|general)")
    # [E1] 도구 호출 추적성 — 각 도구가 어떤 args 로 호출되었고 결과 success/에러가 무엇인지 기록
    tool_calls_detail: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="각 도구 호출의 세부 정보 (tool, args, success, error, elapsed_ms). 디버깅/감사 로그용.",
    )


class MessageItem(BaseModel):
    role: str = Field(..., description="메시지 역할 (user/assistant)")
    content: str = Field(..., description="메시지 내용")


class RagSaveRequest(BaseModel):
    messages: List[MessageItem] = Field(..., description="대화 메시지 목록")
    farm_id: Optional[str] = Field(default=None, description="농장 ID")
    farm_name: Optional[str] = Field(default=None, description="농장명")
    house_name: Optional[str] = Field(default=None, description="재배사명")


class RagResponse(BaseModel):
    success: bool
    message: str
    processing_time: float
