# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# API 요청/응답 Pydantic 모델 정의
# LLM 질의, RAG 검색/저장 등 REST API 엔드포인트의 입출력 데이터 모델을 정의합니다.
# --->
# QueryRequest: LLM 질의 요청 모델
# SourceItem: 출처 정보 모델
# QueryResponse: LLM 질의 응답 모델
# MessageItem: 대화 메시지 모델
# RagSaveRequest: RAG 저장 요청 모델
# RagResponse: RAG 응답 모델
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
from pydantic import BaseModel, Field
from typing import Optional, List


class QueryRequest(BaseModel):
    query: str = Field(..., description="사용자 질문")
    session_id: Optional[str] = Field(default=None, description="대화 세션 ID (멀티턴 대화용)")
    farm_id: Optional[str] = Field(default=None, description="농장 ID")
    house_id: Optional[str] = Field(default=None, description="재배사 ID")
    farm_name: Optional[str] = Field(default=None, description="농장명")
    house_name: Optional[str] = Field(default=None, description="재배사명")
    speech_style: Optional[str] = Field(default=None, description="대화체 (male: 사무적, female: 부드러운)")


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
