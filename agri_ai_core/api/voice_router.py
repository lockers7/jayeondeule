"""음성 API 라우터 — STT (POST /stt) + TTS (POST /tts)"""
import time
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

voice_router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


class TtsRequest(BaseModel):
    text: str


@voice_router.post("/stt")
async def stt_endpoint(file: UploadFile = File(...)):
    """음성 파일을 텍스트로 변환 (STT)"""
    from agri_ai_core.src.voice.stt_engine import transcribe

    start = time.time()
    try:
        audio_bytes = await file.read()
        if not audio_bytes:
            raise HTTPException(400, "빈 오디오 파일입니다.")

        # 최대 30MB
        if len(audio_bytes) > 30 * 1024 * 1024:
            raise HTTPException(413, "오디오 파일이 너무 큽니다. (최대 30MB)")

        content_type = file.content_type or "audio/webm"
        text = transcribe(audio_bytes, content_type)

        return {
            "success": True,
            "text": text,
            "processing_time": round(time.time() - start, 3),
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        logger.error("[STT] 오류: %s", e)
        return {
            "success": False,
            "text": "",
            "error": str(e),
            "processing_time": round(time.time() - start, 3),
        }


@voice_router.post("/tts")
async def tts_endpoint(request: TtsRequest):
    """텍스트를 음성(MP3)으로 변환 (TTS)"""
    from agri_ai_core.src.voice.tts_engine import synthesize

    start = time.time()
    try:
        if not request.text or not request.text.strip():
            raise HTTPException(400, "텍스트가 비어있습니다.")

        mp3_bytes = await synthesize(request.text)

        return Response(
            content=mp3_bytes,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=tts.mp3",
                "X-Processing-Time": str(round(time.time() - start, 3)),
            },
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        logger.error("[TTS] 오류: %s", e)
        raise HTTPException(500, f"TTS 변환 오류: {str(e)}")
