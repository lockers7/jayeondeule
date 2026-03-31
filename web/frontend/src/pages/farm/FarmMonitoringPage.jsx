import React, { useState, useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Container, Tabs, Tab, Accordion } from "react-bootstrap";
import { useSelector, useDispatch } from "react-redux";
import { setSelectedFarm } from "../../store/auth/authSlice.js";
import { useQuery } from "@tanstack/react-query";

import { getHouseList } from "../../utils/houseUtil.js";
import { getLatestSensorData, getSensorData } from "../../utils/sensorUtil.js";
import { getFarm } from "../../utils/farmUtil.js";

import FarmKebabMenu from "../../components/farm/FarmKebabMenu.jsx";
import HouseList from "../../components/house/HouseList.jsx";
import LatestSensorMonitor from "../../components/sensor/LatestSensorMonitor.jsx";
import HouseSensorDashboard from "../../components/sensor/HouseSensorDashboard.jsx";
import RelayDashboard from "../../components/relay/RelayDashboard.jsx";
import LoadingPage from "../../pages/common/LoadingPage.jsx";
import ErrorPage from "../../pages/common/ErrorPage.jsx";

import "./FarmMonitoringPage.css";
import MemoDashboard from "../../components/memo/MemoDashboard.jsx";
import { getUser } from "../../utils/userUtil.js";
import SensorSettingDashboard from "../../components/sensor/SensorSettingDashboard.jsx";
import LatestSensorSelected from "../../components/sensor/LatestSensorSelected.jsx";
import CameraView from "../../components/camera/CameraView.jsx";

