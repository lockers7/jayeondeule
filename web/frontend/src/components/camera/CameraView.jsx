import React, { useState, useEffect, useRef } from "react";
import { Spinner, Alert, Button } from "react-bootstrap";

/**
 * 재배사별 카메라 MJPEG 실시간 스트림 컴포넌트
 *
 * - houseId에 해당하는 /camera/{houseId}/ 경로로 연결
 * - 카메라 미설치 시: RPi에서 "카메라 없음" 안내 이미지 반환 (오류 없음)
 * - 카메라 오프라인(RPi 미응답) 시: 오프라인 안내 표시
 * - MJPEG 실패 시: 2초 스냅샷 폴백
 */
export default function CameraView({ houseId }) {
    const baseUrl = `/camera/${houseId}`;
    const [status, setStatus] = useState("connecting"); // connecting | ok | error | offline
    const [useSnapshot, setUseSnapshot] = useState(false);
    const imgRef = useRef(null);
    const snapshotTimer = useRef(null);

    // 재배사 변경 시 초기화
    useEffect(() => {
        setStatus("connecting");
        setUseSnapshot(false);
        clearInterval(snapshotTimer.current);
    }, [houseId]);

    // 오프라인 여부 확인
    useEffect(() => {
        fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(5000) })
            .then(r => { if (r.ok) setStatus(prev => prev === "connecting" ? "connecting" : prev); })
            .catch(() => setStatus("offline"));
    }, [houseId]);

    // MJPEG 스트림 상태 감시
    const handleStreamLoad = () => setStatus("ok");
    const handleStreamError = () => {
        setStatus("error");
        setUseSnapshot(true);
    };

    // 스냅샷 폴백: 2초마다 갱신
    useEffect(() => {
        if (!useSnapshot) return;
        const refresh = () => {
            if (imgRef.current) imgRef.current.src = `${baseUrl}/snapshot?t=${Date.now()}`;
        };
        refresh();
        snapshotTimer.current = setInterval(refresh, 2000);
        return () => clearInterval(snapshotTimer.current);
    }, [useSnapshot, houseId]);

    const handleRetry = () => {
        setStatus("connecting");
        setUseSnapshot(false);
    };

    if (status === "offline") {
        return (
            <Alert variant="warning" className="mt-3">
                <Alert.Heading>카메라 오프라인</Alert.Heading>
                <p className="mb-0">재배사 {houseId}번 라즈베리파이에 연결할 수 없습니다. 장치 전원 및 네트워크 상태를 확인해 주세요.</p>
            </Alert>
        );
    }

    return (
        <div style={{ padding: "12px 0" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                <span style={{ fontSize: "13px", color: "#6c757d" }}>
                    재배사 {houseId}번 카메라 {useSnapshot ? "— 스냅샷 모드 (2초 갱신)" : "— 실시간 스트림"}
                </span>
                <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                    {status === "ok" && <span style={{ fontSize: "12px", color: "#28a745" }}>● 연결됨</span>}
                    {status === "error" && (
                        <Button size="sm" variant="outline-secondary" onClick={handleRetry}>재시도</Button>
                    )}
                </div>
            </div>

            <div style={{ position: "relative", background: "#000", borderRadius: "8px", overflow: "hidden", textAlign: "center" }}>
                {status === "connecting" && (
                    <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "#1a1a1a" }}>
                        <div style={{ textAlign: "center", color: "#fff" }}>
                            <Spinner animation="border" variant="light" size="sm" />
                            <div style={{ marginTop: "8px", fontSize: "13px" }}>연결 중...</div>
                        </div>
                    </div>
                )}
                {!useSnapshot ? (
                    <img
                        src={`${baseUrl}/stream`}
                        alt={`재배사 ${houseId}번 카메라`}
                        onLoad={handleStreamLoad}
                        onError={handleStreamError}
                        style={{ maxWidth: "100%", width: "100%", height: "auto", display: "block", opacity: status === "ok" ? 1 : 0 }}
                    />
                ) : (
                    <img
                        ref={imgRef}
                        alt={`재배사 ${houseId}번 스냅샷`}
                        onLoad={() => setStatus("ok")}
                        onError={() => setStatus("error")}
                        style={{ maxWidth: "100%", width: "100%", height: "auto", display: "block" }}
                    />
                )}
            </div>
        </div>
    );
}
