// 마이페이지 — user_m_info 전체 정보 조회 및 수정
// auth_lvel: AuthLvel enum (ADMIN, FARM_ADMIN, MONITOR, HOUS_MANAGER) — 읽기전용
// pstn: code_m_info code_id='pstn' (1=농장주, 99=농장관리) — 수정가능
import {useEffect, useState} from "react";
import {Form, Button, Card, Container, Col, Row} from "react-bootstrap";
import LabeledPhoneInput from "../../components/form/LabeledPhoneInput.jsx";
import LabeledInput from "../../components/form/LabeledInput.jsx";
import {useNavigate} from "react-router-dom";
import {deleteUser, getUser, patchUser} from "../../utils/userUtil.js";
import AlertModal from "../../components/common/AlertModal.jsx";
import {useDispatch, useSelector} from "react-redux";
import {logout} from "../../store/auth/authSlice.js";

// 권한 레벨 (AuthLvel enum — API 응답값 기준)
// ADMIN(0)=시스템관리자, SYS_MONITOR(1)=시스템모니터링, FARM_ADMIN(2)=농장관리자, FARM_MONITOR(3)=농장모니터링
const AUTH_LVEL_OPTIONS = [
    {value: "ADMIN", label: "시스템관리자"},
    {value: "SYS_MONITOR", label: "시스템모니터링"},
    {value: "FARM_ADMIN", label: "농장관리자"},
    {value: "FARM_MONITOR", label: "농장모니터링"},
];

// 코드 테이블 값 (code_m_info, code_id='pstn')
const PSTN_OPTIONS = [
    {value: "1", label: "농장주"},
    {value: "99", label: "농장관리"},
];

export default function MyPage() {
    const navigate = useNavigate();
    const dispatch = useDispatch();
    const userInfo = useSelector((state) => state.auth.userInfo);
    const isAdmin = userInfo?.authLvel === "ADMIN";

    const [form, setForm] = useState({
        userName: "",
        pstn: "",
        hpNo: "",
    });
    const [userMeta, setUserMeta] = useState({
        userId: "",
        authLvel: "",
        farmId: "",
        rgstDttm: "",
    });

    useEffect(() => {
        const fetchUser = async () => {
            try {
                const res = await getUser(); // GET /users/me
                const d = res.data;
                setForm({
                    userName: d.userName || "",
                    pstn: String(d.pstn ?? ""),
                    hpNo: d.hpNo || "",
                });
                setUserMeta({
                    userId: d.userId || "",
                    authLvel: String(d.authLvel ?? ""),
                    farmId: d.farmId != null ? String(d.farmId) : "",
                    rgstDttm: d.rgstDttm || "",
                });
            } catch (err) {
                console.error(err);
            }
        };
        fetchUser();
    }, []);

    const [showModal, setShowModal] = useState(false);
    const [showWithdrawModal, setShowWithdrawModal] = useState(false);

    const handleChange = (e) => {
        const {name, value} = e.target;
        setForm({...form, [name]: value});
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            await patchUser(form);
            setShowModal(true);
        } catch (err) {
            alert("수정 실패");
        }
    };

    return (
        <Container className="d-flex justify-content-center align-items-center flex-grow-1">
            <Card className="p-4 m-5" style={{width: "480px", borderWidth: "2px"}}>
                <Form className="p-4" onSubmit={handleSubmit}>
                    <h2 className="mb-4 text-center">마이페이지</h2>

                    {/* 아이디 (읽기전용) */}
                    <Row className="mb-3 align-items-center">
                        <Col sm={4}>
                            <Form.Label className="mb-0">아이디</Form.Label>
                        </Col>
                        <Col sm={8}>
                            <Form.Control value={userMeta.userId} disabled plaintext
                                          className="fw-bold"/>
                        </Col>
                    </Row>

                    <LabeledInput
                        smLabel={4}
                        label="이름"
                        type="text"
                        name="userName"
                        value={form.userName}
                        onChange={handleChange}
                        placeholder="이름 입력"
                        pattern="^[가-힣a-zA-Z]{2,20}$"
                        errorMsg="한글, 영문으로 이루어진 2~20자로 입력해주세요."
                        required
                    />

                    {/* 권한 (auth_lvel — 읽기전용) */}
                    <Row className="mb-3 align-items-center">
                        <Col sm={4}>
                            <Form.Label className="mb-0">권한</Form.Label>
                        </Col>
                        <Col sm={8}>
                            <Form.Select value={userMeta.authLvel} disabled>
                                <option value="">선택</option>
                                {AUTH_LVEL_OPTIONS.map((o) =>
                                    <option key={o.value} value={o.value}>{o.label}</option>
                                )}
                            </Form.Select>
                        </Col>
                    </Row>

                    {/* 직책 (pstn — 수정가능, code_m_info code_id='pstn') */}
                    <Row className="mb-3 align-items-center">
                        <Col sm={4}>
                            <Form.Label className="mb-0">직책 <span className="text-danger">*</span></Form.Label>
                        </Col>
                        <Col sm={8}>
                            <Form.Select name="pstn" value={form.pstn} onChange={handleChange}>
                                <option value="">선택</option>
                                {PSTN_OPTIONS.map((o) =>
                                    <option key={o.value} value={o.value}>{o.label}</option>
                                )}
                            </Form.Select>
                        </Col>
                    </Row>

                    <LabeledPhoneInput
                        smLabel={4}
                        label="휴대폰번호"
                        name="hpNo"
                        value={form.hpNo}
                        onChange={handleChange}
                        required
                    />

                    {/* 농장ID (읽기전용) */}
                    <Row className="mb-3 align-items-center">
                        <Col sm={4}>
                            <Form.Label className="mb-0">농장ID</Form.Label>
                        </Col>
                        <Col sm={8}>
                            <Form.Control value={userMeta.farmId || "-"} disabled plaintext/>
                        </Col>
                    </Row>

                    {/* 등록일 (읽기전용) */}
                    <Row className="mb-3 align-items-center">
                        <Col sm={4}>
                            <Form.Label className="mb-0">등록일</Form.Label>
                        </Col>
                        <Col sm={8}>
                            <Form.Control
                                value={userMeta.rgstDttm ? new Date(userMeta.rgstDttm).toLocaleDateString() : "-"}
                                disabled plaintext/>
                        </Col>
                    </Row>

                    <div className="d-flex justify-content-center gap-2 mt-3">
                        <Button variant="secondary" type="button" onClick={() => navigate("/mypage/password")}>
                            비밀번호 변경
                        </Button>
                        <Button variant="success" type="submit">
                            수정하기
                        </Button>
                        <Button variant="outline-danger" onClick={() => setShowWithdrawModal(true)}>
                            관리자삭제
                        </Button>
                    </div>
                </Form>
            </Card>

            {/* 수정 알림 Modal */}
            <AlertModal
                show={showModal}
                hideModalFunc={() => setShowModal(false)}
                title="알림"
                body="수정이 완료되었습니다."
            />

            {/* 삭제 확인 Modal */}
            <AlertModal
                show={showWithdrawModal}
                hideModalFunc={() => setShowWithdrawModal(false)}
                onClickFunc={async () => {
                    await deleteUser();
                    dispatch(logout()); // Redux 상태 초기화
                    navigate("/login"); // 로그인 페이지로 이동
                }}
                title="정말로 관리자삭제 하시겠습니까?"
                body="관리자삭제 후에는 복구가 불가능합니다."
                variant="danger"
            />
        </Container>
    )
}
