// 재배사 관리 페이지 — farmhouse_m_info 전체 필드 CRUD
// 코드 테이블(crop_kind, crop_lvel, ctrl_type) 콤보박스 적용
// admin: 모든 재배사 수정 가능(소속농장 변경 포함), 비admin: 자기 농장 재배사만
import React, {useEffect, useState} from "react";
import {Button, Container, Form, Spinner, Table, Row, Col, Card} from "react-bootstrap";
import {useParams} from "react-router-dom";
import {useSelector} from "react-redux";
import {getHouseList, patchHouse, deleteHouse, registerHouse, restoreHouse} from "../../utils/houseUtil.js";
import {getMyFarm, getFarmList} from "../../utils/farmUtil.js";
import AlertModal from "../../components/common/AlertModal.jsx";

// 코드 테이블 값 (code_m_info 기반)
const CROP_KIND_OPTIONS = [{value: "10", label: "상황버섯"}];
const CROP_LVEL_OPTIONS = [
    {value: "1", label: "발아기"},
    {value: "2", label: "생육기"},
    {value: "3", label: "수확기"},
    {value: "4", label: "휴지기"},
];
const CTRL_TYPE_OPTIONS = [
    {value: "algorithm", label: "알고리즘"},
    {value: "ai", label: "AI"},
];

