import React from "react";
import {Button, Card, Col} from "react-bootstrap";

// ════════════════════════════════════════════════════════════════════════════
// 단일 릴레이 카드 — ON/OFF 토글 버튼 + 라벨.
// - interlockInfo 가 전달되면 (흡입팬/배출팬 한정) 라벨 옆 빨간색 (잔여N초) 표시
// - disabledDevice=true 면 카드 회색 처리 + 버튼 비활성("미사용") + 클릭 차단
//   (실내히터·히터밸브 등 물리 미연결 장치 표시용 — 백엔드도 force OFF)
// ════════════════════════════════════════════════════════════════════════════
export default function RelayCard({relayNum, label, relayStatus, handleToggle, manualMode, toggleRelayMutation, interlockInfo, disabledDevice}) {
    const key = `relay${relayNum}stFlag`;
    const isOn = relayStatus[key];

    // 흡입팬/배출팬에 한해 — 현재 OFF 이고 ON 가능까지 잔여시간이 있을 때 표시
    const showRemaining = interlockInfo && !isOn
        && interlockInfo.can_on === false
        && Number(interlockInfo.remaining_sec) > 0;

    return (
        <Col xs={6} md={4} lg={3} key={key} className="mb-3">
            <Card
                className={`text-center shadow-sm ${
                    isOn ? "border-success" : "border-secondary"
                }`}
            >
                <Card.Body>
                    <Card.Title className="mb-2">
                        {label}
                        {showRemaining && (
                            <span
                                title={interlockInfo.gate_via_label
                                    ? `${interlockInfo.gate_via_label} ON 후 ${interlockInfo.gate_threshold_sec}초 경과 후 가동 가능`
                                    : "선행 밸브 ON 후 경과 시간 미충족"}
                                style={{color: "red", marginLeft: 4, fontWeight: 600}}
                            >
                                ({interlockInfo.remaining_sec})
                            </span>
                        )}
                    </Card.Title>
                    <Button
                        variant={isOn ? "success" : "outline-secondary"}
                        className="w-100"
                        onClick={() => handleToggle(relayNum)}
                        disabled={disabledDevice || !manualMode || toggleRelayMutation.isLoading}
                        title={disabledDevice ? "미사용 장치 (배선 미연결)" : ""}
                        style={disabledDevice ? {opacity: 1, cursor: "not-allowed"} : undefined}
                    >
                        {disabledDevice ? "미사용" : (isOn ? "ON" : "OFF")}
                    </Button>
                </Card.Body>
            </Card>
        </Col>
    );
}