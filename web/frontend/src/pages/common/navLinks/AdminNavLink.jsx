import React from "react";
import {Nav, NavDropdown} from "react-bootstrap";
import {Link} from "react-router-dom";
import {useSelector} from "react-redux";

export default function AdminNavLink() {
    const selectedFarm = useSelector(state => state.auth.selectedFarm);
    const farmId = selectedFarm?.farmId ?? null;

    return (
        <>
            <NavDropdown title="농장" id="admin-farm-dropdown">
                <NavDropdown.Item as={Link} to="/farm-register">농장 등록</NavDropdown.Item>
                <NavDropdown.Divider/>
                <NavDropdown.Item as={Link} to="/farm-edit">농장 관리</NavDropdown.Item>
                <NavDropdown.Divider/>
                <NavDropdown.Item as={Link} to="/farm-management">농장 목록</NavDropdown.Item>
            </NavDropdown>
            <Nav.Link as={Link} to={farmId != null ? `/farm/${farmId}/house-management` : "/farm-management"}>재배사관리</Nav.Link>
            <Nav.Link as={Link} to={farmId != null ? `/farm/${farmId}/user-management` : "/farm-management"}>사용자관리</Nav.Link>
            <Nav.Link as={Link} to="/prompt-management">프롬프트관리</Nav.Link>
            <Nav.Link as={Link} to="/rule-candidates">룰 후보</Nav.Link>
            <Nav.Link as={Link} to="/agent-history">Agent 이력</Nav.Link>
            <Nav.Link as={Link} to="/control-prompt-management">LLM 제어관리</Nav.Link>
        </>
    );
}
