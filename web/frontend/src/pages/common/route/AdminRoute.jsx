import React from "react";
import {Navigate} from "react-router-dom";
import {useSelector} from "react-redux";

// 시스템관리자(ADMIN) 전용 라우트 가드.
//   · 미로그인 → /login
//   · 로그인했으나 ADMIN 아님(FARM_ADMIN·SYS_MONITOR·FARM_MONITOR 등) → /ai-chat 으로 이동(접근 차단)
// 버튼 숨김(UI)만으로는 URL 직접 접근을 못 막으므로 라우트 레벨에서도 차단(F3).
export default function AdminRoute({ children }) {
    const auth = useSelector(state => state.auth);
    if (!auth.token) {
        return <Navigate to="/login" replace />;
    }
    if (auth.userInfo?.authLvel !== "ADMIN") {
        return <Navigate to="/ai-chat" replace />;
    }
    return children;
}
