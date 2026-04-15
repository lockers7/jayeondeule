import { createSlice } from "@reduxjs/toolkit";

const authSlice = createSlice({
    name: "auth",
    initialState: { token: null, userInfo: null, selectedFarm: null },
    reducers: {
        loginSuccess: (state, action) => {
            state.token = action.payload.token;
            state.userInfo = action.payload.userInfo;
            localStorage.setItem("token", action.payload.token);
        },
        logout: (state) => {
            state.token = null;
            state.userInfo = null;
            state.selectedFarm = null;
            localStorage.removeItem("token");
        },
        restoreSession: (state) => {
            const token = localStorage.getItem("token");
            if (token) {
                state.token = token;
            }
        },
        setUser: (state, action) => {
            state.token = localStorage.getItem("token");
            state.userInfo = action.payload;
        },
        // 선택된 농장 정보 저장 (farmId, farmName)
        setSelectedFarm: (state, action) => {
            state.selectedFarm = action.payload;
        },
    }
});

export const { loginSuccess, logout, restoreSession, setUser, setSelectedFarm } = authSlice.actions;
export default authSlice.reducer;
