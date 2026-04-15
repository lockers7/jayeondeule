// 재배사 관리 페이지 — farmhouse_m_info 전체 필드 CRUD
// 코드 테이블(crop_kind, crop_lvel, ctrl_type) 콤보박스 적용
// admin: 모든 재배사 수정 가능(소속농장 변경 포함), 비admin: 자기 농장 재배사만
import React, {useEffect, useState} from "react";
import {Button, Container, Form, Spinner, Table, Row, Col, Card} from "react-bootstrap";
import {useParams} from "react-router-dom";
import {useSelector} from "react-redux";
import {getHouseList, patchHouse, deleteHouse, registerHouse, restoreHouse, hardDeleteHouse, getNextHousId} from "../../utils/houseUtil.js";
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
const OPERATION_MODE_OPTIONS = [
    {value: "manual", label: "수동제어"},
    {value: "algorithm", label: "알고리즘"},
    {value: "ai", label: "인공지능"},
];

// 모니터 페이지와 동일한 운용방식 결정 로직
const getOperationMode = (house) => {
    if (!house.mnulCtrlFlag) return "manual";
    if (house.ctrlType === "ai") return "ai";
    return "algorithm";
};
const getOperationModeLabel = (house) => {
    const mode = getOperationMode(house);
    return OPERATION_MODE_OPTIONS.find(o => o.value === mode)?.label || mode;
};

