import React, {useEffect, useState} from "react";
import {Nav, NavDropdown} from "react-bootstrap";
import {Link} from "react-router-dom";
import {getFarmList} from "../../../utils/farmUtil.js";

export default function AdminNavLink() {
    const [farmId, setFarmId] = useState(null);

    useEffect(() => {
        getFarmList(0, 1)
            .then((res) => {
                const first = res.data?.content?.[0];
                if (first?.farmId != null) setFarmId(first.farmId);
            })
            .catch(() => {});
    }, []);

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
        </>
    );
}
