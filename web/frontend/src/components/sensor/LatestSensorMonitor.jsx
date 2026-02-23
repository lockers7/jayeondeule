import React, {useEffect, useRef} from "react";
import LatestSensorItem from "./LatestSensorItem.jsx";

export default function LatestSensorMonitor({latestSensorData, houses, setSelectedHouse, selectedHouse, farmId}) {
    const scrollRef = useRef(null);

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

    if (!latestSensorData || !houses) return null;

    const renderSensorItems = () => {
        return Object.entries(latestSensorData).map(([key, value]) => {
            const house = houses.find(h => h.housId === Number(key));
            return (
                <LatestSensorItem
                    key={key}
                    latestSensorData={value}
                    house={house}
                    setSelectedHouse={setSelectedHouse}
                    selectedHouse={selectedHouse}
                    farmId={farmId}
                />
            )
        })
    };

    return (
        <>
            {latestSensorData && (
                <div style={{position: "relative", overflowX: "auto"}}
                     ref={scrollRef}>
                    <table className="table table-bordered mb-0 text-center sensor-table"
                           style={{
                               minWidth: "800px",
                               tableLayout: "auto",
                               verticalAlign: "middle",
                               borderCollapse: "collapse",
                               fontSize: "150%"
                           }}>
                        <thead>
                        <tr>
                            <th>재배사</th>
                            <th>운용방식</th>
                            <th>실내 온도</th>
                            <th>실외 온도</th>
                            <th>실내 습도</th>
                            <th>실외 습도</th>
                            <th>CO2</th>
                            <th>수온</th>
                            <th>기록일</th>
                        </tr>
                        </thead>
                        <tbody>
                        {renderSensorItems()}
                        </tbody>
                    </table>
                </div>
            )}
        </>
    )
}