export default function HouseManagementPage() {
    const {farmId: urlFarmId} = useParams();
    const userInfo = useSelector((state) => state.auth.userInfo);
    const globalSelectedFarm = useSelector((state) => state.auth.selectedFarm);
    const isAdmin = userInfo?.authLvel === "ADMIN";
    const isSysMonitor = userInfo?.authLvel === "SYS_MONITOR";
    const canManage = isAdmin || userInfo?.authLvel === "FARM_ADMIN";

    const [activeFarmId, setActiveFarmId] = useState(null);
    const [houses, setHouses] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [modalMsg, setModalMsg] = useState({title: "", body: "", variant: "success"});
    const [showDeleteModal, setShowDeleteModal] = useState(false);
    const [deleteTarget, setDeleteTarget] = useState(null);
    const [showHardDeleteModal, setShowHardDeleteModal] = useState(false);
    const [hardDeleteTarget, setHardDeleteTarget] = useState(null);

    // 수정 폼
    const [editId, setEditId] = useState(null);
    const [editForm, setEditForm] = useState({});

    // 신규 등록 폼
    const [showRegister, setShowRegister] = useState(false);
    const [newForm, setNewForm] = useState({
        housId: "", housName: "", cropKind: "10", cropLvel: "2", operationMode: "algorithm",
        snsrRfrsItvl: "3", rfrsFlag: false,
    });

    // admin용 농장 리스트 (등록시 농장 선택)
    const [farmList, setFarmList] = useState([]);
    const [registerFarmId, setRegisterFarmId] = useState("");

    // 농장 ID 결정: ADMIN/SYS_MONITOR는 Redux selectedFarm (헤더 선택 기준) → URL 폴백, 비admin은 자기 농장
    useEffect(() => {
        const resolveFarmId = async () => {
            if (isAdmin || isSysMonitor) {
                const fid = globalSelectedFarm?.farmId ?? urlFarmId;
                setActiveFarmId(fid != null ? String(fid) : null);
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
    }, [urlFarmId, isAdmin, isSysMonitor, globalSelectedFarm?.farmId]);

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
            const list = res.data || [];
            setHouses(isAdmin ? list : list.filter(h => h.housId !== 0));
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
            newHousId: String(house.housId),
            housName: house.housName || "",
            cropKind: house.cropKind || "10",
            cropLvel: String(house.cropLvel ?? 2),
            operationMode: getOperationMode(house),
            snsrRfrsItvl: house.snsrRfrsItvl || "3",
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
            const {operationMode, newHousId, ...rest} = editForm;
            const patchData = {...rest, ...modeToFields(operationMode)};
            // ADMIN: 재배사번호 변경 시 newHousId 전달
            if (isAdmin && newHousId !== String(editForm.housId)) {
                patchData.newHousId = Number(newHousId);
            }
            await patchHouse(patchData);
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
            fetchHouses();
            setTimeout(() => {
                setModalMsg({title: "알림", body: "재배사가 삭제되었습니다.", variant: "success"});
                setShowModal(true);
            }, 300);
        } catch (err) {
            setShowDeleteModal(false);
            setTimeout(() => {
                setModalMsg({title: "오류", body: "재배사 삭제에 실패했습니다.", variant: "danger"});
                setShowModal(true);
            }, 300);
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

    // 완전 삭제 확인 (관리자 전용)
    const confirmHardDelete = (house) => {
        setHardDeleteTarget(house);
        setShowHardDeleteModal(true);
    };
    const handleHardDelete = async () => {
        try {
            await hardDeleteHouse(activeFarmId, hardDeleteTarget.housId);
            setShowHardDeleteModal(false);
            fetchHouses();
            setTimeout(() => {
                setModalMsg({title: "알림", body: "재배사가 완전 삭제되었습니다.", variant: "success"});
                setShowModal(true);
            }, 300);
        } catch (err) {
            setShowHardDeleteModal(false);
            setTimeout(() => {
                setModalMsg({title: "오류", body: "재배사 완전 삭제에 실패했습니다.", variant: "danger"});
                setShowModal(true);
            }, 300);
        }
    };

    // operationMode → ctrlType + mnulCtrlFlag 변환
    const modeToFields = (mode) => {
        if (mode === "manual") return {mnulCtrlFlag: false, ctrlType: "algorithm"};
        if (mode === "ai") return {mnulCtrlFlag: true, ctrlType: "ai"};
        return {mnulCtrlFlag: true, ctrlType: "algorithm"};
    };

    const handleRegister = async (e) => {
        e.preventDefault();
        try {
            const targetFarmId = isAdmin ? registerFarmId : activeFarmId;
            const {operationMode, housId, ...rest} = newForm;
            const sendHousId = Number(housId);
            // housId=0은 시스템관리자만 생성 가능
            if (sendHousId === 0 && !isAdmin) {
                setModalMsg({title: "오류", body: "housId=0은 시스템관리자만 생성할 수 있습니다.", variant: "danger"});
                setShowModal(true);
                return;
            }
            await registerHouse({farmId: targetFarmId, housId: sendHousId, ...rest, ...modeToFields(operationMode)});
            setShowRegister(false);
            setNewForm({housId: "", housName: "", cropKind: "10", cropLvel: "2", operationMode: "algorithm",
                snsrRfrsItvl: "3", rfrsFlag: false});
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
                    <Button variant="success" size="sm" onClick={async () => {
                        if (!showRegister) {
                            try {
                                const targetFarmId = isAdmin ? (registerFarmId || activeFarmId) : activeFarmId;
                                const res = await getNextHousId(targetFarmId);
                                setNewForm(prev => ({...prev, housId: String(res.data)}));
                            } catch (err) {
                                console.error("nextHousId 조회 실패:", err);
                            }
                        }
                        setShowRegister(!showRegister);
                    }}>
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
                                                     onChange={async (e) => {
                                                         const fId = e.target.value;
                                                         setRegisterFarmId(fId);
                                                         try {
                                                             const res = await getNextHousId(fId);
                                                             setNewForm(prev => ({...prev, housId: String(res.data)}));
                                                         } catch (err) { console.error(err); }
                                                     }}>
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
                                <th style={{backgroundColor: "#e9ecef", width: "14%"}} className="text-center align-middle">재배사번호</th>
                                <td style={{width: "19%"}}>
                                    <Form.Control size="sm" value={newForm.housId}
                                                  onChange={(e) => setNewForm({...newForm, housId: e.target.value})}
                                                  type="number" min={isAdmin ? "0" : "1"}
                                                  readOnly={!isAdmin}
                                                  style={!isAdmin ? {backgroundColor: "#e9ecef"} : {}}/>
                                </td>
                                <th style={{backgroundColor: "#e9ecef", width: "14%"}} className="text-center align-middle">재배사명</th>
                                <td style={{width: "19%"}}>
                                    <Form.Control size="sm" value={newForm.housName}
                                                  onChange={(e) => setNewForm({...newForm, housName: e.target.value})}
                                                  placeholder="재배사명" required/>
                                </td>
                                <th style={{backgroundColor: "#e9ecef", width: "14%"}} className="text-center align-middle">작물</th>
                                <td style={{width: "20%"}}>
                                    <Form.Select size="sm" value={newForm.cropKind}
                                                 onChange={(e) => setNewForm({...newForm, cropKind: e.target.value})}>
                                        {CROP_KIND_OPTIONS.map((o) =>
                                            <option key={o.value} value={o.value}>{o.label}</option>)}
                                    </Form.Select>
                                </td>
                            </tr>
                            <tr>
                                <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">생육단계</th>
                                <td>
                                    <Form.Select size="sm" value={newForm.cropLvel}
                                                 onChange={(e) => setNewForm({...newForm, cropLvel: e.target.value})}>
                                        {CROP_LVEL_OPTIONS.map((o) =>
                                            <option key={o.value} value={o.value}>{o.label}</option>)}
                                    </Form.Select>
                                </td>
                                <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">운용방식</th>
                                <td>
                                    <Form.Select size="sm" value={newForm.operationMode}
                                                 onChange={(e) => setNewForm({...newForm, operationMode: e.target.value})}>
                                        {OPERATION_MODE_OPTIONS.map((o) =>
                                            <option key={o.value} value={o.value}>{o.label}</option>)}
                                    </Form.Select>
                                </td>
                                <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">센서간격(초)</th>
                                <td>
                                    <Form.Control size="sm" value={newForm.snsrRfrsItvl}
                                                  onChange={(e) => setNewForm({...newForm, snsrRfrsItvl: e.target.value})}
                                                  type="number" min="1"/>
                                </td>
                                <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">갱신</th>
                                <td>
                                    <Form.Check type="switch" id="reg-rfrsFlag" label="갱신"
                                                checked={newForm.rfrsFlag}
                                                onChange={(e) => setNewForm({...newForm, rfrsFlag: e.target.checked})}/>
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
                            <th style={{backgroundColor: "#e9ecef", width: "14%"}} className="text-center align-middle">재배사번호</th>
                            <td style={{width: "19%"}}>
                                <Form.Control size="sm" name="newHousId" value={editForm.newHousId}
                                              onChange={handleEditChange}
                                              type="number" min={isAdmin ? "0" : "1"}
                                              readOnly={!isAdmin}
                                              style={!isAdmin ? {backgroundColor: "#e9ecef"} : {}}/>
                            </td>
                            <th style={{backgroundColor: "#e9ecef", width: "14%"}} className="text-center align-middle">재배사명</th>
                            <td style={{width: "19%"}}>
                                <Form.Control size="sm" name="housName" value={editForm.housName}
                                              onChange={handleEditChange}/>
                            </td>
                            <th style={{backgroundColor: "#e9ecef", width: "14%"}} className="text-center align-middle">작물</th>
                            <td style={{width: "20%"}}>
                                <Form.Select size="sm" name="cropKind" value={editForm.cropKind}
                                             onChange={handleEditChange}>
                                    {CROP_KIND_OPTIONS.map((o) =>
                                        <option key={o.value} value={o.value}>{o.label}</option>)}
                                </Form.Select>
                            </td>
                        </tr>
                        <tr>
                            <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">생육단계</th>
                            <td>
                                <Form.Select size="sm" name="cropLvel" value={editForm.cropLvel}
                                             onChange={handleEditChange}>
                                    {CROP_LVEL_OPTIONS.map((o) =>
                                        <option key={o.value} value={o.value}>{o.label}</option>)}
                                </Form.Select>
                            </td>
                            <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">운용방식</th>
                            <td>
                                <Form.Select size="sm" name="operationMode" value={editForm.operationMode}
                                             onChange={handleEditChange}>
                                    {OPERATION_MODE_OPTIONS.map((o) =>
                                        <option key={o.value} value={o.value}>{o.label}</option>)}
                                </Form.Select>
                            </td>
                            <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">센서간격(초)</th>
                            <td>
                                <Form.Control size="sm" name="snsrRfrsItvl" value={editForm.snsrRfrsItvl}
                                              onChange={handleEditChange} type="number" min="1"/>
                            </td>
                            <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">갱신</th>
                            <td>
                                <Form.Check type="switch" id="rfrsFlag" label="갱신"
                                            name="rfrsFlag" checked={editForm.rfrsFlag}
                                            onChange={handleEditChange}/>
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
                    <th>운용방식</th>
                    <th>센서간격</th>
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
                                    {isDeleted ? (
                                        <span
                                            className="badge bg-danger"
                                            style={{cursor: "pointer"}}
                                            onClick={() => confirmHardDelete(house)}
                                            title="완전삭제"
                                        >삭제</span>
                                    ) : (
                                        <span className="badge bg-success">정상</span>
                                    )}
                                </td>
                            )}
                            <td>{house.housId}</td>
                            <td>{house.housName}</td>
                            <td>{getLabelByValue(CROP_KIND_OPTIONS, house.cropKind)}</td>
                            <td>{getLabelByValue(CROP_LVEL_OPTIONS, house.cropLvel)}</td>
                            <td>{getOperationModeLabel(house)}</td>
                            <td>{house.snsrRfrsItvl}초</td>
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
                        <td colSpan={isAdmin ? 10 : canManage ? 9 : 8} className="text-center text-muted">등록된 재배사가 없습니다.</td>
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

            {/* 완전 삭제 확인 */}
            <AlertModal show={showHardDeleteModal} hideModalFunc={() => setShowHardDeleteModal(false)}
                        onClickFunc={handleHardDelete}
                        title="재배사 완전 삭제"
                        body={`'${hardDeleteTarget?.housName}' 재배사를 완전히 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.`}
                        variant="danger" buttonMsg="완전삭제"/>
        </Container>
    );
}
