import React from "react";
import {Navigate, Route, Routes} from "react-router-dom";
import PrivateRoute from "../pages/common/route/PrivateRoute.jsx";
import AdminRoute from "../pages/common/route/AdminRoute.jsx";
import ErrorPage from "../pages/common/ErrorPage.jsx";
import MyPage from "../pages/user/MyPage.jsx";
import PasswordChangePage from "../pages/user/PasswordChangePage.jsx";
import FarmMonitoringPage from "../pages/farm/FarmMonitoringPage.jsx";
import SensorSettingDashboard from "../components/sensor/SensorSettingDashboard.jsx";
import AiChatPage from "../pages/ai/AiChatPage.jsx";
import StockTradingPage from "../pages/ai/StockTradingPage.jsx";
import HouseManagementPage from "../pages/house/HouseManagementPage.jsx";
import UserManagementPage from "../pages/user/UserManagementPage.jsx";
import FarmEditPage from "../pages/farm/FarmEditPage.jsx";
import HouseRegisterPage from "../pages/house/HouseRegisterPage.jsx";
import HousePatchPage from "../pages/house/HousePatchPage.jsx";
import FarmPatchPage from "../pages/farm/FarmPatchPage.jsx";

export default function CommonRoutes() {
    return (
        <Routes>
            <Route
                path="/"
                element={
                    <PrivateRoute>
                        <FarmMonitoringPage/>
                    </PrivateRoute>
                }
            />
            <Route
                path="/farm-edit"
                element={
                    <PrivateRoute>
                        <FarmEditPage/>
                    </PrivateRoute>
                }
            />
            <Route
                path="/ai-chat"
                element={
                    <PrivateRoute>
                        <AiChatPage/>
                    </PrivateRoute>
                }
            />
            <Route
                path="/stock-trading"
                element={
                    <AdminRoute>
                        <StockTradingPage/>
                    </AdminRoute>
                }
            />
            <Route
                path="/mypage"
                element={
                    <PrivateRoute>
                        <MyPage/>
                    </PrivateRoute>
                }
            />
            <Route
                path="/mypage/password"
                element={
                    <PrivateRoute>
                        <PasswordChangePage/>
                    </PrivateRoute>
                }
            />
            <Route
                path="/farm/:farmId/monitor"
                element={
                    <PrivateRoute>
                        <FarmMonitoringPage/>
                    </PrivateRoute>
                }
            />
            <Route
                path="/farm/:farmId/edit"
                element={
                    <PrivateRoute>
                        <FarmPatchPage/>
                    </PrivateRoute>
                }
            />
            <Route
                path="/farm/:farmId/house-management"
                element={
                    <PrivateRoute>
                        <HouseManagementPage/>
                    </PrivateRoute>
                }
            />
            <Route
                path="/farm/:farmId/house-register"
                element={
                    <PrivateRoute>
                        <HouseRegisterPage/>
                    </PrivateRoute>
                }
            />
            <Route
                path="/farm/:farmId/house/:houseId/edit"
                element={
                    <PrivateRoute>
                        <HousePatchPage/>
                    </PrivateRoute>
                }
            />
            <Route
                path="/farm/:farmId/user-management"
                element={
                    <PrivateRoute>
                        <UserManagementPage/>
                    </PrivateRoute>
                }
            />
            <Route path="/login" element={<Navigate to="/" replace/>}/>
            <Route path="*" element={<ErrorPage/>}/>
        </Routes>
    )
}