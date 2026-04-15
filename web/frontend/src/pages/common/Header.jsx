import React from "react";
import {Navbar, Container, Nav} from "react-bootstrap";
import {Link} from "react-router-dom";
import AdminNavLink from "./navLinks/AdminNavLink.jsx";
import CommonNavLink from "./navLinks/CommonNavLink.jsx";
import GuestNavLink from "./navLinks/GuestNavLink.jsx";
import {useSelector} from "react-redux";

export default function Header() {
    const auth = useSelector(state => state.auth);
    const selectedFarm = useSelector(state => state.auth.selectedFarm);
    const brandName = (auth.token && selectedFarm?.farmName) ? selectedFarm.farmName : "Jayeondeule";

    return (
        <Navbar bg="light" variant="white" fixed="top">
            <Container>
                <Navbar.Brand as={Link} to="/">{brandName}</Navbar.Brand>
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
                <div id="header-actions" style={{display: "flex", gap: "8px", alignItems: "center", marginRight: "auto"}} />
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
            </Container>
        </Navbar>
    );
}