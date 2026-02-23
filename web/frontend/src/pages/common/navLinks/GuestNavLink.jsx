import React from "react";
import {Nav} from "react-bootstrap";

export default function GuestNavLink() {
    return (
        <>
            <Nav.Link href="/login">로그인</Nav.Link>
            <Nav.Link href="/register">관리자등록</Nav.Link>
        </>
    )
}