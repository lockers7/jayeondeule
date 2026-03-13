// 우측 상단 농장명 드롭다운 메뉴
// 선택된 농장명 표시, 하위: 재배사 관리, 사용자 관리, 로그아웃
import React, { useEffect } from "react";
import { NavDropdown } from "react-bootstrap";
import { useDispatch, useSelector } from "react-redux";
import { Link, useNavigate } from "react-router-dom";
import { logout, setSelectedFarm } from "../../../store/auth/authSlice.js";
import { getMyFarm } from "../../../utils/farmUtil.js";

export default function CommonNavLink() {
    const dispatch = useDispatch();
    const navigate = useNavigate();
    const selectedFarm = useSelector((state) => state.auth.selectedFarm);

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

    const farmName = selectedFarm?.farmName || "농장";
    const farmId = selectedFarm?.farmId;

    return (
        <NavDropdown title={farmName} id="farm-nav-dropdown" align="end">
            {farmId != null && (
                <>
                    <NavDropdown.Item as={Link} to={`/farm-edit`}>
                        농장정보변경
                    </NavDropdown.Item>
                    <NavDropdown.Item as={Link} to={`/farm/${farmId}/house-management`}>
                        재배사 관리
                    </NavDropdown.Item>
                    <NavDropdown.Item as={Link} to={`/farm/${farmId}/user-management`}>
                        사용자 관리
                    </NavDropdown.Item>
                    <NavDropdown.Divider />
                </>
            )}
            <NavDropdown.Item onClick={handleLogout}>로그아웃</NavDropdown.Item>
        </NavDropdown>
    );
}
