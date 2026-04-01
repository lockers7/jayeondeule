import React, {useEffect, useRef} from "react";
import axios from "axios";
import LatestSensorItem from "./LatestSensorItem.jsx";

const SENSOR_TIMEOUT_SEC = 30; // 30초 이상 데이터 미수신 시 에러

// 서버-PC 시간 차이 (ms). 서버시각 = new Date().getTime() + _serverTimeOffset
let _serverTimeOffset = 0;
let _serverTimeLoaded = false;

async function loadServerTimeOffset() {
    if (_serverTimeLoaded) return;
    try {
        const res = await axios.get("/ai-api/api/v1/rpi/server-time");
        const serverTime = new Date(res.data.time).getTime();
        _serverTimeOffset = serverTime - Date.now();
        _serverTimeLoaded = true;
    } catch {}
}

function getServerNow() {
    return new Date(Date.now() + _serverTimeOffset);
}

// 비프음 (AudioContext 재사용)
let _beepCtx = null;

function playAlertBeep() {
    try {
        if (!_beepCtx || _beepCtx.state === "closed") {
            _beepCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (_beepCtx.state === "suspended") _beepCtx.resume();

        // 2회 비프
        [0, 0.25].forEach((delay) => {
            const osc = _beepCtx.createOscillator();
            const gain = _beepCtx.createGain();
            osc.connect(gain);
            gain.connect(_beepCtx.destination);
            osc.type = "square";
            osc.frequency.value = 1200;
            gain.gain.value = 0.5;
            osc.start(_beepCtx.currentTime + delay);
            osc.stop(_beepCtx.currentTime + delay + 0.15);
        });
    } catch {}
}

// AudioContext 활성화 (브라우저 자동재생 정책 해제)
if (typeof document !== "undefined") {
    const unlock = () => {
        if (!_beepCtx) _beepCtx = new (window.AudioContext || window.webkitAudioContext)();
        if (_beepCtx.state === "suspended") _beepCtx.resume();
    };
    document.addEventListener("click", unlock);
    document.addEventListener("keydown", unlock);
}

export { playAlertBeep, SENSOR_TIMEOUT_SEC, getServerNow };

export default function LatestSensorMonitor({latestSensorData, houses, setSelectedHouse, selectedHouse, farmId, isAdmin}) {
    const scrollRef = useRef(null);

    // 서버 시각 offset 로드 (1회)
    useEffect(() => { loadServerTimeOffset(); }, []);

    // 스크롤 스타일
    useEffect(() => {
        const el = scrollRef.current;
        if (!el) return;
        let timeout;
        const handleScroll = () => {
            el.classList.add("scrolling");
            clearTimeout(timeout);
            timeout = setTimeout(() => el.classList.remove("scrolling"), 1000);
        };
        el.addEventListener("scroll", handleScroll);
        return () => el.removeEventListener("scroll", handleScroll);
    }, []);

    // 3초마다 갱신되는 latestSensorData 감시
    // DB의 기록일시(recdDttm)와 현재 시각을 직접 비교하여 즉시 에러 판정
    const staleHouseIds = new Set();

    if (latestSensorData && houses) {
        const now = getServerNow();
        for (const house of houses) {
            if (house.housId === 0) continue;
            const sensor = latestSensorData[house.housId];
            if (!sensor || !sensor.recdDttm) {
                staleHouseIds.add(house.housId);
            } else {
                const ageSec = (now - new Date(sensor.recdDttm)) / 1000;
                if (ageSec > SENSOR_TIMEOUT_SEC) {
                    staleHouseIds.add(house.housId);
                }
            }
        }
    }

    const hasError = staleHouseIds.size > 0;

    // 에러 시 비프음 (첫 데이터 갱신은 건너뜀 — 화면 이동 시 즉시 비프 방지)
    const renderCountRef = useRef(0);
    useEffect(() => {
        renderCountRef.current += 1;
        if (renderCountRef.current <= 1) return; // 첫 데이터 갱신은 비프 안 울림
        if (hasError) {
            playAlertBeep();
        }
    }, [latestSensorData]); // eslint-disable-line react-hooks/exhaustive-deps

    if (!latestSensorData || !houses) return null;

    return (
        <>
            {latestSensorData && (
                <div style={{position: "relative", overflowX: "auto"}} ref={scrollRef}>
                    <table className="table table-bordered mb-0 text-center sensor-table"
                           style={{minWidth: "800px", tableLayout: "auto", verticalAlign: "middle",
                                   borderCollapse: "collapse", fontSize: "150%"}}>
                        <thead>
                        <tr>
                            <th>재배사</th>
                            <th>생육단계</th>
                            <th>운용방식</th>
                            <th>실내 온도</th>
                            <th>실외 온도</th>
                            <th>실내 습도</th>
                            <th>실외 습도</th>
                            <th>CO2</th>
                            <th>수온</th>
                            <th>기록일</th>
                            {isAdmin && <th>RPi 관리</th>}
                        </tr>
                        </thead>
                        <tbody>
                        {houses.map((house) => {
                            const sensorData = latestSensorData[house.housId] || null;
                            const isStale = staleHouseIds.has(house.housId);
                            return (
                                <LatestSensorItem
                                    key={house.housId}
                                    latestSensorData={sensorData}
                                    house={house}
                                    setSelectedHouse={setSelectedHouse}
                                    selectedHouse={selectedHouse}
                                    farmId={farmId}
                                    isAdmin={isAdmin}
                                    isStale={isStale}
                                />
                            )
                        })}
                        </tbody>
                    </table>
                </div>
            )}
        </>
    )
}
