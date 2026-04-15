import React, { useEffect, useState } from "react";
import { Button, Form, Alert } from "react-bootstrap";
import { useSelector, useDispatch } from "react-redux";
import { setSelectedFarm as setGlobalSelectedFarm } from "../../store/auth/authSlice.js";
import { getFarmList, getMyFarm } from "../../utils/farmUtil.js";
import { getHouseList } from "../../utils/houseUtil.js";

export default function ChatSidebar({
    selectedFarm,
    setSelectedFarm,
    selectedHouse,
    setSelectedHouse,
    onClearMessages,
    speechStyle,
    setSpeechStyle,
    modelAlert,
    setModelAlert,
}) {
    const dispatch = useDispatch();
    const [farms, setFarms] = useState([]);
    const [houses, setHouses] = useState([]);
    const [region, setRegion] = useState("확인 중...");

    // 관리자 전용: LLM 모델 관리
    const userInfo = useSelector((state) => state.auth?.userInfo);
    const globalSelectedFarm = useSelector((state) => state.auth.selectedFarm);
    const isAdmin = userInfo?.authLvel === "ADMIN";
    const isSysMonitor = userInfo?.authLvel === "SYS_MONITOR";
    const [availableModels, setAvailableModels] = useState([]);
    const [currentModel, setCurrentModel] = useState("");

    // IP 기반 지역 판단 (서버 측 조회)
    useEffect(() => {
        fetch("/ai-api/geo")
            .then((res) => res.json())
            .then((data) => {
                if (data.city && data.region) {
                    setRegion(`${data.region} ${data.city}`);
                } else if (data.city) {
                    setRegion(data.city);
                } else if (data.region) {
                    setRegion(data.region);
                } else {
                    setRegion("알 수 없음");
                }
            })
            .catch(() => {
                setRegion("알 수 없음");
            });
    }, []);

    // 관리자 전용: Ollama 모델 목록 로드
    useEffect(() => {
        if (!isAdmin) return;
        fetch("/ai-api/api/v1/admin/models")
            .then((res) => res.json())
            .then((data) => {
                if (data.success) {
                    setAvailableModels(data.models || []);
                    setCurrentModel(data.current_model || "");
                }
            })
            .catch(() => {});
    }, [isAdmin]);

    const handleModelChange = (e) => {
        const newModel = e.target.value;
        if (!newModel || newModel === currentModel) return;

        fetch("/ai-api/api/v1/admin/models", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model_name: newModel }),
        })
            .then((res) => res.json())
            .then((data) => {
                if (data.success) {
                    setCurrentModel(newModel);
                    setModelAlert({ variant: "info", text: `모델이 '${newModel}'로 변경되었습니다. 다음 대화부터 적용됩니다.` });
                } else {
                    setModelAlert({ variant: "danger", text: `모델 변경 실패: ${data.detail || data.error || "알 수 없는 오류"}` });
                }
            })
            .catch((err) => {
                setModelAlert({ variant: "danger", text: `모델 변경 실패: ${err.message}` });
            });
    };

    // 농장 목록 로드 (admin/시스템모니터링: 전체 농장, 비admin: 소속 농장)
    useEffect(() => {
        if (isAdmin || isSysMonitor) {
            getFarmList(0, 100)
                .then((res) => {
                    const list = res.data.content || [];
                    setFarms(list);
                    if (list.length > 0 && !selectedFarm) {
                        // Redux에 선택된 농장이 있으면 그것을 기본값으로 사용
                        if (globalSelectedFarm) {
                            const match = list.find(f => f.farmId === globalSelectedFarm.farmId);
                            setSelectedFarm(match || list[0]);
                        } else {
                            setSelectedFarm(list[0]);
                        }
                    }
                })
                .catch(err => { console.error(err); });
        } else {
            getMyFarm()
                .then((res) => {
                    if (res.data) {
                        setFarms([res.data]);
                        if (!selectedFarm) {
                            setSelectedFarm(res.data);
                        }
                    }
                })
                .catch(err => { console.error(err); });
        }
    }, [isAdmin, isSysMonitor]);

    // 재배사 목록 로드 (농장 선택 변경 시)
    useEffect(() => {
        if (!selectedFarm) return;
        getHouseList({ farmId: selectedFarm.farmId })
            .then((res) => {
                const list = res.data || [];
                setHouses(list);
                if (list.length > 0) {
                    setSelectedHouse(list[0]);
                }
            })
            .catch(err => { console.error(err); });
    }, [selectedFarm?.farmId]);

    const handleFarmChange = (e) => {
        const farm = farms.find((f) => String(f.farmId) === e.target.value);
        if (farm) {
            setSelectedFarm(farm);
            // ADMIN/SYS_MONITOR: 농장 콤보 변경 시 헤더 농장명(Redux)도 동기화
            if (isAdmin || isSysMonitor) {
                dispatch(setGlobalSelectedFarm({ farmId: farm.farmId, farmName: farm.farmName }));
            }
        }
    };

    const handleHouseChange = (e) => {
        const house = houses.find((h) => String(h.housId) === e.target.value);
        if (house) setSelectedHouse(house);
    };

    return (
        <div
            style={{
                width: "220px",
                minWidth: "220px",
                borderRight: "1px solid #DEE2E6",
                padding: "20px 16px",
                backgroundColor: "#FAFAFA",
                display: "flex",
                flexDirection: "column",
                overflowY: "auto",
            }}
        >
            {/* 헤더 */}
            <h5 style={{ color: "#1B5E20", marginBottom: "4px" }}>자연들에</h5>
            <small className="text-muted" style={{ marginBottom: "0", display: "block" }}>스마트팜 AI 관리</small>

            <div style={{ height: "2em" }} />

            {/* 대화체 선택 */}
            <Form.Group className="mb-2">
                <Form.Label style={{ fontWeight: "600", fontSize: "13px", marginBottom: "4px" }}>대화체</Form.Label>
                <Form.Select
                    size="sm"
                    value={speechStyle || "male"}
                    onChange={(e) => setSpeechStyle(e.target.value)}
                    style={{ fontSize: "13px" }}
                >
                    <option value="male">남성 (사무적)</option>
                    <option value="female">여성 (부드러운)</option>
                </Form.Select>
            </Form.Group>

            {/* 농장 선택 */}
            <Form.Group className="mb-3">
                <Form.Label style={{ fontWeight: "600", fontSize: "14px" }}>농장 선택</Form.Label>
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
                <Form.Label style={{ fontWeight: "600", fontSize: "14px" }}>재배사 선택</Form.Label>
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
                <div style={{ fontWeight: "600", fontSize: "13px", color: "#495057", marginBottom: "4px" }}>
                    현재 선택
                </div>
                <div style={{ fontSize: "13px", display: "flex" }}><span style={{ width: "52px", display: "inline-block" }}>지&nbsp;&nbsp;&nbsp;역</span>:&nbsp;{region}</div>
                <div style={{ fontSize: "13px", display: "flex" }}><span style={{ width: "52px", display: "inline-block" }}>농&nbsp;&nbsp;&nbsp;장</span>:&nbsp;{selectedFarm?.farmName || "-"}</div>
                <div style={{ fontSize: "13px", display: "flex" }}><span style={{ width: "52px", display: "inline-block" }}>재배사</span>:&nbsp;{selectedHouse?.housName || "-"}</div>
            </div>

            <hr />

            {/* 대화 기록 삭제 */}
            <Button variant="outline-secondary" size="sm" className="w-100" onClick={onClearMessages}>
                대화 기록 삭제
            </Button>

            {/* 관리자 전용: LLM 모델 선택 */}
            {isAdmin && availableModels.length > 0 && (
                <>
                    <hr />
                    <Form.Group className="mb-2">
                        <Form.Label style={{ fontWeight: "600", fontSize: "13px", color: "#D32F2F", marginBottom: "4px" }}>
                            LLM 모델 ({userInfo?.userId || "Admin"})
                        </Form.Label>
                        <Form.Select
                            size="sm"
                            value={currentModel}
                            onChange={handleModelChange}
                            style={{ fontSize: "12px" }}
                        >
                            {availableModels.map((m) => (
                                <option key={m.name} value={m.name}>
                                    {m.name} ({m.parameter_size || "?"}/{m.size_gb}GB)
                                </option>
                            ))}
                        </Form.Select>
                    </Form.Group>
                    {modelAlert && (
                        <Alert
                            variant={modelAlert.variant}
                            dismissible
                            onClose={() => setModelAlert(null)}
                            style={{ fontSize: "12px", padding: "8px 10px", marginBottom: "0" }}
                        >
                            {modelAlert.text}
                        </Alert>
                    )}
                </>
            )}
        </div>
    );
}