export default function FarmMonitoringPage() {
    const { farmId } = useParams();
    const auth = useSelector(state => state.auth);
    const dispatch = useDispatch();
    const navigate = useNavigate();

    // 페이지 이동 후 복귀 시 상태 유지용 sessionStorage 키 접두사
    const SK = `fmon_${farmId}`;

    const [isAccordionOpened, setIsAccordionOpened] = useState(
        () => sessionStorage.getItem(`${SK}_acc`) ?? "0"
    );
    const [activeTab, setActiveTab] = useState(
        () => sessionStorage.getItem(`${SK}_tab`) || "sensor"
    );

    const [selectedHouse, setSelectedHouse] = useState(null);
    const [startDate, setStartDate] = useState(() => {
        const stored = sessionStorage.getItem(`${SK}_sd`);
        if (stored) return stored;
        const d = new Date();
        d.setMonth(d.getMonth() - 1);
        d.setDate(d.getDate() + 1);
        return d.toISOString().split("T")[0];
    });
    const [endDate, setEndDate] = useState(
        () => sessionStorage.getItem(`${SK}_ed`) || new Date().toISOString().split("T")[0]
    );

    const handleSetSelectedHouse = (house) => {
        setSelectedHouse(house);
        if (house) sessionStorage.setItem(`${SK}_hid`, String(house.housId));
        else sessionStorage.removeItem(`${SK}_hid`);
    };
    const handleSetStartDate = (date) => {
        setStartDate(date);
        sessionStorage.setItem(`${SK}_sd`, date);
    };
    const handleSetEndDate = (date) => {
        setEndDate(date);
        sessionStorage.setItem(`${SK}_ed`, date);
    };
    const handleAccordionSelect = (key) => {
        setIsAccordionOpened(key);
        sessionStorage.setItem(`${SK}_acc`, key ?? "");
    };
    const handleTabChange = (tab) => {
        setActiveTab(tab);
        sessionStorage.setItem(`${SK}_tab`, tab);
    };

    // 농장 정보
    const { data: farm, isLoading: farmLoading, error: farmError } = useQuery({
        queryKey: ["farm", farmId],
        queryFn: () => getFarm({ farmId }).then(res => res.data),
        enabled: !!farmId,
    });

    // 재배사 전체 리스트 (housId=0 포함, 메모 재배사 선택용)
    const isAdmin = auth.userInfo?.authLvel === "ADMIN";
    const { data: allHouses = [] } = useQuery({
        queryKey: ["allHouses", farmId],
        queryFn: () => getHouseList({ farmId }).then(res => res.data || []),
        enabled: !!farmId,
    });

    // 재배사 리스트 (비ADMIN: housId=0 제외, 모니터/센서용)
    const houses = isAdmin ? allHouses : allHouses.filter(h => h.housId !== 0);
    const housesLoading = false;
    const housesError = null;

    // 선택된 하우스 센서 데이터
    const {
        data: sensorData = [],
        isLoading: sensorLoading,
        error: sensorError,
        refetch: refetchSensor
    } = useQuery({
        queryKey: ["sensorData", farmId, selectedHouse],
        queryFn: () => {
            if (!selectedHouse) return [];
            const startDateTime = `${startDate}T00:00:00`;
            const endDateTime = `${endDate}T23:59:59`;
            return getSensorData(farmId, selectedHouse.housId, startDateTime, endDateTime).then(res => res.data);
        },
        enabled: !!selectedHouse,
    });

    // 선택된 하우스 센서 데이터
    const {
        data: latestSensorData = {},
        isLoading: latestSensorLoading,
        error: latestSensorError,
        refetch: refetchLatestSensor
    } = useQuery({
        queryKey: ["latestSensorData", farmId, selectedHouse],
        queryFn: () => {
            if (!selectedHouse) return [];
            return getLatestSensorData(farmId, selectedHouse.housId).then(res => res.data);
        },
        refetchInterval: 3000, // 3초마다 polling
        enabled: !!selectedHouse,
    });

    // 사용자의 아이디로 접근권한을 가진 farm을 호출
    useEffect(() => {
        if (!farmId) {
            getUser().then((res) => navigate(`/farm/${res.data.farmId}/monitor`));
        }
    }, [farmId, navigate])

    // 농장 정보 로드 시 우측 상단 메뉴에 농장명 반영
    useEffect(() => {
        if (farm) {
            dispatch(setSelectedFarm({farmId: farm.farmId, farmName: farm.farmName}));
        }
    }, [farm]);

    // selectedHouse 초기값: 이전 선택 재배사 복원 → 없으면 첫 번째
    useEffect(() => {
        if (!selectedHouse && houses.length > 0) {
            const storedId = Number(sessionStorage.getItem(`${SK}_hid`));
            const saved = storedId ? houses.find(h => h.housId === storedId) : null;
            handleSetSelectedHouse(saved || houses[0]);
        }
    }, [houses]);

    const onSettingsClick = () => {
        navigate(`/farm/${farmId}/house/${selectedHouse.housId}/sensor/setting`);
    }

    if (farmLoading) return <LoadingPage />;
    if (farmError || housesError || sensorError) return <ErrorPage />;

    return (
        <Container className="mt-4">
            <div className="d-flex justify-content-between align-items-center mb-3">
                {farm && (
                    <h3 className="mb-0">{farm.farmName} 현황</h3>
                )}
            </div>

            {/* 최신 센서 데이터 */}
            <Accordion onSelect={handleAccordionSelect} activeKey={isAccordionOpened} className="mb-3">
                <Accordion.Item eventKey="0">
                    <Accordion.Header>
                        <span style={{ fontWeight: "bold", fontSize: "150%", textAlign: "center" }}>실 시 간    재 배 사   현 황</span>
                    </Accordion.Header>
                    <Accordion.Body className="p-0">
                        {!latestSensorLoading &&
                            <LatestSensorMonitor
                                latestSensorData={latestSensorData}
                                houses={houses}
                                setSelectedHouse={handleSetSelectedHouse}
                                selectedHouse={selectedHouse}
                                farmId={farmId}
                                isAdmin={isAdmin}
                            />
                        }
                    </Accordion.Body>
                </Accordion.Item>
            </Accordion>

            {/* 선택된 재배사 최신 센서 데이터 */}
            {isAccordionOpened === null && !latestSensorLoading && selectedHouse && (() => {
                const data = latestSensorData[selectedHouse.housId];
                if (!data) return null;
                return (
                    <LatestSensorSelected latestSensorData={data}
                        house={selectedHouse} />
                )
            })()}

            {/* 재배사 리스트 — 현재 숨김 (향후 사용 예정) */}
            {/*<HouseList
                selectedHouse={selectedHouse?.housId}
                authLvel={auth.userInfo.authLvel}
                houses={houses}
                setSelectedHouse={setSelectedHouse}
                farmId={farmId}
            />*/}

            {/* 탭 */}
            <Tabs id="custom-tabs" className="d-flex justify-content-end" activeKey={activeTab} onSelect={handleTabChange}>
                <Tab
                    eventKey="sensor"
                    title={
                        <>
                            <span className="d-none d-md-inline">센서 기록 조회</span>
                            <span className="d-inline d-md-none">센서</span>
                        </>
                    }
                >
                    <HouseSensorDashboard
                        sensorData={sensorData}
                        startDate={startDate}
                        setStartDate={handleSetStartDate}
                        endDate={endDate}
                        setEndDate={handleSetEndDate}
                        fetchSensorData={refetchSensor}
                        loading={sensorLoading}
                    />
                </Tab>

                <Tab
                    eventKey="relay"
                    title={
                        <>
                            <span className="d-none d-md-inline">릴레이 현황 및 조작</span>
                            <span className="d-inline d-md-none">릴레이</span>
                        </>
                    }
                >
                    {selectedHouse &&
                        <RelayDashboard farmId={farmId} house={selectedHouse} setSelectedHouse={handleSetSelectedHouse} />
                    }
                </Tab>

                <Tab
                    eventKey="memo"
                    title={
                        <>
                            <span className="d-none d-md-inline">재배사 메모</span>
                            <span className="d-inline d-md-none">메모</span>
                        </>
                    }
                >
                    {/* 메모 컴포넌트 */}
                    {selectedHouse &&
                        <MemoDashboard farmId={farmId} houseId={selectedHouse.housId}
                                       houses={allHouses} farmName={farm?.farmName} />
                    }
                </Tab>

                <Tab
                    eventKey="sensorSetting"
                    title={
                        <>
                            <span className="d-none d-md-inline">설정</span>
                            <span className="d-inline d-md-none">설정</span>
                        </>
                    }
                >
                    {selectedHouse &&
                        <SensorSettingDashboard farmId={farmId} selectedHouse={selectedHouse.housId} />
                    }
                </Tab>

                <Tab
                    eventKey="camera"
                    title={
                        <>
                            <span className="d-none d-md-inline">카메라</span>
                            <span className="d-inline d-md-none">카메라</span>
                        </>
                    }
                >
                    {selectedHouse && (
                        <CameraView
                            farmId={farmId}
                            houseId={selectedHouse.housId}
                            houses={houses}
                        />
                    )}
                </Tab>
            </Tabs>
        </Container>
    )

}
