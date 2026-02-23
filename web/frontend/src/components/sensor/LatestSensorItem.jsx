import React from "react";
import {Form} from "react-bootstrap";
import {useQueryClient, useMutation} from "@tanstack/react-query";
import {patchHouse} from "../../utils/houseUtil.js";
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

export default function LatestSensorItem({latestSensorData, house, setSelectedHouse, selectedHouse, farmId}) {
    const queryClient = useQueryClient();
    const trStyle = {};
    const now = new Date();
    const recdTime = new Date(latestSensorData.recdDttm);

    if ((now - recdTime) / 1000 > 60) { // 1분(60초) 이상 차이면
        trStyle.color = "red";
    }

    if(selectedHouse.housId == house.housId) {
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

    return (
            <tr className="sensorItem" onClick={() => setSelectedHouse(house)} style={{cursor: "pointer"}}>
                <td style={{...trStyle, padding: "0"}}>{house.housName}</td>
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
                <td style={trStyle}>{Math.round(latestSensorData.indrTprtValu * 100) / 100 + "℃" ?? "-"}</td>
                <td style={trStyle}>{Math.round(latestSensorData.oudrTprtValu * 100) / 100 + "℃" ?? "-"}</td>
                <td style={trStyle}>{Math.round(latestSensorData.indrHmdtValu * 100) / 100 + "%" ?? "-"}</td>
                <td style={trStyle}>{Math.round(latestSensorData.oudrHmdtValu * 100) / 100 + "%" ?? "-"}</td>
                <td style={trStyle}>{Math.round(latestSensorData.co2Valu * 100) / 100 + "ppm" ?? "-"}</td>
                <td style={trStyle}>{Math.round(latestSensorData.watrTprtValu * 100) / 100 + "℃" ?? "-"}</td>
                <td style={{...trStyle, fontSize: "12px"}}>
                    {formatDate(latestSensorData.recdDttm)}<br/>
                    {formatTime(latestSensorData.recdDttm)}
                </td>
            </tr>
    )
}
