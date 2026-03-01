import React from "react";
import {Card} from "react-bootstrap";

const fmt = (v, unit) => (v != null ? Math.round(v * 100) / 100 + unit : "-");

export default function LatestSensorSelected({latestSensorData, houseName}) {
    return (
        <>
            {latestSensorData && (
                <div style={{position: "relative", marginBottom: "1rem", marginTop: "2rem"}}>
                    {/* 카드 바깥 오른쪽 상단에 측정 시간 */}
                    <div style={{
                        position: "absolute",
                        top: "-1.5rem",
                        right: "0",
                        fontWeight: "bold",
                        fontSize: "0.9rem"
                    }}>
                        {new Date(latestSensorData.recdDttm).toLocaleString()}
                    </div>

                    {houseName && (
                        <div style={{
                            position: "absolute",
                            top: "-1.5rem",
                            left: "0",
                            fontWeight: "bold",
                            fontSize: "0.9rem"
                        }}>
                            {houseName}
                        </div>
                    )}

                    <Card className="p-3 mb-3"
                          style={{overflowX: "auto", minHeight: "100px", display: "flex", alignItems: "center", overflow: "hidden"}}>
                        <table className="table table-borderless mb-0 text-center" style={{minWidth: "300px"}}>
                            <thead>
                            <tr className="d-none d-md-table-row">
                                <th>실내 온도</th>
                                <th>실외 온도</th>
                                <th>실내 습도</th>
                                <th>실외 습도</th>
                                <th>CO2</th>
                                <th>수온</th>
                            </tr>
                            </thead>
                            <tbody>
                            {/* PC용 한 줄 */}
                            <tr className="d-none d-md-table-row">
                                <td>{fmt(latestSensorData.indrTprtValu, "℃")}</td>
                                <td>{fmt(latestSensorData.oudrTprtValu, "℃")}</td>
                                <td>{fmt(latestSensorData.indrHmdtValu, "%")}</td>
                                <td>{fmt(latestSensorData.oudrHmdtValu, "%")}</td>
                                <td>{fmt(latestSensorData.co2Valu, "ppm")}</td>
                                <td>{fmt(latestSensorData.watrTprtValu, "℃")}</td>
                            </tr>

                            {/* 모바일용 2열씩 3줄 */}
                            <tr className="d-md-none">
                                <td><b>실내 온도:</b> {fmt(latestSensorData.indrTprtValu, "℃")}</td>
                                <td><b>실외 온도:</b> {fmt(latestSensorData.oudrTprtValu, "℃")}</td>
                            </tr>
                            <tr className="d-md-none">
                                <td><b>실내 습도:</b> {fmt(latestSensorData.indrHmdtValu, "%")}</td>
                                <td><b>실외 습도:</b> {fmt(latestSensorData.oudrHmdtValu, "%")}</td>
                            </tr>
                            <tr className="d-md-none">
                                <td><b>CO2:</b> {fmt(latestSensorData.co2Valu, "ppm")}</td>
                                <td><b>수온:</b> {fmt(latestSensorData.watrTprtValu, "℃")}</td>
                            </tr>
                            </tbody>
                        </table>
                    </Card>
                </div>
            )}
        </>
    )
}