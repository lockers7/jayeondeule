import React, {useRef} from "react";
import {Modal, Button, Table, Badge} from "react-bootstrap";

const DEVICE_LABELS = {
    water_heater_flag: "수온히터",
    fog_occurs_flag: "포그생성",
};

function DeviceBadges({devices}) {
    if (!devices) return <span className="text-muted">-</span>;
    return Object.entries(devices).map(([key, value]) => {
        const label = DEVICE_LABELS[key] || key;
        return (
            <Badge
                key={key}
                bg={value ? "success" : "secondary"}
                className="me-1 mb-1"
            >
                {label}: {value ? "ON" : "OFF"}
            </Badge>
        );
    });
}

export default function AiJudgmentModal({show, onHide, judgment, toggledDevice}) {
    // [2026-04-27] 팝업 표시 직후 닫기 버튼에 포커스 — 사용자가 마우스 클릭
    // 없이 스페이스바/Enter 만으로 즉시 닫을 수 있게 한다. ESC 는 react-bootstrap
    // Modal 의 기본 keyboard prop(true) 으로 이미 동작. (useRef 는 조건부 호출
    // 금지 규칙 때문에 early-return 보다 위에 둔다.)
    const closeBtnRef = useRef(null);
    const focusCloseBtn = () => {
        if (closeBtnRef.current) closeBtnRef.current.focus();
    };

    if (!judgment) return null;

    return (
        <Modal show={show} onHide={onHide} centered size="lg" onEntered={focusCloseBtn}>
            <Modal.Header closeButton className="bg-info bg-opacity-10">
                <Modal.Title>
                    AI가 추천하는 알고리즘 제어
                </Modal.Title>
            </Modal.Header>
            <Modal.Body>
                {toggledDevice && (
                    <div className="alert alert-warning mb-3 py-2">
                        <strong>수동 제어:</strong> {toggledDevice}
                    </div>
                )}

                <Table bordered size="sm" className="mb-0">
                    <tbody>
                        <tr>
                            <th className="bg-light" style={{width: "25%"}}>센서 현황</th>
                            <td>{judgment.sensor || "-"}</td>
                        </tr>
                        <tr>
                            <th className="bg-light">생육단계</th>
                            <td>{judgment.growth_stage || "-"}</td>
                        </tr>
                        <tr>
                            <th className="bg-light">AI 판단 사유</th>
                            <td><strong>{judgment.reason || "-"}</strong></td>
                        </tr>
                        <tr>
                            <th className="bg-light">권장 장치 상태</th>
                            <td><DeviceBadges devices={judgment.devices}/></td>
                        </tr>
                        <tr>
                            <th className="bg-light">권장 순환모드</th>
                            <td>
                                {judgment.circulation ? (
                                    <Badge bg="primary">{judgment.circulation}</Badge>
                                ) : "-"}
                            </td>
                        </tr>
                        <tr>
                            <th className="bg-light">장치 요약</th>
                            <td>{judgment.device_summary || "-"}</td>
                        </tr>
                    </tbody>
                </Table>
            </Modal.Body>
            <Modal.Footer>
                <Button ref={closeBtnRef} variant="secondary" onClick={onHide}>닫기</Button>
            </Modal.Footer>
        </Modal>
    );
}
