import React, {useState, useRef, useCallback} from "react";
import {Spinner} from "react-bootstrap";
import {VolumeUpFill, StopFill} from "react-bootstrap-icons";
import {textToSpeech} from "../../../utils/voiceUtil.js";
import "./VoiceTtsButton.css";

/**
 * TTS 재생/정지 버튼
 * @param {string} text - 읽을 텍스트
 */
export default function VoiceTtsButton({text}) {
    // idle | loading | playing
    const [status, setStatus] = useState("idle");
    const audioRef = useRef(null);
    const urlRef = useRef(null);

    const cleanup = useCallback(() => {
        if (audioRef.current) {
            audioRef.current.pause();
            audioRef.current = null;
        }
        if (urlRef.current) {
            URL.revokeObjectURL(urlRef.current);
            urlRef.current = null;
        }
    }, []);

    const play = useCallback(async () => {
        setStatus("loading");
        try {
            const mp3Blob = await textToSpeech(text);
            const url = URL.createObjectURL(mp3Blob);
            urlRef.current = url;

            const audio = new Audio(url);
            audioRef.current = audio;

            audio.onended = () => {
                cleanup();
                setStatus("idle");
            };
            audio.onerror = () => {
                cleanup();
                setStatus("idle");
            };

            await audio.play();
            setStatus("playing");
        } catch (err) {
            console.error("TTS 오류:", err);
            cleanup();
            setStatus("idle");
        }
    }, [text, cleanup]);

    const stop = useCallback(() => {
        cleanup();
        setStatus("idle");
    }, [cleanup]);

    const handleClick = () => {
        if (status === "loading") return;
        if (status === "playing") {
            stop();
        } else {
            play();
        }
    };

    if (!text || !text.trim()) return null;

    const btnClass = `voice-tts-btn ${status === "playing" ? "voice-tts-playing" : status === "loading" ? "voice-tts-loading" : ""}`;

    return (
        <button
            className={btnClass}
            onClick={handleClick}
            disabled={status === "loading"}
            title={status === "idle" ? "음성으로 듣기" : status === "playing" ? "재생 중지" : "변환 중..."}
        >
            {status === "loading" ? (
                <Spinner animation="border" size="sm" style={{width: "14px", height: "14px"}}/>
            ) : status === "playing" ? (
                <StopFill size={14}/>
            ) : (
                <VolumeUpFill size={14}/>
            )}
        </button>
    );
}
