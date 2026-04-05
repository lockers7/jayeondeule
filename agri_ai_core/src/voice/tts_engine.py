# ════════════════════════════════════════════════════════
# TTS(텍스트→음성) 엔진 모듈
# edge-tts 기반 한국어 음성 합성 (ko-KR-SunHiNeural 보이스) 기능을 제공합니다.
# --->
# synthesize: 텍스트를 MP3 바이트로 변환
# ════════════════════════════════════════════════════════
import io
import edge_tts
from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

VOICE = "ko-KR-SunHiNeural"
MAX_TEXT_LENGTH = 2000


# ══════════════════
# 텍스트를 MP3 바이트로 변환
# ══════════════════
async def synthesize(text: str) -> bytes:
    if not text or not text.strip():
        raise ValueError("TTS 텍스트가 비어있습니다.")

    # 텍스트 길이 제한
    was_truncated = False
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]
        was_truncated = True
        logger.warning("[TTS] 텍스트 길이 초과, %d자로 잘림", MAX_TEXT_LENGTH)

    communicate = edge_tts.Communicate(text, VOICE)
    buffer = io.BytesIO()

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buffer.write(chunk["data"])

    mp3_bytes = buffer.getvalue()
    logger.info("[TTS] 변환 완료: text_len=%d, mp3_size=%d bytes%s",
                len(text), len(mp3_bytes), " (잘림)" if was_truncated else "")
    return mp3_bytes
