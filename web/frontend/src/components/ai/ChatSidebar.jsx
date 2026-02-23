import React, {useEffect, useState} from "react";
import {Button, Form} from "react-bootstrap";
import {getFarmList} from "../../utils/farmUtil.js";
import {getHouseList} from "../../utils/houseUtil.js";

export default function ChatSidebar({
                                        selectedFarm,
                                        setSelectedFarm,
                                        selectedHouse,
                                        setSelectedHouse,
                                        onClearMessages,
                                    }) {
    const [farms, setFarms] = useState([]);
    const [houses, setHouses] = useState([]);

    // 농장 목록 로드
    useEffect(() => {
        getFarmList(0, 100)
            .then((res) => {
                const list = res.data.content || [];
                setFarms(list);
                if (list.length > 0 && !selectedFarm) {
                    setSelectedFarm(list[0]);
                }
            })
            .catch(console.error);
    }, []);

    // 재배사 목록 로드 (농장 선택 변경 시)
    useEffect(() => {
        if (!selectedFarm) return;
        getHouseList({farmId: selectedFarm.farmId})
            .then((res) => {
                const list = res.data || [];
                setHouses(list);
                if (list.length > 0) {
                    setSelectedHouse(list[0]);
                }
            })
            .catch(console.error);
    }, [selectedFarm?.farmId]);

    const handleFarmChange = (e) => {
        const farm = farms.find((f) => String(f.farmId) === e.target.value);
        if (farm) setSelectedFarm(farm);
    };

    const handleHouseChange = (e) => {
        const house = houses.find((h) => String(h.housId) === e.target.value);
        if (house) setSelectedHouse(house);
    };

    return (
        <div
            style={{
                width: "280px",
                minWidth: "280px",
                borderRight: "1px solid #DEE2E6",
                padding: "20px 16px",
                backgroundColor: "#FAFAFA",
                display: "flex",
                flexDirection: "column",
                overflowY: "auto",
            }}
        >
            {/* 헤더 */}
            <h5 style={{color: "#1B5E20", marginBottom: "4px"}}>자연들에</h5>
            <small className="text-muted" style={{marginBottom: "20px"}}>스마트팜 AI 관리</small>

            <hr/>

            {/* 농장 선택 */}
            <Form.Group className="mb-3">
                <Form.Label style={{fontWeight: "600", fontSize: "14px"}}>농장 선택</Form.Label>
                <Form.Select
                    size="sm"
                    value={selectedFarm ? String(selectedFarm.farmId) : ""}
                    onChange={handleFarmChange}
                >
                    {farms.map((farm) => (
                        <option key={farm.farmId} value={String(farm.farmId)}>
                            {farm.farmName}
                        </option>
                    ))}
                </Form.Select>
            </Form.Group>

            {/* 재배사 선택 */}
            <Form.Group className="mb-3">
                <Form.Label style={{fontWeight: "600", fontSize: "14px"}}>재배사 선택</Form.Label>
                <Form.Select
                    size="sm"
                    value={selectedHouse ? String(selectedHouse.housId) : ""}
                    onChange={handleHouseChange}
                >
                    {houses.map((house) => (
                        <option key={house.housId} value={String(house.housId)}>
                            {house.housName}
                        </option>
                    ))}
                </Form.Select>
            </Form.Group>

            {/* 현재 선택 정보 */}
            <div
                style={{
                    backgroundColor: "#E3F2FD",
                    padding: "12px",
                    borderRadius: "6px",
                    border: "1px solid #90CAF9",
                    borderLeft: "3px solid #2196F3",
                    marginBottom: "20px",
                }}
            >
                <div style={{fontWeight: "600", fontSize: "13px", color: "#495057", marginBottom: "4px"}}>
                    현재 선택
                </div>
                <div style={{fontSize: "13px"}}>농장: {selectedFarm?.farmName || "-"}</div>
                <div style={{fontSize: "13px"}}>재배사: {selectedHouse?.housName || "-"}</div>
            </div>

            <hr/>

            {/* 대화 기록 삭제 */}
            <Button variant="outline-secondary" size="sm" className="w-100" onClick={onClearMessages}>
                대화 기록 삭제
            </Button>
        </div>
    );
}
