import React from "react";
import {Navigate, Route, Routes} from "react-router-dom";
import PrivateRoute from "../pages/common/route/PrivateRoute.jsx";
import FarmManagementPage from "../pages/farm/FarmManagementPage.jsx";
import FarmRegisterPage from "../pages/farm/FarmRegisterPage.jsx";
import CommonRoutes from "./CommonRoutes.jsx";
import FarmPatchPage from "../pages/farm/FarmPatchPage.jsx";
import FarmEditPage from "../pages/farm/FarmEditPage.jsx";
import HouseRegisterPage from "../pages/house/HouseRegisterPage.jsx";
import HousePatchPage from "../pages/house/HousePatchPage.jsx";
import HouseManagementPage from "../pages/house/HouseManagementPage.jsx";
import UserManagementPage from "../pages/user/UserManagementPage.jsx";

export default function AdminRoutes() {
    return ( //"/assign-farm-roles"
        <Routes>
            <Route
                path="/"
                element={<Navigate to="/farm-management" replace/>
                }
            />
            <Route
                path="/farm-management"
                element={
                    <PrivateRoute>
                        <FarmManagementPage/>
                    </PrivateRoute>
                }
            />
            <Route
                path="/farm-register"
                element={
                    <PrivateRoute>
                        <FarmRegisterPage/>
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
                path="/farm/:farmId/edit"
                element={
                    <PrivateRoute>
                        <FarmPatchPage/>
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
                path="/farm/:farmId/house-management"
                element={
                    <PrivateRoute>
                        <HouseManagementPage/>
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
            <Route path="/login" element={<Navigate to="/farm-management" replace/>}/>
            <Route path="*" element={<CommonRoutes/>}/>
        </Routes>
    )
}