export default function HouseManagementPage() {
    const {farmId: urlFarmId} = useParams();
    const userInfo = useSelector((state) => state.auth.userInfo);
    const isAdmin = userInfo?.authLvel === "ADMIN";
    const canManage = isAdmin || userInfo?.authLvel === "FARM_ADMIN";

    const [activeFarmId, setActiveFarmId] = useState(null);
    const [houses, setHouses] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [modalMsg, setModalMsg] = useState({title: "", body: "", variant: "success"});
    const [showDeleteModal, setShowDeleteModal] = useState(false);
    const [deleteTarget, setDeleteTarget] = useState(null);

    // 수정 폼
    const [editId, setEditId] = useState(null);
    const [editForm, setEditForm] = useState({});

    // 신규 등록 폼
    const [showRegister, setShowRegister] = useState(false);
    const [newForm, setNewForm] = useState({
        housName: "", cropKind: "10", cropLvel: "2", ctrlType: "algorithm",
        snsrRfrsItvl: "3", mnulCtrlFlag: false, rfrsFlag: false,
    });

    // admin용 농장 리스트 (등록시 농장 선택)
    const [farmList, setFarmList] = useState([]);
    const [registerFarmId, setRegisterFarmId] = useState("");

    // 비admin: 자기 소속 농장 ID, admin: URL farmId
    useEffect(() => {
        const resolveFarmId = async () => {
            if (isAdmin) {
                setActiveFarmId(urlFarmId);
            } else {
                try {
                    const res = await getMyFarm();
                    setActiveFarmId(res.data?.farmId ? String(res.data.farmId) : null);
                } catch (err) {
                    console.error(err);
                    setLoading(false);
                }
            }
        };
        resolveFarmId();
    }, [urlFarmId, isAdmin]);

    // admin: 농장 리스트 조회 (등록 폼에서 농장 선택용)
    useEffect(() => {
        if (!isAdmin) return;
        const fetchFarms = async () => {
            try {
                const res = await getFarmList(0, 100);
                const list = res.data?.content || res.data || [];
                setFarmList(list);
                if (list.length > 0) setRegisterFarmId(String(list[0].farmId));
            } catch (err) {
                console.error("농장 리스트 조회 실패:", err);
            }
        };
        fetchFarms();
    }, [isAdmin]);

    const fetchHouses = async () => {
        if (!activeFarmId) return;
        try {
            const res = await getHouseList({farmId: activeFarmId});
            setHouses(res.data || []);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (activeFarmId) fetchHouses();
    }, [activeFarmId]);

    // 수정 시작 — farmhouse_m_info 전체 필드
    const startEdit = (house) => {
        setEditId(house.housId);
        setEditForm({
            farmId: activeFarmId,
            housId: house.housId,
            housName: house.housName || "",
            cropKind: house.cropKind || "10",
            cropLvel: String(house.cropLvel ?? 2),
            ctrlType: house.ctrlType || "algorithm",
            snsrRfrsItvl: house.snsrRfrsItvl || "3",
            mnulCtrlFlag: house.mnulCtrlFlag ?? false,
            rfrsFlag: house.rfrsFlag ?? false,
        });
    };

    const cancelEdit = () => setEditId(null);

    const handleEditChange = (e) => {
        const {name, value, type, checked} = e.target;
        setEditForm({...editForm, [name]: type === "checkbox" ? checked : value});
    };

    const saveEdit = async () => {
        try {
            await patchHouse(editForm);
            setEditId(null);
            setModalMsg({title: "알림", body: "재배사 정보가 수정되었습니다.", variant: "success"});
            setShowModal(true);
            fetchHouses();
        } catch (err) {
            setModalMsg({title: "오류", body: "재배사 수정에 실패했습니다.", variant: "danger"});
            setShowModal(true);
        }
    };

    const confirmDelete = (house) => {
        setDeleteTarget(house);
        setShowDeleteModal(true);
    };

    const handleDelete = async () => {
        try {
            await deleteHouse(activeFarmId, deleteTarget.housId);
            setShowDeleteModal(false);
            setModalMsg({title: "알림", body: "재배사가 삭제되었습니다.", variant: "success"});
            setShowModal(true);
            fetchHouses();
        } catch (err) {
            setShowDeleteModal(false);
            setModalMsg({title: "오류", body: "재배사 삭제에 실패했습니다.", variant: "danger"});
            setShowModal(true);
        }
    };

    // 복원 실행 (관리자 전용)
    const handleRestore = async (houseId) => {
        try {
            await restoreHouse(activeFarmId, houseId);
            setModalMsg({title: "알림", body: "재배사가 복원되었습니다.", variant: "success"});
            setShowModal(true);
            fetchHouses();
        } catch (err) {
            setModalMsg({title: "오류", body: "재배사 복원에 실패했습니다.", variant: "danger"});
            setShowModal(true);
        }
    };

    const handleRegister = async (e) => {
        e.preventDefault();
        try {
            const targetFarmId = isAdmin ? registerFarmId : activeFarmId;
            await registerHouse({farmId: targetFarmId, ...newForm});
            setShowRegister(false);
            setNewForm({housName: "", cropKind: "10", cropLvel: "2", ctrlType: "algorithm",
                snsrRfrsItvl: "3", mnulCtrlFlag: false, rfrsFlag: false});
            setModalMsg({title: "알림", body: "재배사가 등록되었습니다.", variant: "success"});
            setShowModal(true);
            fetchHouses();
        } catch (err) {
            setModalMsg({title: "오류", body: "재배사 등록에 실패했습니다.", variant: "danger"});
            setShowModal(true);
        }
    };

    const getLabelByValue = (options, value) =>
        options.find((o) => String(o.value) === String(value))?.label || value;

    if (loading) {
        return (
            <Container className="d-flex justify-content-center align-items-center flex-grow-1">
                <Spinner animation="border" variant="success"/>
            </Container>
        );
    }

    return (
        <Container className="mt-2 pt-3">
            <div className="d-flex justify-content-between align-items-center mb-3">
                <h4>재배사 관리</h4>
                {canManage && (
                    <Button variant="success" size="sm" onClick={() => setShowRegister(!showRegister)}>
                        {showRegister ? "취소" : "재배사 등록"}
                    </Button>
                )}
            </div>

            {/* 신규 등록 폼 — 전체 필드 (테이블 형태) */}
            {showRegister && (
                <Form onSubmit={handleRegister}>
                    <div className="mb-3" style={{border: "2px solid #198754", borderRadius: "6px", overflow: "hidden"}}>
                        <div className="d-flex justify-content-between align-items-center px-3 py-2"
                             style={{backgroundColor: "#198754", color: "#fff"}}>
                            <span className="fw-bold">재배사 등록</span>
                            <div>
                                <Button size="sm" variant="light" className="me-1" type="submit">등록</Button>
                                <Button size="sm" variant="outline-light"
                                        onClick={() => setShowRegister(false)}>취소</Button>
                            </div>
                        </div>
                        <table className="table table-bordered mb-0" style={{fontSize: "0.875rem"}}>
                            <tbody>
                            {isAdmin && (
                                <tr>
                                    <th style={{backgroundColor: "#e9ecef", width: "14%"}} className="text-center align-middle">소속농장</th>
                                    <td colSpan={5}>
                                        <Form.Select size="sm" value={registerFarmId}
                                                     onChange={(e) => setRegisterFarmId(e.target.value)}>
                                            {farmList.map((farm) => (
                                                <option key={farm.farmId} value={String(farm.farmId)}>
                                                    {farm.farmName} (ID: {farm.farmId})
                                                </option>
                                            ))}
                                        </Form.Select>
                                    </td>
                                </tr>
                            )}
                            <tr>
                                <th style={{backgroundColor: "#e9ecef", width: "14%"}} className="text-center align-middle">재배사명</th>
                                <td style={{width: "19%"}}>
                                    <Form.Control size="sm" value={newForm.housName}
                                                  onChange={(e) => setNewForm({...newForm, housName: e.target.value})}
                                                  placeholder="재배사명" required/>
                                </td>
                                <th style={{backgroundColor: "#e9ecef", width: "14%"}} className="text-center align-middle">작물</th>
                                <td style={{width: "19%"}}>
                                    <Form.Select size="sm" value={newForm.cropKind}
                                                 onChange={(e) => setNewForm({...newForm, cropKind: e.target.value})}>
                                        {CROP_KIND_OPTIONS.map((o) =>
                                            <option key={o.value} value={o.value}>{o.label}</option>)}
                                    </Form.Select>
                                </td>
                                <th style={{backgroundColor: "#e9ecef", width: "14%"}} className="text-center align-middle">생육단계</th>
                                <td style={{width: "20%"}}>
                                    <Form.Select size="sm" value={newForm.cropLvel}
                                                 onChange={(e) => setNewForm({...newForm, cropLvel: e.target.value})}>
                                        {CROP_LVEL_OPTIONS.map((o) =>
                                            <option key={o.value} value={o.value}>{o.label}</option>)}
                                    </Form.Select>
                                </td>
                            </tr>
                            <tr>
                                <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">제어유형</th>
                                <td>
                                    <Form.Select size="sm" value={newForm.ctrlType}
                                                 onChange={(e) => setNewForm({...newForm, ctrlType: e.target.value})}>
                                        {CTRL_TYPE_OPTIONS.map((o) =>
                                            <option key={o.value} value={o.value}>{o.label}</option>)}
                                    </Form.Select>
                                </td>
                                <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">센서간격(초)</th>
                                <td>
                                    <Form.Control size="sm" value={newForm.snsrRfrsItvl}
                                                  onChange={(e) => setNewForm({...newForm, snsrRfrsItvl: e.target.value})}
                                                  type="number" min="1"/>
                                </td>
                                <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">제어및주기방법</th>
                                <td>
                                    <div className="d-flex gap-3 align-items-center">
                                        <Form.Check type="switch" id="reg-mnulCtrlFlag" label="수동제어"
                                                    checked={newForm.mnulCtrlFlag}
                                                    onChange={(e) => setNewForm({...newForm, mnulCtrlFlag: e.target.checked})}/>
                                        <Form.Check type="switch" id="reg-rfrsFlag" label="갱신"
                                                    checked={newForm.rfrsFlag}
                                                    onChange={(e) => setNewForm({...newForm, rfrsFlag: e.target.checked})}/>
                                    </div>
                                </td>
                            </tr>
                            </tbody>
                        </table>
                    </div>
                </Form>
            )}

            {/* 수정 폼 — farmhouse_m_info 전체 필드 (테이블 형태) */}
            {editId != null && (
                <div className="mb-3" style={{border: "2px solid #198754", borderRadius: "6px", overflow: "hidden"}}>
                    <div className="d-flex justify-content-between align-items-center px-3 py-2"
                         style={{backgroundColor: "#198754", color: "#fff"}}>
                        <span className="fw-bold">재배사 수정 (ID: {editForm.housId})</span>
                        <div>
                            <Button size="sm" variant="light" className="me-1" onClick={saveEdit}>저장</Button>
                            <Button size="sm" variant="outline-light" onClick={cancelEdit}>취소</Button>
                        </div>
                    </div>
                    <table className="table table-bordered mb-0" style={{fontSize: "0.875rem"}}>
                        <tbody>
                        <tr>
                            <th style={{backgroundColor: "#e9ecef", width: "14%"}} className="text-center align-middle">재배사명</th>
                            <td style={{width: "19%"}}>
                                <Form.Control size="sm" name="housName" value={editForm.housName}
                                              onChange={handleEditChange}/>
                            </td>
                            <th style={{backgroundColor: "#e9ecef", width: "14%"}} className="text-center align-middle">작물</th>
                            <td style={{width: "19%"}}>
                                <Form.Select size="sm" name="cropKind" value={editForm.cropKind}
                                             onChange={handleEditChange}>
                                    {CROP_KIND_OPTIONS.map((o) =>
                                        <option key={o.value} value={o.value}>{o.label}</option>)}
                                </Form.Select>
                            </td>
                            <th style={{backgroundColor: "#e9ecef", width: "14%"}} className="text-center align-middle">생육단계</th>
                            <td style={{width: "20%"}}>
                                <Form.Select size="sm" name="cropLvel" value={editForm.cropLvel}
                                             onChange={handleEditChange}>
                                    {CROP_LVEL_OPTIONS.map((o) =>
                                        <option key={o.value} value={o.value}>{o.label}</option>)}
                                </Form.Select>
                            </td>
                        </tr>
                        <tr>
                            <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">제어유형</th>
                            <td>
                                <Form.Select size="sm" name="ctrlType" value={editForm.ctrlType}
                                             onChange={handleEditChange}>
                                    {CTRL_TYPE_OPTIONS.map((o) =>
                                        <option key={o.value} value={o.value}>{o.label}</option>)}
                                </Form.Select>
                            </td>
                            <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">센서간격(초)</th>
                            <td>
                                <Form.Control size="sm" name="snsrRfrsItvl" value={editForm.snsrRfrsItvl}
                                              onChange={handleEditChange} type="number" min="1"/>
                            </td>
                            <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">제어및주기방법</th>
                            <td>
                                <div className="d-flex gap-3 align-items-center">
                                    <Form.Check type="switch" id="mnulCtrlFlag" label="수동제어"
                                                name="mnulCtrlFlag" checked={editForm.mnulCtrlFlag}
                                                onChange={handleEditChange}/>
                                    <Form.Check type="switch" id="rfrsFlag" label="갱신"
                                                name="rfrsFlag" checked={editForm.rfrsFlag}
                                                onChange={handleEditChange}/>
                                </div>
                            </td>
                        </tr>
                        </tbody>
                    </table>
                </div>
            )}

            <Table striped bordered hover responsive size="sm">
                <thead>
                <tr>
                    {isAdmin && <th>상태</th>}
                    <th>ID</th>
                    <th>재배사명</th>
                    <th>작물</th>
                    <th>생육단계</th>
                    <th>제어유형</th>
                    <th>센서간격</th>
                    <th>수동제어</th>
                    <th>갱신</th>
                    <th>등록일</th>
                    {canManage && <th>관리</th>}
                </tr>
                </thead>
                <tbody>
                {houses.map((house) => {
                    const isDeleted = house.dlteYn === "Y";
                    return (
                        <tr key={house.housId}
                            className={editId === house.housId ? "table-warning" : isDeleted ? "table-secondary" : ""}>
                            {isAdmin && (
                                <td className="text-center">
                                    <span className={`badge bg-${isDeleted ? "danger" : "success"}`}>
                                        {isDeleted ? "삭제" : "정상"}
                                    </span>
                                </td>
                            )}
                            <td>{house.housId}</td>
                            <td>{house.housName}</td>
                            <td>{getLabelByValue(CROP_KIND_OPTIONS, house.cropKind)}</td>
                            <td>{getLabelByValue(CROP_LVEL_OPTIONS, house.cropLvel)}</td>
                            <td>{getLabelByValue(CTRL_TYPE_OPTIONS, house.ctrlType)}</td>
                            <td>{house.snsrRfrsItvl}초</td>
                            <td>{house.mnulCtrlFlag ? "ON" : "OFF"}</td>
                            <td>{house.rfrsFlag ? "ON" : "OFF"}</td>
                            <td>{house.rgstDttm ? new Date(house.rgstDttm).toLocaleDateString() : "-"}</td>
                            {canManage && (
                                <td className="text-nowrap">
                                    {isDeleted ? (
                                        isAdmin && (
                                            <Button size="sm" variant="outline-primary"
                                                    onClick={() => handleRestore(house.housId)}>삭제취소</Button>
                                        )
                                    ) : (
                                        <>
                                            <Button size="sm" variant="outline-success" className="me-1"
                                                    onClick={() => startEdit(house)}>수정</Button>
                                            <Button size="sm" variant="outline-danger"
                                                    onClick={() => confirmDelete(house)}>삭제</Button>
                                        </>
                                    )}
                                </td>
                            )}
                        </tr>
                    );
                })}
                {houses.length === 0 && (
                    <tr>
                        <td colSpan={isAdmin ? 11 : canManage ? 10 : 9} className="text-center text-muted">등록된 재배사가 없습니다.</td>
                    </tr>
                )}
                </tbody>
            </Table>

            {/* 결과 알림 */}
            <AlertModal show={showModal} hideModalFunc={() => setShowModal(false)}
                        title={modalMsg.title} body={modalMsg.body} variant={modalMsg.variant}/>

            {/* 삭제 확인 */}
            <AlertModal show={showDeleteModal} hideModalFunc={() => setShowDeleteModal(false)}
                        onClickFunc={handleDelete}
                        title="재배사 삭제"
                        body={`'${deleteTarget?.housName}' 재배사를 삭제하시겠습니까?`}
                        variant="danger" buttonMsg="삭제"/>
        </Container>
    );
}
