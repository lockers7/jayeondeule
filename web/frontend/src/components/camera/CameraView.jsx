import React, { useState, useEffect } from "react";
import { Alert } from "react-bootstrap";

/**
 * 단일 카메라 MJPEG 스트림
 * - 실시간 스트리밍만 사용 (스냅샷 폴백 없음)
 * - 카메라 없음 / 오프라인 상태 모두 img onError로 처리
 */
function CameraStream({ farmId, houseId, label }) {
    const [errored, setErrored] = useState(false);
    const src = `/camera/${farmId}/${houseId}/stream`;

    // farmId/houseId 변경 시 오류 상태 초기화
    useEffect(() => { setErrored(false); }, [farmId, houseId]);

    return (
        <div style={{ marginBottom: "8px" }}>
            {label && (
                <div style={{ fontSize: "13px", fontWeight: "600", color: "#495057", marginBottom: "4px" }}>
                    {label}
                </div>
            )}
            <div style={{ background: "#000", borderRadius: "8px", overflow: "hidden" }}>
                {errored ? (
                    <div style={{
                        background: "#1e1e1e",
                        aspectRatio: "16/9",
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        justifyContent: "center",
                        gap: "8px",
                        color: "#6c757d",
                        fontSize: "13px"
                    }}>
                        <span style={{ fontSize: "28px" }}>📷</span>
                        <span>카메라 연결 실패</span>
                        <span style={{ fontSize: "11px" }}>재배사 {houseId}번 — RPi 오프라인 또는 카메라 미설치</span>
                    </div>
                ) : (
                    <img
                        src={src}
                        alt={`재배사 ${houseId}번 카메라`}
                        onError={() => setErrored(true)}
                        style={{ width: "100%", display: "block" }}
                    />
                )}
            </div>
        </div>
    );
}

/**
 * 재배사별 카메라 뷰
 * - houseId === 0 : 농장 전체 재배사 카메라 그리드 표시
 * - houseId > 0   : 해당 재배사 카메라 단독 표시
 */
export default function CameraView({ farmId, houseId, houses = [] }) {
    // houseId=0 (통합정보재배사) → 전체 재배사 카메라 표시
    if (Number(houseId) === 0) {
        const cameraHouses = houses.filter(h => h.housId !== 0);
        if (cameraHouses.length === 0) {
            return (
                <Alert variant="secondary" className="mt-3">
                    표시할 재배사 카메라가 없습니다.
                </Alert>
            );
        }
        return (
            <div style={{ padding: "12px 0" }}>
                <div style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
                    gap: "16px"
                }}>
                    {cameraHouses.map(h => (
                        <CameraStream
                            key={h.housId}
                            farmId={farmId}
                            houseId={h.housId}
                            label={h.housName}
                        />
                    ))}
                </div>
            </div>
        );
    }

    // 특정 재배사 단독 표시
    return (
        <div style={{ padding: "12px 0" }}>
            <CameraStream farmId={farmId} houseId={houseId} />
        </div>
    );
}
