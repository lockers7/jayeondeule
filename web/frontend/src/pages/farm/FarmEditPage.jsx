// 농장관리 페이지 — 현재 사용자의 농장 정보를 조회하여 수정하는 화면
// ADMIN: 전체 농장 목록 콤보박스에서 선택하여 관리
// 일반 사용자: 자기 농장만 표시 및 수정
import React, {useEffect, useState} from "react";
import {Button, Card, Container, Form, Spinner} from "react-bootstrap";
import {useSelector} from "react-redux";
import LabeledInput from "../../components/form/LabeledInput.jsx";
import LabeledAddress from "../../components/form/LabeledAddress.jsx";
import LabeledSelect from "../../components/form/LabeledSelect.jsx";
import LabeledPhoneInput from "../../components/form/LabeledPhoneInput.jsx";
import {getFarm, getFarmList, getMyFarm, patchFarm} from "../../utils/farmUtil.js";
import AlertModal from "../../components/common/AlertModal.jsx";

export default function FarmEditPage() {
    const userInfo = useSelector((state) => state.auth?.userInfo);
    const globalSelectedFarm = useSelector((state) => state.auth.selectedFarm);
    const isAdmin = userInfo?.authLvel === "ADMIN";
    const isFarmAdmin = userInfo?.authLvel === "FARM_ADMIN";

    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [modalMsg, setModalMsg] = useState({title: "", body: "", variant: "success"});
    const [farmList, setFarmList] = useState([]);

    useEffect(() => {
        const script = document.createElement("script");
        script.src = "https://t1.daumcdn.net/mapjsapi/bundle/postcode/prod/postcode.v2.js";
        script.async = true;
        document.body.appendChild(script);
    }, []);

    const [farm, setFarm] = useState({
        farmId: "",
        farmName: "",
        farmDomi: "",
        openDate: "",
        closeDate: "",
        telNo: "",
        hpNo: "",
        faxNo: "",
        mail: "",
        ipAddr: "",
        port: "",
        addr: "",
        mainPrdt: "",
        rmks: "",
    });

    // 초기 데이터 로드: ADMIN은 농장 목록 + 첫 번째 농장, 일반 사용자는 자기 농장
    useEffect(() => {
        const fetchData = async () => {
            try {
                if (isAdmin) {
                    const listRes = await getFarmList(0, 100);
                    const farms = listRes.data?.content || [];
                    setFarmList(farms);
                    // Redux에 선택된 농장이 있으면 그것을 기본 로드, 없으면 첫 번째 농장
                    const targetId = globalSelectedFarm?.farmId
                        || (farms.length > 0 ? farms[0].farmId : null);
                    if (targetId) {
                        const farmRes = await getFarm({farmId: targetId});
                        setFarm(farmRes.data);
                    }
                } else {
                    const res = await getMyFarm();
                    setFarm(res.data);
                }
            } catch (err) {
                console.error(err);
            } finally {
                setLoading(false);
            }
        };

        fetchData();
    }, [isAdmin]);

    // ADMIN 농장 선택 변경 시 해당 농장 정보 조회
    const handleFarmSelect = async (e) => {
        const selectedFarmId = e.target.value;
        if (!selectedFarmId) return;
        try {
            setLoading(true);
            const res = await getFarm({farmId: selectedFarmId});
            setFarm(res.data);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const handleChange = (e) => {
        const {name, value} = e.target;
        setFarm({...farm, [name]: value});
    };

    const handleAddressSearch = (e) => {
        new window.daum.Postcode({
            oncomplete: function (data) {
                setFarm((state) => ({
                    ...state,
                    addr: data.address,
                }));
            },
        }).open();
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            await patchFarm(farm);
            setModalMsg({title: "알림", body: "농장 정보가 수정되었습니다.", variant: "success"});
        } catch (err) {
            setModalMsg({title: "오류", body: "농장 정보 저장에 실패했습니다.", variant: "danger"});
        }
        setShowModal(true);
    };

    if (loading) {
        return (
            <Container className="d-flex justify-content-center align-items-center flex-grow-1">
                <Spinner animation="border" variant="success"/>
            </Container>
        );
    }

    return (
        <Container className="d-flex justify-content-center align-items-center flex-grow-1">
            <Card className="p-4 m-5" style={{width: "800px", borderWidth: "2px"}}>
                <Form className="p-4" onSubmit={handleSubmit}>
                    <h2 className="mb-4 text-center">농장관리</h2>

                    {/* ADMIN: 농장 선택 콤보박스 */}
                    {isAdmin && farmList.length > 0 && (
                        <Form.Group className="row mb-3">
                            <Form.Label column sm={3} className="text-end">농장 선택</Form.Label>
                            <div className="col-sm-5">
                                <Form.Select
                                    value={farm.farmId}
                                    onChange={handleFarmSelect}
                                >
                                    {farmList.map((f) => (
                                        <option key={f.farmId} value={f.farmId}>
                                            {f.farmName}
                                        </option>
                                    ))}
                                </Form.Select>
                            </div>
                        </Form.Group>
                    )}

                    <LabeledInput
                        label="농장 이름"
                        smInput={5}
                        name="farmName"
                        value={farm.farmName}
                        onChange={handleChange}
                        placeholder="농장 이름 입력"
                        pattern="^[가-힣a-zA-Z0-9 ]{2,20}$"
                        errorMsg="한글, 영문, 숫자로 이루어진 2~20자로 입력해주세요."
                        required
                        readOnly={isFarmAdmin}
                        style={isFarmAdmin ? {backgroundColor: "#e9ecef"} : {}}
                    />
                    <LabeledInput
                        label="농장 도메인"
                        smInput={5}
                        name="farmDomi"
                        value={farm.farmDomi}
                        onChange={handleChange}
                        placeholder="농장 도메인 입력"
                        pattern="^[a-zA-Z0-9.]*$"
                        errorMsg="영문, 숫자로 입력해주세요."
                        required
                    />
                    <LabeledInput
                        label="개업일자"
                        smInput={5}
                        type="date"
                        name="openDate"
                        value={farm.openDate}
                        onChange={handleChange}
                        required
                    />
                    <LabeledInput
                        label="폐업일자"
                        smInput={5}
                        type="date"
                        name="closeDate"
                        value={farm.closeDate}
                        onChange={handleChange}
                    />
                    <LabeledPhoneInput
                        label="대표번호"
                        smInput={5}
                        name="telNo"
                        value={farm.telNo}
                        onChange={handleChange}
                        required
                    />
                    <LabeledPhoneInput
                        label="전화번호"
                        smInput={5}
                        name="hpNo"
                        value={farm.hpNo}
                        placeholder="063-1234-5678"
                        onChange={handleChange}
                    />
                    <LabeledPhoneInput
                        label="팩스번호"
                        smInput={5}
                        name="faxNo"
                        value={farm.faxNo}
                        placeholder="063-1234-5678"
                        onChange={handleChange}
                    />
                    <LabeledInput
                        label="대표메일"
                        smInput={5}
                        type="email"
                        name="mail"
                        value={farm.mail}
                        onChange={handleChange}
                        placeholder="대표메일 입력"
                    />
                    <LabeledInput
                        label="농장 IP"
                        smInput={5}
                        name="ipAddr"
                        value={farm.ipAddr}
                        onChange={handleChange}
                        placeholder="농장 IP 입력"
                        required
                    />
                    <LabeledInput
                        label="농장 포트"
                        smInput={5}
                        name="port"
                        value={farm.port}
                        onChange={handleChange}
                        placeholder="농장 포트 입력"
                        pattern="^[0-9]{2,5}$"
                        errorMsg="숫자 2~5자로 입력해주세요."
                        required
                    />
                    <LabeledAddress
                        label="주소"
                        name="addr"
                        value={farm.addr}
                        onChange={handleChange}
                        onSearch={handleAddressSearch}
                        required
                    />
                    <LabeledSelect
                        label="주요 작물"
                        smInput={5}
                        name="mainPrdt"
                        placeholder="주요 작물 선택"
                        option={[
                            { value: "10", label: "상황버섯"},
                        ]}
                        value={farm.mainPrdt}
                        onChange={handleChange}
                        required
                    />
                    <LabeledInput
                        label="농장 설명"
                        smInput={5}
                        name="rmks"
                        value={farm.rmks}
                        onChange={handleChange}
                        placeholder="농장 설명 입력"
                    />

                    <Button type="submit" variant="success" className="w-100 mt-3">농장정보 저장</Button>
                </Form>
            </Card>

            {/* 수정 알림 Modal */}
            <AlertModal
                show={showModal}
                hideModalFunc={() => setShowModal(false)}
                title={modalMsg.title}
                body={modalMsg.body}
                variant={modalMsg.variant}
            />
        </Container>
    );
}
