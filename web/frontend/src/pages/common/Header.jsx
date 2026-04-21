import React from "react";
import {Navbar, Container, Nav} from "react-bootstrap";
import {Link} from "react-router-dom";
import AdminNavLink from "./navLinks/AdminNavLink.jsx";
import CommonNavLink from "./navLinks/CommonNavLink.jsx";
import GuestNavLink from "./navLinks/GuestNavLink.jsx";
import {useSelector} from "react-redux";

// [2026-05-01] 모바일 반응형 보완 — expand="lg" + Navbar.Toggle/Collapse 적용.
//   기존 구조는 데스크톱 가로 배치만 가정하여 태블릿·스마트폰에서 메뉴가 좁게
//   squeeze 됨. lg 미만 화면에서 햄버거 토글로 펼치는 표준 react-bootstrap 패턴.
export default function Header() {
    const auth = useSelector(state => state.auth);
    const selectedFarm = useSelector(state => state.auth.selectedFarm);
    const brandName = (auth.token && selectedFarm?.farmName) ? selectedFarm.farmName : "Jayeondeule";

    return (
        <Navbar bg="light" variant="white" fixed="top" expand="lg">
            <Container>
                <Navbar.Brand as={Link} to="/">{brandName}</Navbar.Brand>
                <Navbar.Toggle aria-controls="main-navbar" />
                <Navbar.Collapse id="main-navbar">
                    {auth.token != null && (
                        <Nav className="me-auto">
                            <Nav.Link as={Link} to="/ai-chat" style={{fontWeight: "bold"}}>AI 채팅</Nav.Link>
                            {auth.userInfo?.authLvel === "ADMIN" && (
                                <Nav.Link href="#" onClick={(e) => { e.preventDefault(); window.open('http://lockers7.iptime.org:5100', 'shop_window'); }}
                                   style={{fontSize: "0.85rem", color: "#FF7043", fontWeight: "bold"}}>
                                    🛒 쇼핑몰
                                </Nav.Link>
                            )}
                        </Nav>
                    )}
                    {/* 페이지별 액션 버튼 슬롯 (AiChatPage에서 Portal로 RAG 버튼 렌더링) */}
                    <div id="header-actions" className="d-flex align-items-center gap-2 me-auto flex-wrap" />
                    <Nav className="ms-auto">
                        {auth.token != null ? (
                            <>
                                {auth.userInfo.authLvel === "ADMIN" && (
                                    <AdminNavLink/>
                                )}
                                <CommonNavLink/>
                            </>
                        ) : (
                            <>
                                <GuestNavLink/>
                            </>
                        )}
                    </Nav>
                </Navbar.Collapse>
            </Container>
        </Navbar>
    );
}
