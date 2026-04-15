import React, {useState} from "react";
import {Form} from "react-bootstrap";
import {useQueryClient, useMutation} from "@tanstack/react-query";
import {patchHouse} from "../../utils/houseUtil.js";
import axios from "axios";
import "./LatestSensorItem.css";

function getOperationMode(mnulCtrlFlag, ctrlType) {
    if (!mnulCtrlFlag) return "manual";
    if (ctrlType === "ai") return "ai";
    return "algorithm";
}

function parseOperationMode(mode) {
    if (mode === "manual") return {mnulCtrlFlag: false, ctrlType: "algorithm"};
    if (mode === "ai") return {mnulCtrlFlag: true, ctrlType: "ai"};
    return {mnulCtrlFlag: true, ctrlType: "algorithm"};
}

const CROP_LEVEL_OPTIONS = [
    {value: 1, label: "발이기"},
    {value: 2, label: "생육기"},
    {value: 3, label: "수확기"},
    {value: 4, label: "휴지기"},
];

const fmt = (v, unit) => (v != null ? Math.round(v * 100) / 100 + unit : "-");

export default function LatestSensorItem({latestSensorData, house, setSelectedHouse, selectedHouse, farmId, isAdmin, isStale = false}) {
    const queryClient = useQueryClient();
    const [rpiRestarting, setRpiRestarting] = useState(false);
    const trStyle = {};
    const hasSensorData = latestSensorData != null;

    // house_id=0 (통합정보재배사)는 센서 없는 특수 재배사 → 에러 체크 제외
    if (house.housId === 0) {
        trStyle.color = "#999";
    } else if (isStale) {
        // 30초간 데이터 변경 없음 → 에러
        trStyle.color = "red";
        trStyle.fontWeight = "bold";
    } else if (!hasSensorData) {
        trStyle.color = "#999";
    }

    if(selectedHouse?.housId == house.housId) {
        trStyle.backgroundColor = "#f4f8fd";
        trStyle.fontWeight = "bold";
    }

    const modeMutation = useMutation({
        mutationFn: (updatedHouse) => patchHouse({farmId, ...updatedHouse}),
        onSuccess: () => queryClient.invalidateQueries(["houses", String(farmId)]),
    });

    const handleModeChange = (e) => {
        e.stopPropagation();
        const {mnulCtrlFlag, ctrlType} = parseOperationMode(e.target.value);
        modeMutation.mutate({...house, mnulCtrlFlag, ctrlType});
    };

    const handleCropLevelChange = (e) => {
        e.stopPropagation();
        modeMutation.mutate({...house, cropLvel: Number(e.target.value)});
    };

    const formatDate = (dateString) => {
        const d = new Date(dateString);
        const yyyy = d.getFullYear();
        const mm = String(d.getMonth() + 1).padStart(2, "0");
        const dd = String(d.getDate()).padStart(2, "0");
        return `${yyyy}-${mm}-${dd}`;
    };

    const formatTime = (dateString) => {
        const d = new Date(dateString);
        const hh = String(d.getHours()).padStart(2, "0");
        const min = String(d.getMinutes()).padStart(2, "0");
        const ss = String(d.getSeconds()).padStart(2, "0");
        return `${hh}:${min}:${ss}`;
    };

    const handleRpiRestart = async (e) => {
        e.stopPropagation();
        if (!window.confirm(`${house.housName}의 라즈베리파이를 재시작하시겠습니까?`)) return;
        setRpiRestarting(true);
        try {
            await axios.post("/ai-api/api/v1/rpi/restart", {
                farm_id: Number(farmId),
                house_id: house.housId,
            });
            alert(`${house.housName} RPi 재시작 완료`);
        } catch (err) {
            alert(`재시작 실패: ${err.response?.data?.detail || err.message}`);
        } finally {
            setRpiRestarting(false);
        }
    };

    return (
            <tr className="sensorItem" onClick={() => setSelectedHouse(house)} style={{cursor: "pointer"}}>
                <td style={{...trStyle, padding: "0"}}>{house.housName}</td>
                <td style={{...trStyle, padding: "2px", textAlign: "center"}} onClick={(e) => e.stopPropagation()}>
                    <div style={{display: "inline-block"}}>
                    <Form.Select
                        size="sm"
                        value={house.cropLvel ?? 2}
                        onChange={handleCropLevelChange}
                        disabled={modeMutation.isPending}
                        style={{fontSize: "inherit", padding: "2px 2.2rem 2px 2px", width: "fit-content", color: trStyle.color || "inherit", fontWeight: trStyle.fontWeight || "normal"}}
                    >
                        {CROP_LEVEL_OPTIONS.map(opt => (
                            <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
                    </Form.Select>
                    </div>
                </td>
                <td style={{...trStyle, padding: "2px", textAlign: "center"}} onClick={(e) => e.stopPropagation()}>
                    <div style={{display: "inline-block"}}>
                    <Form.Select
                        size="sm"
                        value={getOperationMode(house.mnulCtrlFlag, house.ctrlType)}
                        onChange={handleModeChange}
                        disabled={modeMutation.isPending}
                        style={{fontSize: "inherit", padding: "2px 2.2rem 2px 2px", width: "fit-content", color: trStyle.color || "inherit", fontWeight: trStyle.fontWeight || "normal"}}
                    >
                        <option value="ai">인공지능</option>
                        <option value="algorithm">알고리즘</option>
                        <option value="manual">수동제어</option>
                    </Form.Select>
                    </div>
                </td>
                <td style={trStyle}>{fmt(latestSensorData?.indrTprtValu, "℃")}</td>
                <td style={trStyle}>{fmt(latestSensorData?.oudrTprtValu, "℃")}</td>
                <td style={trStyle}>{fmt(latestSensorData?.indrHmdtValu, "%")}</td>
                <td style={trStyle}>{fmt(latestSensorData?.oudrHmdtValu, "%")}</td>
                <td style={trStyle}>{fmt(latestSensorData?.co2Valu, "ppm")}</td>
                <td style={trStyle}>{fmt(latestSensorData?.watrTprtValu, "℃")}</td>
                <td style={{...trStyle, fontSize: "12px"}}>
                    {hasSensorData ? (<>{formatDate(latestSensorData.recdDttm)}<br/>{formatTime(latestSensorData.recdDttm)}</>) : "-"}
                </td>
                {isAdmin && (
                    <td style={{...trStyle, textAlign: "center"}} onClick={(e) => e.stopPropagation()}>
                        <button
                            onClick={handleRpiRestart}
                            disabled={rpiRestarting}
                            title={`${house.housName} RPi 재시작`}
                            style={{
                                background: "none", border: "1px solid #ccc", borderRadius: "4px",
                                cursor: rpiRestarting ? "wait" : "pointer", padding: "2px 8px",
                                fontSize: "14px", color: rpiRestarting ? "#999" : "#dc3545",
                            }}
                        >
                            {rpiRestarting ? "⏳" : "🔄"}
                        </button>
                    </td>
                )}
            </tr>
    )
}
