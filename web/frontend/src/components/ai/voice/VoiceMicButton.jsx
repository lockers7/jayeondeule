import React, {useState, useRef, useCallback, useEffect} from "react";
import {Spinner} from "react-bootstrap";
import {MicFill, StopFill} from "react-bootstrap-icons";
import {speechToText} from "../../../utils/voiceUtil.js";
import "./VoiceMicButton.css";

/**
 * 마이크 녹음 버튼 (실시간 음성 인식 + 서버 STT)
 * - 녹음 중: Web Speech API로 실시간 텍스트를 onInterimResult로 전달 (입력창에 표시)
 * - 녹음 완료: 서버 STT(Whisper)로 최종 정확한 텍스트를 onTranscribed로 전달
 */
export default function VoiceMicButton({onTranscribed, onInterimResult, onStatusChange, disabled = false}) {
    const [status, setStatus] = useState("idle");

    const updateStatus = useCallback((newStatus) => {
        setStatus(newStatus);
        onStatusChange?.(newStatus);
    }, [onStatusChange]);

    const mediaRecorderRef = useRef(null);
    const chunksRef = useRef([]);
    const recognitionRef = useRef(null);
    const interimTextRef = useRef("");
    const silenceTimerRef = useRef(null);

    const SILENCE_TIMEOUT_MS = 3000; // 3초 무음 시 자동 종료

    // 컴포넌트 언마운트 시 정리
    useEffect(() => {
        return () => {
            if (recognitionRef.current) {
                try { recognitionRef.current.abort(); } catch {}
            }
            if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
        };
    }, []);

    // 무음 타이머 리셋 (음성 입력이 있을 때마다 호출)
    const resetSilenceTimer = useCallback(() => {
        if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
        silenceTimerRef.current = setTimeout(() => {
            // 3초간 음성 입력 없음 → 자동 녹음 종료
            if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
                mediaRecorderRef.current.stop();
            }
        }, SILENCE_TIMEOUT_MS);
    }, []);

    // Web Speech API 실시간 인식 시작
    const startSpeechRecognition = useCallback(() => {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) return; // 미지원 브라우저면 건너뜀

        try {
            const recognition = new SpeechRecognition();
            recognition.lang = "ko-KR";
            recognition.continuous = true;
            recognition.interimResults = true;

            recognition.onresult = (event) => {
                let interim = "";
                let final = "";
                for (let i = event.resultIndex; i < event.results.length; i++) {
                    const transcript = event.results[i][0].transcript;
                    if (event.results[i].isFinal) {
                        final += transcript;
                    } else {
                        interim += transcript;
                    }
                }
                interimTextRef.current = final + interim;
                onInterimResult?.(interimTextRef.current);
                resetSilenceTimer(); // 음성 입력 감지 → 타이머 리셋
            };

            recognition.onerror = () => {}; // 무시 (서버 STT가 최종 처리)
            recognition.onend = () => {};   // 자동 재시작 안 함

            recognition.start();
            recognitionRef.current = recognition;
        } catch {
            // Web Speech API 실패해도 서버 STT로 처리 가능
        }
    }, [onInterimResult, resetSilenceTimer]);

    // Web Speech API 중지
    const stopSpeechRecognition = useCallback(() => {
        if (recognitionRef.current) {
            try { recognitionRef.current.stop(); } catch {}
            recognitionRef.current = null;
        }
    }, []);

    const startRecording = useCallback(async () => {
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
            interimTextRef.current = "";

            mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) chunksRef.current.push(e.data);
            };

            mediaRecorder.onstop = async () => {
                stream.getTracks().forEach(t => t.stop());
                stopSpeechRecognition();
                if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);

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
                    } else if (interimTextRef.current) {
                        // 서버 STT 실패 시 Web Speech API 결과 사용
                        onTranscribed?.(interimTextRef.current);
                    }
                } catch (err) {
                    console.error("STT 오류:", err);
                    // 서버 오류 시 Web Speech API 결과로 대체
                    if (interimTextRef.current) {
                        onTranscribed?.(interimTextRef.current);
                    }
                } finally {
                    updateStatus("idle");
                }
            };

            mediaRecorder.start();
            startSpeechRecognition(); // 실시간 인식 동시 시작
            resetSilenceTimer();      // 무음 타이머 시작
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
    }, [onTranscribed, updateStatus, startSpeechRecognition, stopSpeechRecognition]);

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
