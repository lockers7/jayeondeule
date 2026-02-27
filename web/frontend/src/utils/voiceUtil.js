/**
 * 음성 API 통신 유틸리티 (STT/TTS)
 */

const VOICE_API_BASE = "/ai-api/api/v1/voice";

/**
 * STT — 음성 파일을 텍스트로 변환
 * @param {Blob} audioBlob - 녹음된 오디오 Blob
 * @returns {Promise<{success: boolean, text: string}>}
 */
export async function speechToText(audioBlob) {
    const formData = new FormData();
    formData.append("file", audioBlob, "recording.webm");

    const response = await fetch(`${VOICE_API_BASE}/stt`, {
        method: "POST",
        body: formData,
    });

    if (!response.ok) {
        throw new Error(`STT 요청 실패 (HTTP ${response.status})`);
    }

    return response.json();
}

/**
 * TTS — 텍스트를 음성(MP3)으로 변환
 * @param {string} text - 변환할 텍스트
 * @returns {Promise<Blob>} MP3 Blob
 */
export async function textToSpeech(text) {
    const response = await fetch(`${VOICE_API_BASE}/tts`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({text}),
    });

    if (!response.ok) {
        throw new Error(`TTS 요청 실패 (HTTP ${response.status})`);
    }

    return response.blob();
}
