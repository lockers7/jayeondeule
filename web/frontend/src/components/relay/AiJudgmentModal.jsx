import React from "react";
import {Modal, Button, Table, Badge} from "react-bootstrap";

const DEVICE_LABELS = {
    water_heater_flag: "물가열기",
    fog_occurs_flag: "분사펌프",
    indoor_heater_flag: "열풍기",
    indoor_heater_valve_flag: "열풍댐퍼",
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
    if (!judgment) return null;

    return (
        <Modal show={show} onHide={onHide} centered size="lg">
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
                <Button variant="secondary" onClick={onHide}>닫기</Button>
            </Modal.Footer>
        </Modal>
    );
}
