from pydantic import BaseModel, Field
from typing import Optional


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
