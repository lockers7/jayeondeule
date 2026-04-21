# ════════════════════════════════════════════════════════════════════
# STT(음성→텍스트) 엔진 — faster-whisper 기반 음성 인식.
# CPU + int8 양자화 + VAD 필터. medium 모델(한국어 정확도 ↑).
# --->
# _get_model        : faster-whisper 모델 lazy 싱글톤 로더
# _webm_to_wav_bytes: WebM/Opus → 16kHz mono WAV 변환 (PyAV)
# transcribe        : 음성 바이트를 한국어 텍스트로 변환
# ════════════════════════════════════════════════════════════════════
import io
import tempfile
import threading
import av
from faster_whisper import WhisperModel
from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_model = None
_model_lock = threading.Lock()


# ────────────────────────────────────────────────────────────────────
# faster-whisper 모델 lazy 싱글톤 로더 (스레드 안전, double-checked).
# ────────────────────────────────────────────────────────────────────
def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                logger.info("[STT] faster-whisper medium 모델 로딩 (CPU, int8)...")
                _model = WhisperModel("medium", device="cpu", compute_type="int8")
                logger.info("[STT] 모델 로딩 완료")
    return _model


# ────────────────────────────────────────────────────────────────────
# WebM/Opus 바이트를 16kHz mono WAV 바이트로 변환 (PyAV).
# ────────────────────────────────────────────────────────────────────
def _webm_to_wav_bytes(audio_bytes: bytes) -> bytes:
    input_buf = io.BytesIO(audio_bytes)
    output_buf = io.BytesIO()

    with av.open(input_buf, format="webm") as in_container:
        in_stream = in_container.streams.audio[0]
        with av.open(output_buf, mode="w", format="wav") as out_container:
            out_stream = out_container.add_stream("pcm_s16le", rate=16000, layout="mono")
            for frame in in_container.decode(in_stream):
                frame.pts = None
                for packet in out_stream.encode(frame):
                    out_container.mux(packet)
            for packet in out_stream.encode(None):
                out_container.mux(packet)

    return output_buf.getvalue()


# ────────────────────────────────────────────────────────────────────
# 음성 바이트를 한국어 텍스트로 변환. WebM/Opus 자동 감지 → WAV 변환 후 STT.
# ────────────────────────────────────────────────────────────────────
def transcribe(audio_bytes: bytes, content_type: str = "audio/webm") -> str:
    model = _get_model()

    # WebM이면 WAV로 변환
    if "webm" in content_type or "opus" in content_type:
        wav_bytes = _webm_to_wav_bytes(audio_bytes)
    else:
        wav_bytes = audio_bytes

    # 임시 파일에 쓰고 transcribe
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        tmp.write(wav_bytes)
        tmp.flush()

        segments, info = model.transcribe(
            tmp.name,
            language="ko",
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        text = " ".join(seg.text.strip() for seg in segments)

    logger.info("[STT] 변환 완료: lang=%s, dur=%.1fs, text_len=%d", info.language, info.duration, len(text))
    return text
