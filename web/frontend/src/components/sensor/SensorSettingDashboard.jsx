import React, {useEffect, useState} from "react";
import {Card, Form, Row, Col, Button, InputGroup, Badge} from "react-bootstrap";
import {Dash} from "react-bootstrap-icons";
import {deleteSetting, getSettings, insertSettings, patchSetting} from "../../utils/settingUtil.js";
import AlertModal from "../common/AlertModal.jsx";

const compactInput = { maxWidth: "100px" };
const labelStyle  = { minWidth: "110px", fontWeight: "bold", marginBottom: 0, whiteSpace: "nowrap" };
const greenCard   = { backgroundColor: "#fff", border: "2px solid #28a745" };

// 24시간 시:분 입력 (숫자 직접 입력)
const timeInputStyle = { width: "44px", padding: "4px 6px", fontSize: "0.95rem", textAlign: "center" };

function TimeInput({value, onChange}) {
    const [hh, mm] = (value || "00:00").split(":");
    const clamp = (v, min, max) => String(Math.max(min, Math.min(max, parseInt(v) || 0))).padStart(2, "0");
    const handleBlur = (part, v) => {
        const clamped = part === "hh" ? clamp(v, 0, 23) : clamp(v, 0, 59);
        const newVal = part === "hh" ? `${clamped}:${mm || "00"}` : `${hh || "00"}:${clamped}`;
        onChange(newVal);
    };
    return (
        <div className="d-flex align-items-center gap-1">
            <Form.Control size="sm" style={timeInputStyle} maxLength={2}
                defaultValue={hh || "00"} key={`${value}-hh`}
                onBlur={(e) => handleBlur("hh", e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && e.target.blur()}/>
            <span style={{fontWeight: "bold"}}>시</span>
            <Form.Control size="sm" style={timeInputStyle} maxLength={2}
                defaultValue={mm || "00"} key={`${value}-mm`}
                onBlur={(e) => handleBlur("mm", e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && e.target.blur()}/>
            <span style={{fontWeight: "bold"}}>분</span>
        </div>
    );
}

const WEEKDAYS = [
    {value: "1", label: "월"},
    {value: "2", label: "화"},
    {value: "3", label: "수"},
    {value: "4", label: "목"},
    {value: "5", label: "금"},
    {value: "6", label: "토"},
    {value: "7", label: "일"},
];

export default function SensorSettingDashboard({farmId, selectedHouse}) {
    const [show, setShow] = useState(false);
    const [deleteTarget, setDeleteTarget] = useState({});

    const [sensorSetting, setSensorSetting] = useState({
        tprtMin: "", tprtMax: "",
        watrTprtMin: "", watrTprtMax: "",
        hmdtMin: "", hmdtMax: "",
        co2Min: "", co2Max: "",
    });

    const [lightSchedules, setLightSchedules] = useState([]);
    const [waterSchedules, setWaterSchedules] = useState([]);

    const handleScheduleChange = (index, type, field, value) => {
        const newSchedules = type === "LIGHT" ? [...lightSchedules] : [...waterSchedules];
        newSchedules[index][field] = value;
        type === "LIGHT" ? setLightSchedules(newSchedules) : setWaterSchedules(newSchedules);

        patchSetting(farmId, selectedHouse, newSchedules[index]);
    };

    const handleExcsTypeChange = (index, type, newExcsType) => {
        const newSchedules = type === "LIGHT" ? [...lightSchedules] : [...waterSchedules];
        newSchedules[index].excsType = newExcsType;
        if (newExcsType === "daily") {
            newSchedules[index].excsItvl = null;
            newSchedules[index].excsStrtDate = null;
            newSchedules[index].excsWkdy = null;
        } else if (newExcsType === "interval") {
            newSchedules[index].excsWkdy = null;
        } else if (newExcsType === "weekdays") {
            newSchedules[index].excsItvl = null;
            newSchedules[index].excsStrtDate = null;
        }
        type === "LIGHT" ? setLightSchedules(newSchedules) : setWaterSchedules(newSchedules);
        patchSetting(farmId, selectedHouse, newSchedules[index]);
    };

    const handleWeekdayToggle = (index, type, dayValue) => {
        const schedules = type === "LIGHT" ? lightSchedules : waterSchedules;
        const current = schedules[index].excsWkdy ? schedules[index].excsWkdy.split(",") : [];
        const updated = current.includes(dayValue)
            ? current.filter(d => d !== dayValue)
            : [...current, dayValue].sort();
        handleScheduleChange(index, type, "excsWkdy", updated.length > 0 ? updated.join(",") : null);
    };

    const addSchedule = (type) => {
        const newSchedule = {strtTime: "00:00", fnshTime: "00:00", dlteYn: false, unitType: type, excsType: "daily", excsItvl: null, excsStrtDate: null, excsWkdy: null};
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
                tprtMin: "", tprtMax: "",
                watrTprtMin: "", watrTprtMax: "",
                hmdtMin: "", hmdtMax: "",
                co2Min: "", co2Max: "",
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
                unitType: item.unitType,
                excsType: item.excsType || "daily",
                excsItvl: item.excsItvl,
                excsStrtDate: item.excsStrtDate,
                excsWkdy: item.excsWkdy,
            };

            if (item.unitType === "LIGHT") {
                setLightSchedules(prev => [...prev, newSchedule]);
            } else {
                setWaterSchedules(prev => [...prev, newSchedule]);
            }
        });
    });

    const renderScheduleItem = (schedule, idx, type) => {
        const excsType = schedule.excsType || "daily";
        const selectedWkdy = schedule.excsWkdy ? schedule.excsWkdy.split(",") : [];

        return (
            <Card key={idx} className="mb-2 p-2" style={{border: "1px solid #dee2e6", backgroundColor: "#fafffe"}}>
                {/* 시간 + 토글 + 삭제 */}
                <div className="d-flex align-items-center justify-content-center gap-2 mb-1 flex-wrap">
                    <TimeInput value={schedule.strtTime}
                        onChange={(v) => handleScheduleChange(idx, type, "strtTime", v)}/>
                    <span style={{fontWeight: "bold", fontSize: "1.1rem"}}>~</span>
                    <TimeInput value={schedule.fnshTime}
                        onChange={(v) => handleScheduleChange(idx, type, "fnshTime", v)}/>
                    <Form.Check
                        type="switch"
                        checked={!schedule.dlteYn}
                        onClick={() => handleScheduleChange(idx, type, 'dlteYn', !schedule.dlteYn)}
                        disabled={!(schedule.strtTime && schedule.fnshTime)}
                    />
                    <Button
                        style={{ width: "28px", height: "28px", display: "flex", alignItems: "center", justifyContent: "center", padding: "0" }}
                        variant="danger" size="sm"
                        onClick={() => { setShow(true); setDeleteTarget({id: idx, type}); }}
                    >
                        <Dash/>
                    </Button>
                </div>

                {/* 실행 유형 선택 */}
                <div className="d-flex align-items-center justify-content-center gap-2 mb-1" style={{fontSize: "0.85rem"}}>
                    <Form.Check inline type="radio" name={`excsType-${type}-${idx}`} id={`daily-${type}-${idx}`}
                        label="매일" checked={excsType === "daily"}
                        onChange={() => handleExcsTypeChange(idx, type, "daily")}/>
                    <Form.Check inline type="radio" name={`excsType-${type}-${idx}`} id={`interval-${type}-${idx}`}
                        label="N일마다" checked={excsType === "interval"}
                        onChange={() => handleExcsTypeChange(idx, type, "interval")}/>
                    <Form.Check inline type="radio" name={`excsType-${type}-${idx}`} id={`weekdays-${type}-${idx}`}
                        label="요일선택" checked={excsType === "weekdays"}
                        onChange={() => handleExcsTypeChange(idx, type, "weekdays")}/>
                </div>

                {/* interval 옵션: 간격 + 시작일 */}
                {excsType === "interval" && (
                    <div className="d-flex align-items-center justify-content-center gap-2 mb-1" style={{fontSize: "0.85rem"}}>
                        <Form.Control type="number" min="1" style={{maxWidth: "60px", padding: "2px 6px"}}
                            value={schedule.excsItvl || ""}
                            onChange={(e) => handleScheduleChange(idx, type, "excsItvl", e.target.value ? parseInt(e.target.value) : null)}
                        />
                        <span>일마다</span>
                        <Form.Control type="date" style={{maxWidth: "150px", padding: "2px 6px"}}
                            value={schedule.excsStrtDate || ""}
                            onChange={(e) => handleScheduleChange(idx, type, "excsStrtDate", e.target.value || null)}
                        />
                        <span style={{whiteSpace: "nowrap"}}>부터</span>
                    </div>
                )}

                {/* weekdays 옵션: 요일 체크 */}
                {excsType === "weekdays" && (
                    <div className="d-flex align-items-center justify-content-center gap-1 mb-1">
                        {WEEKDAYS.map(day => (
                            <Badge key={day.value} pill
                                bg={selectedWkdy.includes(day.value) ? "success" : "secondary"}
                                style={{cursor: "pointer", fontSize: "0.8rem", padding: "5px 8px"}}
                                onClick={() => handleWeekdayToggle(idx, type, day.value)}
                            >
                                {day.label}
                            </Badge>
                        ))}
                    </div>
                )}
            </Card>
        );
    };

    return (
        <div className="p-3">
            <Card className="mb-3 p-3" style={greenCard}>
                <div className="d-flex align-items-center justify-content-center mb-2">
                    <span style={labelStyle}>온도(&#8451;)</span>
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
                    <span style={labelStyle}>수온(&#8451;)</span>
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
                    <span style={labelStyle}>CO&#8322;(ppm)</span>
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
                        {lightSchedules.map((schedule, idx) => renderScheduleItem(schedule, idx, "LIGHT"))}
                        <div className="text-center mt-2">
                            <Button variant="success" size="sm" onClick={() => addSchedule("LIGHT")}>+ 시간 추가</Button>
                        </div>
                    </Card>
                </Col>
                <Col md={6} className="mb-3">
                    <Card className="p-3 h-100" style={greenCard}>
                        <h5 className="text-center">관수 시간 설정</h5>
                        {waterSchedules.map((schedule, idx) => renderScheduleItem(schedule, idx, "WATER"))}
                        <div className="text-center mt-2">
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
