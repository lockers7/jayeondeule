import React, {useEffect, useState} from "react";
import {Card, Form, Row, Col, Button, InputGroup} from "react-bootstrap";
import {Dash} from "react-bootstrap-icons";
import {deleteSetting, getSettings, insertSettings, patchSetting} from "../../utils/settingUtil.js";
import AlertModal from "../common/AlertModal.jsx";

const compactInput = { maxWidth: "100px" };
const labelStyle  = { minWidth: "110px", fontWeight: "bold", marginBottom: 0, whiteSpace: "nowrap" };
const greenCard   = { backgroundColor: "#fff", border: "2px solid #28a745" };

export default function SensorSettingDashboard({farmId, selectedHouse}) {
    const [show, setShow] = useState(false);

    const [deleteTarget, setDeleteTarget] = useState({});

    const [sensorSetting, setSensorSetting] = useState({
        tprtMin: "",
        tprtMax: "",
        watrTprtMin: "",
        watrTprtMax: "",
        hmdtMin: "",
        hmdtMax: "",
        co2Min: "",
        co2Max: "",
    });

    const [lightSchedules, setLightSchedules] = useState([]);
    const [waterSchedules, setWaterSchedules] = useState([]);

    const handleScheduleChange = (index, type, field, value) => {
        const newSchedules = type === "LIGHT" ? [...lightSchedules] : [...waterSchedules];
        newSchedules[index][field] = value;
        type === "LIGHT" ? setLightSchedules(newSchedules) : setWaterSchedules(newSchedules);

        patchSetting(farmId, selectedHouse, newSchedules[index]);
    };

    const addSchedule = (type) => {
        const newSchedule = {strtTime: "00:00", fnshTime: "00:00", dlteYn: false, unitType: type};
        if (type === "LIGHT") {
            setLightSchedules([...lightSchedules, newSchedule]);
        } else {
            setWaterSchedules([...waterSchedules, newSchedule]);
        }
        insertSettings(farmId, selectedHouse, {lightIrrigationSettingInsertDTO: newSchedule}).then(fetchSettings);
    };

    const deleteSchedule = (idx, type) => {
        if (type === "LIGHT") {
            deleteSetting(farmId, selectedHouse, lightSchedules[idx].setnDttm);
            setLightSchedules(prev => prev.filter((_, i) => i !== idx));
        } else {
            deleteSetting(farmId, selectedHouse, waterSchedules[idx].setnDttm);
            setWaterSchedules(prev => prev.filter((_, i) => i !== idx));
        }
        setShow(false);
    };

    useEffect(() => {
        fetchSettings();
    }, [selectedHouse]);

    const handleSensorSettingChange = (type, value) => {
        setSensorSetting({...sensorSetting, [type]: value});
    }

    const handleSensorSettingInsert = () => {
        insertSettings(farmId, selectedHouse, {sensorSettingInsertDTO: sensorSetting});
    }

    const fetchSettings = () => getSettings(farmId, selectedHouse).then((res) => {
        const newSensorSetting = res.data.sensorSettingDTO;
        if (newSensorSetting) {
            newSensorSetting.setnDttm = "";
            setSensorSetting(newSensorSetting);
        } else {
            setSensorSetting({
                tprtMin: "",
                tprtMax: "",
                watrTprtMin: "",
                watrTprtMax: "",
                hmdtMin: "",
                hmdtMax: "",
                co2Min: "",
                co2Max: "",
            });
        }

        setLightSchedules([]);
        setWaterSchedules([]);
        res.data.lightIrrigationSettingDTO.map(item => {
            const newSchedule = {
                strtTime: item.strtTime,
                fnshTime: item.fnshTime,
                dlteYn: item.dlteYn,
                setnDttm: item.setnDttm,
                unitType: item.unitType
            };

            if (item.unitType === "LIGHT") {
                setLightSchedules(prev => [...prev, newSchedule]);
            } else {
                setWaterSchedules(prev => [...prev, newSchedule]);
            }
        });
    });

    return (
        <div className="p-3">
            <Card className="mb-3 p-3" style={greenCard}>
                <div className="d-flex align-items-center justify-content-center mb-2">
                    <span style={labelStyle}>온도(℃)</span>
                    <InputGroup style={{ maxWidth: "260px" }}>
                        <Form.Control style={compactInput} value={sensorSetting && sensorSetting.tprtMin}
                            onChange={(e) => handleSensorSettingChange("tprtMin", e.target.value)}
                            onBlur={handleSensorSettingInsert} type="number" placeholder="최소"/>
                        <InputGroup.Text>~</InputGroup.Text>
                        <Form.Control style={compactInput} value={sensorSetting && sensorSetting.tprtMax}
                            onChange={(e) => handleSensorSettingChange("tprtMax", e.target.value)}
                            onBlur={handleSensorSettingInsert} type="number" placeholder="최대"/>
                    </InputGroup>
                </div>
                <div className="d-flex align-items-center justify-content-center mb-2">
                    <span style={labelStyle}>수온(℃)</span>
                    <InputGroup style={{ maxWidth: "260px" }}>
                        <Form.Control style={compactInput} value={sensorSetting && sensorSetting.watrTprtMin}
                            onChange={(e) => handleSensorSettingChange("watrTprtMin", e.target.value)}
                            onBlur={handleSensorSettingInsert} type="number" placeholder="최소"/>
                        <InputGroup.Text>~</InputGroup.Text>
                        <Form.Control style={compactInput} value={sensorSetting && sensorSetting.watrTprtMax}
                            onChange={(e) => handleSensorSettingChange("watrTprtMax", e.target.value)}
                            onBlur={handleSensorSettingInsert} type="number" placeholder="최대"/>
                    </InputGroup>
                </div>
                <div className="d-flex align-items-center justify-content-center mb-2">
                    <span style={labelStyle}>습도(%)</span>
                    <InputGroup style={{ maxWidth: "260px" }}>
                        <Form.Control style={compactInput} value={sensorSetting && sensorSetting.hmdtMin}
                            onChange={(e) => handleSensorSettingChange("hmdtMin", e.target.value)}
                            onBlur={handleSensorSettingInsert} type="number" placeholder="최소"/>
                        <InputGroup.Text>~</InputGroup.Text>
                        <Form.Control style={compactInput} value={sensorSetting && sensorSetting.hmdtMax}
                            onChange={(e) => handleSensorSettingChange("hmdtMax", e.target.value)}
                            onBlur={handleSensorSettingInsert} type="number" placeholder="최대"/>
                    </InputGroup>
                </div>
                <div className="d-flex align-items-center justify-content-center mb-2">
                    <span style={labelStyle}>CO₂(ppm)</span>
                    <InputGroup style={{ maxWidth: "260px" }}>
                        <Form.Control style={compactInput} value={sensorSetting && sensorSetting.co2Min}
                            onChange={(e) => handleSensorSettingChange("co2Min", e.target.value)}
                            onBlur={handleSensorSettingInsert} type="number" placeholder="최소"/>
                        <InputGroup.Text>~</InputGroup.Text>
                        <Form.Control style={compactInput} value={sensorSetting && sensorSetting.co2Max}
                            onChange={(e) => handleSensorSettingChange("co2Max", e.target.value)}
                            onBlur={handleSensorSettingInsert} type="number" placeholder="최대"/>
                    </InputGroup>
                </div>
            </Card>

            <Row>
                <Col md={6} className="mb-3">
                    <Card className="p-3 h-100" style={greenCard}>
                        <h5 className="text-center">조명 시간 설정</h5>
                        {lightSchedules.map((schedule, idx) => (
                            <div key={idx} className="d-flex align-items-center justify-content-center mb-2">
                                <InputGroup style={{ maxWidth: "360px" }}>
                                    <Form.Control type="time" value={schedule.strtTime}
                                                  onChange={(e) => handleScheduleChange(idx, "LIGHT", "strtTime", e.target.value)}/>
                                    <InputGroup.Text>~</InputGroup.Text>
                                    <Form.Control type="time" value={schedule.fnshTime}
                                                  onChange={(e) => handleScheduleChange(idx, "LIGHT", "fnshTime", e.target.value)}/>
                                    <InputGroup.Text>
                                        <Form.Check
                                            type="switch"
                                            checked={!schedule.dlteYn}
                                            onClick={() => handleScheduleChange(idx, 'LIGHT', 'dlteYn', !schedule.dlteYn)}
                                            disabled={!(schedule.strtTime && schedule.fnshTime)}
                                        />
                                    </InputGroup.Text>
                                    <Button
                                        style={{ maxWidth: "20px", display: "flex", alignItems: "center", justifyContent: "center", padding: "0" }}
                                        variant="danger"
                                        onClick={() => { setShow(true); setDeleteTarget({id: idx, type: 'LIGHT'}); }}
                                    >
                                        <Dash/>
                                    </Button>
                                </InputGroup>
                            </div>
                        ))}
                        <div className="text-center">
                            <Button variant="success" size="sm" onClick={() => addSchedule("LIGHT")}>+ 시간 추가</Button>
                        </div>
                    </Card>
                </Col>
                <Col md={6} className="mb-3">
                    <Card className="p-3 h-100" style={greenCard}>
                        <h5 className="text-center">관수 시간 설정</h5>
                        {waterSchedules.map((schedule, idx) => (
                            <div key={idx} className="d-flex align-items-center justify-content-center mb-2">
                                <InputGroup style={{ maxWidth: "360px" }}>
                                    <Form.Control type="time" value={schedule.strtTime}
                                                  onChange={(e) => handleScheduleChange(idx, "WATER", "strtTime", e.target.value)}/>
                                    <InputGroup.Text>~</InputGroup.Text>
                                    <Form.Control type="time" value={schedule.fnshTime}
                                                  onChange={(e) => handleScheduleChange(idx, "WATER", "fnshTime", e.target.value)}/>
                                    <InputGroup.Text>
                                        <Form.Check
                                            type="switch"
                                            checked={!schedule.dlteYn}
                                            onClick={() => handleScheduleChange(idx, 'WATER', 'dlteYn', !schedule.dlteYn)}
                                            disabled={!(schedule.strtTime && schedule.fnshTime)}
                                        />
                                    </InputGroup.Text>
                                    <Button
                                        style={{ maxWidth: "20px", display: "flex", alignItems: "center", justifyContent: "center", padding: "0" }}
                                        variant="danger"
                                        onClick={() => { setShow(true); setDeleteTarget({id: idx, type: 'WATER'}); }}
                                    >
                                        <Dash/>
                                    </Button>
                                </InputGroup>
                            </div>
                        ))}
                        <div className="text-center">
                            <Button variant="success" size="sm" onClick={() => addSchedule("WATER")}>+ 시간 추가</Button>
                        </div>
                    </Card>
                </Col>
            </Row>
            <AlertModal
                show={show}
                hideModalFunc={() => setShow(false)}
                onClickFunc={() => deleteSchedule(deleteTarget.id, deleteTarget.type)}
                title="정말 삭제하시겠습니까?"
                body="삭제 후 복구가 불가능할 수 있습니다."
                variant="danger"
                buttonMsg="삭제"
            />
        </div>
    );
}
