"""edge-tts 기반 TTS 엔진 (한국어, ko-KR-SunHiNeural)"""
import io
import edge_tts
from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

VOICE = "ko-KR-SunHiNeural"
MAX_TEXT_LENGTH = 2000


async def synthesize(text: str) -> bytes:
    """텍스트를 MP3 바이트로 변환"""
    if not text or not text.strip():
        raise ValueError("TTS 텍스트가 비어있습니다.")

    # 텍스트 길이 제한
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]
        logger.warning("[TTS] 텍스트 길이 초과, %d자로 잘림", MAX_TEXT_LENGTH)

    communicate = edge_tts.Communicate(text, VOICE)
    buffer = io.BytesIO()

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buffer.write(chunk["data"])

    mp3_bytes = buffer.getvalue()
    logger.info("[TTS] 변환 완료: text_len=%d, mp3_size=%d bytes", len(text), len(mp3_bytes))
    return mp3_bytes
