// 우측 상단 고정 메뉴: [농장관리(FARM_ADMIN=농장관리자)] | 재배사관리 | 사용자관리 | 로그아웃
import React, { useEffect } from "react";
import { Nav } from "react-bootstrap";
import { useDispatch, useSelector } from "react-redux";
import { Link, useNavigate } from "react-router-dom";
import { logout, setSelectedFarm } from "../../../store/auth/authSlice.js";
import { getMyFarm } from "../../../utils/farmUtil.js";

export default function CommonNavLink() {
    const dispatch = useDispatch();
    const navigate = useNavigate();
    const selectedFarm = useSelector((state) => state.auth.selectedFarm);
    const userInfo = useSelector((state) => state.auth.userInfo);

    // 기본 농장 조회
    useEffect(() => {
        const fetchData = async () => {
            try {
                if (!selectedFarm) {
                    const farmRes = await getMyFarm();
                    if (farmRes.data) {
                        dispatch(setSelectedFarm({
                            farmId: farmRes.data.farmId,
                            farmName: farmRes.data.farmName,
                        }));
                    }
                }
            } catch (err) {
                console.error(err);
            }
        };
        fetchData();
    }, []);

    const handleLogout = (e) => {
        e.preventDefault();
        try {
            dispatch(logout());
            navigate("/login");
        } catch (err) {
            console.error(err);
        }
    };

    const farmId = selectedFarm?.farmId;
    const isFarmAdmin = userInfo?.authLvel === "FARM_ADMIN";

    return (
        <>
            {isFarmAdmin && farmId != null && (
                <>
                    <Nav.Link as={Link} to="/farm-edit">
                        농장관리
                    </Nav.Link>
                    <Nav.Link as={Link} to={`/farm/${farmId}/house-management`}>
                        재배사관리
                    </Nav.Link>
                    <Nav.Link as={Link} to={`/farm/${farmId}/user-management`}>
                        사용자관리
                    </Nav.Link>
                </>
            )}
            <Nav.Link onClick={handleLogout} className="ms-2" style={{cursor: "pointer"}}>
                로그아웃
            </Nav.Link>
        </>
    );
}
