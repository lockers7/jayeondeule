import React, {useState, useRef, useCallback} from "react";
import {Spinner} from "react-bootstrap";
import {MicFill, StopFill} from "react-bootstrap-icons";
import {speechToText} from "../../../utils/voiceUtil.js";
import "./VoiceMicButton.css";

/**
 * 마이크 녹음 버튼
 * @param {function} onTranscribed - STT 완료 시 텍스트 전달 콜백
 * @param {boolean} disabled - 버튼 비활성화
 */
export default function VoiceMicButton({onTranscribed, onStatusChange, disabled = false}) {
    // idle | recording | processing
    const [status, setStatus] = useState("idle");

    const updateStatus = useCallback((newStatus) => {
        setStatus(newStatus);
        onStatusChange?.(newStatus);
    }, [onStatusChange]);
    const mediaRecorderRef = useRef(null);
    const chunksRef = useRef([]);

    const startRecording = useCallback(async () => {
        // HTTPS 또는 localhost가 아니면 마이크 API 사용 불가
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            const isLocalhost = location.hostname === "localhost" || location.hostname === "127.0.0.1";
            if (!isLocalhost) {
                alert("음성 입력은 HTTPS 환경에서만 사용할 수 있습니다.\n\n현재 HTTP 접속 중이므로 브라우저가 마이크 접근을 차단합니다.");
            } else {
                alert("이 브라우저에서 마이크를 지원하지 않습니다.");
            }
            return;
        }

        try {
            const stream = await navigator.mediaDevices.getUserMedia({audio: true});
            const mediaRecorder = new MediaRecorder(stream, {mimeType: "audio/webm;codecs=opus"});
            mediaRecorderRef.current = mediaRecorder;
            chunksRef.current = [];

            mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) chunksRef.current.push(e.data);
            };

            mediaRecorder.onstop = async () => {
                // 스트림 트랙 해제
                stream.getTracks().forEach(t => t.stop());

                const audioBlob = new Blob(chunksRef.current, {type: "audio/webm;codecs=opus"});
                if (audioBlob.size === 0) {
                    updateStatus("idle");
                    return;
                }

                updateStatus("processing");
                try {
                    const result = await speechToText(audioBlob);
                    if (result.success && result.text) {
                        onTranscribed?.(result.text);
                    }
                } catch (err) {
                    console.error("STT 오류:", err);
                } finally {
                    updateStatus("idle");
                }
            };

            mediaRecorder.start();
            updateStatus("recording");
        } catch (err) {
            console.error("마이크 접근 오류:", err);
            if (err.name === "NotAllowedError") {
                alert("마이크 사용이 거부되었습니다.\n브라우저 설정에서 마이크 권한을 허용해주세요.");
            } else if (err.name === "NotFoundError") {
                alert("마이크를 찾을 수 없습니다.\n마이크가 연결되어 있는지 확인해주세요.");
            } else {
                alert("마이크 접근 오류: " + err.message);
            }
            updateStatus("idle");
        }
    }, [onTranscribed, updateStatus]);

    const stopRecording = useCallback(() => {
        if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
            mediaRecorderRef.current.stop();
        }
    }, []);

    const handleClick = () => {
        if (disabled || status === "processing") return;
        if (status === "idle") {
            startRecording();
        } else if (status === "recording") {
            stopRecording();
        }
    };

    const btnClass = `voice-mic-btn voice-mic-${status}`;

    return (
        <button
            className={btnClass}
            onClick={handleClick}
            disabled={disabled || status === "processing"}
            title={status === "idle" ? "음성 입력" : status === "recording" ? "녹음 중지" : "변환 중..."}
        >
            {status === "processing" ? (
                <Spinner animation="border" size="sm"/>
            ) : status === "recording" ? (
                <StopFill size={16}/>
            ) : (
                <MicFill size={16}/>
            )}
        </button>
    );
}
