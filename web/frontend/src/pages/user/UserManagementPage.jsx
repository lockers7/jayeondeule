// 사용자 관리 페이지 — 농장별 사용자 목록 조회, 등록, 수정, 삭제(soft delete)
// user_m_info 테이블 기반, 코드 테이블(auth_lvel, pstn) 콤보박스 적용
// 비admin 사용자는 자기 소속 농장의 사용자만 조회
import React, {useEffect, useState} from "react";
import {Button, Container, Form, Modal, Spinner, Table} from "react-bootstrap";
import {useParams} from "react-router-dom";
import {useSelector} from "react-redux";
import {searchUserList, registerUser, patchUserFarmId, patchUserById, idDuplCheck, deleteUserById, restoreUserById, hardDeleteUserById} from "../../utils/userUtil.js";
import {getMyFarm, getFarmList} from "../../utils/farmUtil.js";
import AlertModal from "../../components/common/AlertModal.jsx";

// 코드 테이블 값 (code_m_info 기반) — API 응답 값과 일치
// ADMIN(0)=시스템관리자, SYS_MONITOR(1)=시스템모니터링, FARM_ADMIN(2)=농장관리자, FARM_MONITOR(3)=농장모니터링
const AUTH_LVEL_OPTIONS = [
    {value: "FARM_ADMIN", label: "농장관리자"},
    {value: "FARM_MONITOR", label: "농장모니터링"},
];
const AUTH_LVEL_OPTIONS_ADMIN = [
    {value: "ADMIN", label: "시스템관리자"},
    {value: "SYS_MONITOR", label: "시스템모니터링"},
    ...AUTH_LVEL_OPTIONS,
];
const PSTN_OPTIONS = [
    {value: "1", label: "농장주"},
    {value: "2", label: "농장관리"},
    {value: "99", label: "농장모니터링"},
];

const pstnToAuthLvel = (pstn) => {
    if (pstn === "1" || pstn === "2") return "FARM_ADMIN";
    return "FARM_MONITOR";
};

