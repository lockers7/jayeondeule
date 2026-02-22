from pydantic import BaseModel, Field
from typing import Optional, List


class QueryRequest(BaseModel):
    query: str = Field(..., description="사용자 질문")
    farm_id: Optional[str] = Field(default=None, description="농장 ID")
    house_id: Optional[str] = Field(default=None, description="재배사 ID")
    farm_name: Optional[str] = Field(default=None, description="농장명")
    house_name: Optional[str] = Field(default=None, description="재배사명")


class QueryResponse(BaseModel):
    success: bool
    response: str
    processing_time: float


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
