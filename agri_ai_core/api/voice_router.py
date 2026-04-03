"""음성 API 라우터: STT/TTS REST API 엔드포인트."""
import time
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from agri_ai_core.logs import setup_logger, setup_api_logger

logger = setup_logger(__name__)
api_logger = setup_api_logger("api_voice")

voice_router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


# ════════════════════════════════════════════════════════════
# 음성 파일을 텍스트로 변환 (STT)
# ════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════
# 텍스트를 음성(MP3)으로 변환 (TTS)
# ════════════════════════════════════════════════════════════
class TtsRequest(BaseModel):
    text: str

# ════════════════════════════════════════════════════════════
# 음성 파일을 텍스트로 변환 (STT)
# ════════════════════════════════════════════════════════════
@voice_router.post("/stt")
async def stt_endpoint(file: UploadFile = File(...)):
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
        api_logger.debug("[STT 요청] content_type=%s, size=%dB", content_type, len(audio_bytes))

        text = transcribe(audio_bytes, content_type)
        processing_time = round(time.time() - start, 3)

        api_logger.debug("[STT 완료] %.3fs, text=%s", processing_time, text[:100] if text else "")

        return {
            "success": True,
            "text": text,
            "processing_time": processing_time,
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        logger.error("[STT] 오류: %s", e)
        api_logger.error("[STT 오류] %s", e)
        return {
            "success": False,
            "text": "",
            "error": str(e),
            "processing_time": round(time.time() - start, 3),
        }


@voice_router.post("/tts")
async def tts_endpoint(request: TtsRequest):
    from agri_ai_core.src.voice.tts_engine import synthesize

    start = time.time()
    try:
        if not request.text or not request.text.strip():
            raise HTTPException(400, "텍스트가 비어있습니다.")

        api_logger.debug("[TTS 요청] text=%s", request.text[:100] if request.text else "")

        mp3_bytes = await synthesize(request.text)
        processing_time = round(time.time() - start, 3)

        api_logger.debug("[TTS 완료] %.3fs, size=%dB", processing_time, len(mp3_bytes) if mp3_bytes else 0)

        return Response(
            content=mp3_bytes,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=tts.mp3",
                "X-Processing-Time": str(processing_time),
            },
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        logger.error("[TTS] 오류: %s", e)
        api_logger.error("[TTS 오류] %s", e)
        raise HTTPException(500, f"TTS 변환 오류: {str(e)}")