export default function UserManagementPage() {
    const {farmId: urlFarmId} = useParams();
    const userInfo = useSelector((state) => state.auth.userInfo);
    const globalSelectedFarm = useSelector((state) => state.auth.selectedFarm);
    const isAdmin = userInfo?.authLvel === "ADMIN";
    const canManage = isAdmin || userInfo?.authLvel === "FARM_ADMIN";

    const [activeFarmId, setActiveFarmId] = useState(null);
    const [users, setUsers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [modalMsg, setModalMsg] = useState({title: "", body: "", variant: "success"});
    const [showDeleteModal, setShowDeleteModal] = useState(false);
    const [deleteTarget, setDeleteTarget] = useState(null);
    const [showHardDeleteModal, setShowHardDeleteModal] = useState(false);
    const [hardDeleteTarget, setHardDeleteTarget] = useState(null);
    const [showReleaseModal, setShowReleaseModal] = useState(false);
    const [releaseTarget, setReleaseTarget] = useState(null);

    // 농장 목록 (admin용 드롭다운)
    const [farmList, setFarmList] = useState([]);

    // 수정 폼
    const [editId, setEditId] = useState(null);
    const [editForm, setEditForm] = useState({});

    // 비밀번호 변경 모달
    const [showPwModal, setShowPwModal] = useState(false);
    const [pwForm, setPwForm] = useState({newPw: "", confirmPw: ""});

    // 신규 등록 폼
    const [showRegister, setShowRegister] = useState(false);
    const [newForm, setNewForm] = useState({userId: "", passwd: "", userName: "", pstn: "2", hpNo: ""});
    const [idChecked, setIdChecked] = useState(false);
    const [idAvailable, setIdAvailable] = useState(false);

    // 농장 ID 결정: ADMIN은 Redux selectedFarm (헤더 선택 기준) → URL 폴백, 비admin은 자기 농장
    useEffect(() => {
        const resolveFarmId = async () => {
            if (isAdmin) {
                const fid = globalSelectedFarm?.farmId ?? urlFarmId;
                setActiveFarmId(fid != null ? String(fid) : null);
                try {
                    const res = await getFarmList(0, 100);
                    setFarmList(res.data?.content || []);
                } catch (err) { console.error(err); }
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
    }, [urlFarmId, isAdmin, globalSelectedFarm?.farmId]);

    // 사용자 목록 조회 (activeFarmId 기반)
    const fetchUsers = async () => {
        if (!activeFarmId) return;
        try {
            const res = await searchUserList(0, 100, activeFarmId);
            setUsers(res.data?.content || []);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (activeFarmId) fetchUsers();
    }, [activeFarmId]);

    // 수정 시작
    const startEdit = (user) => {
        setEditId(user.userId);
        setEditForm({
            userName: user.userName || "",
            pstn: user.pstn || "2",
            hpNo: user.hpNo || "",
            authLvel: user.authLvel || "FARM_MONITOR",
            farmId: user.farmId != null ? String(user.farmId) : "0",
        });
    };

    const cancelEdit = () => setEditId(null);

    const handleEditChange = (e) => {
        const {name, value} = e.target;
        if (name === "pstn") {
            setEditForm({...editForm, pstn: value, authLvel: pstnToAuthLvel(value)});
        } else {
            setEditForm({...editForm, [name]: value});
        }
    };

    const saveEdit = async () => {
        try {
            const payload = {
                userName: editForm.userName,
                pstn: editForm.pstn,
                hpNo: editForm.hpNo,
                authLvel: editForm.authLvel,
                farmId: Number(editForm.farmId),
            };
            await patchUserById(editId, payload);
            setEditId(null);
            setModalMsg({title: "알림", body: "사용자 정보가 수정되었습니다.", variant: "success"});
            setShowModal(true);
            fetchUsers();
        } catch (err) {
            setModalMsg({title: "오류", body: "사용자 수정에 실패했습니다.", variant: "danger"});
            setShowModal(true);
        }
    };

    // 비밀번호 변경
    const openPwModal = () => {
        setPwForm({newPw: "", confirmPw: ""});
        setShowPwModal(true);
    };
    const handlePwChange = async () => {
        if (!pwForm.newPw.trim()) {
            setModalMsg({title: "알림", body: "새 비밀번호를 입력해주세요.", variant: "warning"});
            setShowModal(true);
            return;
        }
        if (pwForm.newPw !== pwForm.confirmPw) {
            setModalMsg({title: "알림", body: "비밀번호가 일치하지 않습니다.", variant: "warning"});
            setShowModal(true);
            return;
        }
        try {
            await patchUserById(editId, {passwd: pwForm.newPw});
            setShowPwModal(false);
            setModalMsg({title: "알림", body: "비밀번호가 변경되었습니다.", variant: "success"});
            setShowModal(true);
        } catch (err) {
            setModalMsg({title: "오류", body: "비밀번호 변경에 실패했습니다.", variant: "danger"});
            setShowModal(true);
        }
    };

    // 삭제 확인
    const confirmDelete = (user) => {
        setDeleteTarget(user);
        setShowDeleteModal(true);
    };

    // 삭제 실행 (soft delete)
    const handleDelete = async () => {
        try {
            await deleteUserById(deleteTarget.userId);
            setShowDeleteModal(false);
            fetchUsers();
            setTimeout(() => {
                setModalMsg({title: "알림", body: "사용자가 삭제되었습니다.", variant: "success"});
                setShowModal(true);
            }, 300);
        } catch (err) {
            setShowDeleteModal(false);
            setTimeout(() => {
                setModalMsg({title: "오류", body: "사용자 삭제에 실패했습니다.", variant: "danger"});
                setShowModal(true);
            }, 300);
        }
    };

    // 복원 실행 (관리자 전용)
    const handleRestore = async (userId) => {
        try {
            await restoreUserById(userId);
            setModalMsg({title: "알림", body: "사용자가 복원되었습니다.", variant: "success"});
            setShowModal(true);
            fetchUsers();
        } catch (err) {
            setModalMsg({title: "오류", body: "사용자 복원에 실패했습니다.", variant: "danger"});
            setShowModal(true);
        }
    };

    // 완전 삭제 확인 (관리자 전용)
    const confirmHardDelete = (user) => {
        setHardDeleteTarget(user);
        setShowHardDeleteModal(true);
    };
    const handleHardDelete = async () => {
        try {
            await hardDeleteUserById(hardDeleteTarget.userId);
            setShowHardDeleteModal(false);
            fetchUsers();
            setTimeout(() => {
                setModalMsg({title: "알림", body: "사용자가 완전 삭제되었습니다.", variant: "success"});
                setShowModal(true);
            }, 300);
        } catch (err) {
            setShowHardDeleteModal(false);
            setTimeout(() => {
                setModalMsg({title: "오류", body: "사용자 완전 삭제에 실패했습니다.", variant: "danger"});
                setShowModal(true);
            }, 300);
        }
    };

    // 해제 확인 (농장 배정 해제)
    const confirmRelease = (user) => {
        setReleaseTarget(user);
        setShowReleaseModal(true);
    };

    // 해제 실행 (farmId를 0으로)
    const handleRelease = async () => {
        try {
            await patchUserFarmId(releaseTarget.userId, {farmId: 0});
            setShowReleaseModal(false);
            setModalMsg({title: "알림", body: "사용자가 농장에서 해제되었습니다.", variant: "success"});
            setShowModal(true);
            fetchUsers();
        } catch (err) {
            setShowReleaseModal(false);
            setModalMsg({title: "오류", body: "사용자 해제에 실패했습니다.", variant: "danger"});
            setShowModal(true);
        }
    };

    // 아이디 중복 확인
    const handleIdCheck = async () => {
        if (!newForm.userId.trim()) return;
        try {
            const res = await idDuplCheck(newForm.userId);
            const isDupl = res.data;
            setIdChecked(true);
            setIdAvailable(!isDupl);
            if (isDupl) {
                setModalMsg({title: "알림", body: "이미 사용 중인 아이디입니다.", variant: "warning"});
            } else {
                setModalMsg({title: "알림", body: "사용 가능한 아이디입니다.", variant: "success"});
            }
            setShowModal(true);
        } catch (err) {
            setModalMsg({title: "오류", body: "아이디 확인에 실패했습니다.", variant: "danger"});
            setShowModal(true);
        }
    };

    // 신규 사용자 등록 후 농장 배정
    const handleRegister = async (e) => {
        e.preventDefault();
        if (!idChecked || !idAvailable) {
            setModalMsg({title: "알림", body: "아이디 중복 확인을 먼저 해주세요.", variant: "warning"});
            setShowModal(true);
            return;
        }
        try {
            await registerUser(newForm);
            // 등록 후 농장 배정
            await patchUserFarmId(newForm.userId, {farmId: Number(activeFarmId)});
            // pstn 기반 authLvel 자동 설정
            await patchUserById(newForm.userId, {authLvel: pstnToAuthLvel(newForm.pstn)});
            setShowRegister(false);
            setNewForm({userId: "", passwd: "", userName: "", pstn: "2", hpNo: ""});
            setIdChecked(false);
            setIdAvailable(false);
            setModalMsg({title: "알림", body: "사용자가 등록되었습니다.", variant: "success"});
            setShowModal(true);
            fetchUsers();
        } catch (err) {
            setModalMsg({title: "오류", body: "사용자 등록에 실패했습니다.", variant: "danger"});
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
                <h4>사용자 관리</h4>
                {canManage && (
                    <Button variant="success" size="sm" onClick={() => setShowRegister(!showRegister)}>
                        {showRegister ? "취소" : "사용자 등록"}
                    </Button>
                )}
            </div>

            {/* 신규 등록 폼 — 테이블 형태 */}
            {showRegister && (
                <Form onSubmit={handleRegister}>
                    <div className="mb-3" style={{border: "2px solid #198754", borderRadius: "6px", overflow: "hidden"}}>
                        <div className="d-flex justify-content-between align-items-center px-3 py-2"
                             style={{backgroundColor: "#198754", color: "#fff"}}>
                            <span className="fw-bold">사용자 등록</span>
                            <div>
                                <Button size="sm" variant="light" className="me-1" type="submit">등록</Button>
                                <Button size="sm" variant="outline-light"
                                        onClick={() => setShowRegister(false)}>취소</Button>
                            </div>
                        </div>
                        <table className="table table-bordered mb-0" style={{fontSize: "0.875rem"}}>
                            <tbody>
                            <tr>
                                <th style={{backgroundColor: "#e9ecef", width: "12%"}} className="text-center align-middle">아이디</th>
                                <td style={{width: "22%"}}>
                                    <div className="d-flex gap-1">
                                        <Form.Control size="sm" value={newForm.userId}
                                                      onChange={(e) => {
                                                          setNewForm({...newForm, userId: e.target.value});
                                                          setIdChecked(false);
                                                          setIdAvailable(false);
                                                      }}
                                                      placeholder="아이디" required/>
                                        <Button size="sm" variant="outline-secondary" onClick={handleIdCheck}
                                                type="button" className="text-nowrap">중복확인</Button>
                                    </div>
                                </td>
                                <th style={{backgroundColor: "#e9ecef", width: "12%"}} className="text-center align-middle">비밀번호</th>
                                <td style={{width: "22%"}}>
                                    <Form.Control size="sm" type="password" value={newForm.passwd}
                                                  onChange={(e) => setNewForm({...newForm, passwd: e.target.value})}
                                                  placeholder="비밀번호" required/>
                                </td>
                                <th style={{backgroundColor: "#e9ecef", width: "10%"}} className="text-center align-middle">이름</th>
                                <td style={{width: "22%"}}>
                                    <Form.Control size="sm" value={newForm.userName}
                                                  onChange={(e) => setNewForm({...newForm, userName: e.target.value})}
                                                  placeholder="사용자명" required/>
                                </td>
                            </tr>
                            <tr>
                                <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">직위</th>
                                <td>
                                    <Form.Select size="sm" value={newForm.pstn}
                                                 onChange={(e) => setNewForm({...newForm, pstn: e.target.value})}>
                                        {PSTN_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                                    </Form.Select>
                                </td>
                                <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">연락처</th>
                                <td colSpan={3}>
                                    <Form.Control size="sm" value={newForm.hpNo}
                                                  onChange={(e) => setNewForm({...newForm, hpNo: e.target.value})}
                                                  placeholder="010-0000-0000"/>
                                </td>
                            </tr>
                            </tbody>
                        </table>
                    </div>
                </Form>
            )}

            {/* 수정 폼 — 테이블 형태 */}
            {editId != null && (
                <div className="mb-3" style={{border: "2px solid #198754", borderRadius: "6px", overflow: "hidden"}}>
                    <div className="d-flex justify-content-between align-items-center px-3 py-2"
                         style={{backgroundColor: "#198754", color: "#fff"}}>
                        <span className="fw-bold">사용자 수정 ({editId})</span>
                        <div>
                            <Button size="sm" variant="warning" className="me-1" onClick={openPwModal}>비밀번호변경</Button>
                            <Button size="sm" variant="light" className="me-1" onClick={saveEdit}>저장</Button>
                            <Button size="sm" variant="outline-light" onClick={cancelEdit}>취소</Button>
                        </div>
                    </div>
                    <table className="table table-bordered mb-0" style={{fontSize: "0.875rem"}}>
                        <tbody>
                        <tr>
                            <th style={{backgroundColor: "#e9ecef", width: "12%"}} className="text-center align-middle">이름</th>
                            <td style={{width: "22%"}}>
                                <Form.Control size="sm" name="userName" value={editForm.userName}
                                              onChange={handleEditChange}/>
                            </td>
                            <th style={{backgroundColor: "#e9ecef", width: "12%"}} className="text-center align-middle">권한</th>
                            <td style={{width: "22%"}}>
                                <Form.Select size="sm" name="authLvel" value={editForm.authLvel}
                                             onChange={handleEditChange}>
                                    {(isAdmin ? AUTH_LVEL_OPTIONS_ADMIN : AUTH_LVEL_OPTIONS).map((o) =>
                                        <option key={o.value} value={o.value}>{o.label}</option>)}
                                </Form.Select>
                            </td>
                            <th style={{backgroundColor: "#e9ecef", width: "10%"}} className="text-center align-middle">연락처</th>
                            <td style={{width: "22%"}}>
                                <Form.Control size="sm" name="hpNo" value={editForm.hpNo}
                                              onChange={handleEditChange} placeholder="010-0000-0000"/>
                            </td>
                        </tr>
                        <tr>
                            <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">직위</th>
                            <td>
                                <Form.Select size="sm" name="pstn" value={editForm.pstn}
                                             onChange={handleEditChange}>
                                    {PSTN_OPTIONS.map((o) =>
                                        <option key={o.value} value={o.value}>{o.label}</option>)}
                                </Form.Select>
                            </td>
                            <th style={{backgroundColor: "#e9ecef"}} className="text-center align-middle">소속농장</th>
                            <td>
                                {isAdmin ? (
                                    <Form.Select size="sm" name="farmId" value={editForm.farmId}
                                                 onChange={handleEditChange}>
                                        {farmList.map((f) =>
                                            <option key={f.farmId} value={String(f.farmId)}>{f.farmName}</option>)}
                                    </Form.Select>
                                ) : (
                                    <Form.Control size="sm" value={editForm.farmId} disabled/>
                                )}
                            </td>
                        </tr>
                        </tbody>
                    </table>
                </div>
            )}

            <Table striped bordered hover responsive size="sm">
                <thead>
                <tr>
                    {isAdmin && <th style={{width: "8%"}}>상태</th>}
                    <th style={{width: isAdmin ? "14%" : "15%"}}>아이디</th>
                    <th style={{width: "13%"}}>이름</th>
                    <th style={{width: "15%"}}>권한</th>
                    <th style={{width: "10%"}}>직위</th>
                    <th style={{width: "15%"}}>연락처</th>
                    <th style={{width: isAdmin ? "10%" : "15%"}}>등록일</th>
                    {canManage && <th style={{width: isAdmin ? "15%" : "17%"}}>관리</th>}
                </tr>
                </thead>
                <tbody>
                {users.map((user) => {
                    const isDeleted = user.dlteYn === "Y";
                    return (
                        <tr key={user.userId}
                            className={editId === user.userId ? "table-warning" : isDeleted ? "table-secondary" : ""}>
                            {isAdmin && (
                                <td className="text-center">
                                    {isDeleted ? (
                                        <span
                                            className="badge bg-danger"
                                            style={{cursor: "pointer"}}
                                            onClick={() => confirmHardDelete(user)}
                                            title="완전삭제"
                                        >삭제</span>
                                    ) : (
                                        <span className="badge bg-success">정상</span>
                                    )}
                                </td>
                            )}
                            <td>{user.userId}</td>
                            <td>{user.userName}</td>
                            <td>{getLabelByValue(AUTH_LVEL_OPTIONS_ADMIN, user.authLvel)}</td>
                            <td>{getLabelByValue(PSTN_OPTIONS, user.pstn)}</td>
                            <td>{user.hpNo || "-"}</td>
                            <td>{user.rgstDttm ? new Date(user.rgstDttm).toLocaleDateString() : "-"}</td>
                            {canManage && (
                                <td className="text-nowrap">
                                    {isDeleted ? (
                                        isAdmin && (
                                            <Button size="sm" variant="outline-primary"
                                                    onClick={() => handleRestore(user.userId)}>삭제취소</Button>
                                        )
                                    ) : (
                                        <>
                                            <Button size="sm" variant="outline-success" className="me-1"
                                                    onClick={() => startEdit(user)}>수정</Button>
                                            <Button size="sm" variant="outline-danger"
                                                    onClick={() => confirmDelete(user)}>삭제</Button>
                                        </>
                                    )}
                                </td>
                            )}
                        </tr>
                    );
                })}
                {users.length === 0 && (
                    <tr>
                        <td colSpan={isAdmin ? 8 : canManage ? 7 : 6} className="text-center text-muted">등록된 사용자가 없습니다.</td>
                    </tr>
                )}
                </tbody>
            </Table>

            {/* 결과 알림 */}
            <AlertModal show={showModal} hideModalFunc={() => setShowModal(false)}
                        title={modalMsg.title} body={modalMsg.body} variant={modalMsg.variant}/>

            {/* 해제 확인 */}
            <AlertModal show={showReleaseModal} hideModalFunc={() => setShowReleaseModal(false)}
                        onClickFunc={handleRelease}
                        title="사용자 해제"
                        body={`'${releaseTarget?.userName}(${releaseTarget?.userId})' 사용자를 농장에서 해제하시겠습니까?`}
                        variant="warning" buttonMsg="해제"/>

            {/* 삭제 확인 */}
            <AlertModal show={showDeleteModal} hideModalFunc={() => setShowDeleteModal(false)}
                        onClickFunc={handleDelete}
                        title="사용자 삭제"
                        body={`'${deleteTarget?.userName}(${deleteTarget?.userId})' 사용자를 삭제하시겠습니까?`}
                        variant="danger" buttonMsg="삭제"/>

            {/* 완전삭제 확인 */}
            <AlertModal show={showHardDeleteModal} hideModalFunc={() => setShowHardDeleteModal(false)}
                        onClickFunc={handleHardDelete}
                        title="사용자 완전삭제"
                        body={`'${hardDeleteTarget?.userName}(${hardDeleteTarget?.userId})' 사용자를 완전히 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.`}
                        variant="danger" buttonMsg="완전삭제"/>

            {/* 비밀번호 변경 모달 */}
            <Modal show={showPwModal} onHide={() => setShowPwModal(false)} centered>
                <Modal.Header closeButton>
                    <Modal.Title>비밀번호 변경 ({editId})</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <Form.Group className="mb-3">
                        <Form.Label>새 비밀번호</Form.Label>
                        <Form.Control type="password" value={pwForm.newPw}
                                      onChange={(e) => setPwForm({...pwForm, newPw: e.target.value})}
                                      placeholder="새 비밀번호 입력"/>
                    </Form.Group>
                    <Form.Group>
                        <Form.Label>비밀번호 확인</Form.Label>
                        <Form.Control type="password" value={pwForm.confirmPw}
                                      onChange={(e) => setPwForm({...pwForm, confirmPw: e.target.value})}
                                      placeholder="비밀번호 재입력"/>
                    </Form.Group>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={() => setShowPwModal(false)}>취소</Button>
                    <Button variant="warning" onClick={handlePwChange}>변경</Button>
                </Modal.Footer>
            </Modal>
        </Container>
    );
}
