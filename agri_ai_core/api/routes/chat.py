# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# FastAPI 채팅 엔드포인트를 제공하는 라우터 모듈
# 일반 채팅, 스트리밍 채팅, 파일 첨부 채팅 기능을 처리하며,
# LLM 쿼리 처리를 통해 사용자와의 대화 인터페이스를 제공합니다.
# --->
# [클래스] ChatRequest: 채팅 요청 모델
# [클래스] ChatResponse: 채팅 응답 모델
# chat: 채팅 엔드포인트 (비스트리밍)
# chat_stream: 스트리밍 채팅 엔드포인트
# chat_with_files: 파일 첨부 채팅 엔드포인트
# generate: 기능 설명 필요
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agri_ai_core.log_utils.log_handlers import setup_logger
from agri_ai_core.llm.qa.query_handler import (
    query_llm_unified,
    process_llm_query_simple
)

logger = setup_logger(__name__)

router = APIRouter()


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 요청/응답 모델
# --->
# 채팅 요청 모델
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    farm_id: Optional[str] = None
    house_id: Optional[str] = None
    farm_name: Optional[str] = None
    house_name: Optional[str] = None
    stream: bool = False


class ChatResponse(BaseModel):
    """채팅 응답 모델"""
    response: str
    timestamp: str
    farm_id: Optional[str] = None
    house_id: Optional[str] = None


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 채팅 엔드포인트
# --->
# 채팅 엔드포인트 (비스트리밍)
# Args:
#     request: 채팅 요청
# Returns:
#     ChatResponse: 채팅 응답
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        logger.info(f"채팅 요청: {request.message[:50]}...")

        # 스트리밍이 아닌 경우 간단한 처리
        if not request.stream:
            response = process_llm_query_simple(
                user_query=request.message,
                farm_id=request.farm_id,
                house_id=request.house_id,
                farm_name=request.farm_name,
                house_name=request.house_name
            )

            return ChatResponse(
                response=response,
                timestamp=datetime.now().isoformat(),
                farm_id=request.farm_id,
                house_id=request.house_id
            )
        else:
            # 스트리밍 요청인 경우 스트리밍 엔드포인트로 리다이렉트
            raise HTTPException(
                status_code=400,
                detail="스트리밍 요청은 /chat/stream 엔드포인트를 사용해주세요."
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"채팅 처리 중 오류: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"채팅 처리 중 오류가 발생했습니다: {str(e)}"
        )


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 스트리밍 채팅 엔드포인트
# --->
# Args:
#     request: 채팅 요청
# Returns:
#     StreamingResponse: 스트리밍 응답
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    try:
        logger.info(f"스트리밍 채팅 요청: {request.message[:50]}...")

        async def generate():
            async for chunk in query_llm_unified(
                user_query=request.message,
                farm_id=request.farm_id,
                house_id=request.house_id,
                farm_name=request.farm_name,
                house_name=request.house_name,
                stream=True
            ):
                yield chunk

        return StreamingResponse(
            generate(),
            media_type="text/plain"
        )

    except Exception as e:
        logger.error(f"스트리밍 채팅 처리 중 오류: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"스트리밍 채팅 처리 중 오류가 발생했습니다: {str(e)}"
        )


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 파일 첨부 채팅 엔드포인트
# --->
# Args:
#     message: 채팅 메시지
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#     farm_name: 농장명
#     house_name: 재배사명
#     files: 첨부 파일 목록
# Returns:
#     ChatResponse: 채팅 응답
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
@router.post("/chat/with-files", response_model=ChatResponse)
async def chat_with_files(
    message: str = Form(...),
    farm_id: Optional[str] = Form(None),
    house_id: Optional[str] = Form(None),
    farm_name: Optional[str] = Form(None),
    house_name: Optional[str] = Form(None),
    files: List[UploadFile] = File(None)
):
    try:
        logger.info(f"파일 첨부 채팅 요청: {message[:50]}..., 파일 수: {len(files) if files else 0}")

        # 파일 정보 추출
        file_paths = []
        if files:
            for file in files:
                # 파일 저장 로직 (임시 파일로 저장)
                import tempfile
                import os

                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
                    content = await file.read()
                    tmp.write(content)
                    file_paths.append({
                        "path": tmp.name,
                        "filename": file.filename
                    })

        # LLM 처리
        response_text = ""
        async for chunk in query_llm_unified(
            user_query=message,
            file_paths=file_paths if file_paths else None,
            farm_id=farm_id,
            house_id=house_id,
            farm_name=farm_name,
            house_name=house_name,
            stream=False
        ):
            response_text += chunk

        # 임시 파일 정리
        for file_info in file_paths:
            try:
                import os
                os.unlink(file_info["path"])
            except:
                pass

        return ChatResponse(
            response=response_text,
            timestamp=datetime.now().isoformat(),
            farm_id=farm_id,
            house_id=house_id
        )

    except Exception as e:
        logger.error(f"파일 첨부 채팅 처리 중 오류: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"파일 첨부 채팅 처리 중 오류가 발생했습니다: {str(e)}"
        )
