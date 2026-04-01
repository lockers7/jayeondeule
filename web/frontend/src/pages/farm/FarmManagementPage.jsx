import {useEffect, useState, useRef, useCallback} from "react";
import {
    Table,
    Button,
    Form,
    Container,
    Row,
    Col,
    Spinner,
    InputGroup,
    Dropdown,
} from "react-bootstrap";
import {useNavigate} from "react-router-dom";
import {useDispatch, useSelector} from "react-redux";
import {setSelectedFarm} from "../../store/auth/authSlice.js";
import TruncatedOverlayTrigger from "../../components/farm/TruncatedOverlayTrigger.jsx";
import {getFarmList, deleteFarm, restoreFarm, hardDeleteFarm} from "../../utils/farmUtil.js";
import {getHouseList} from "../../utils/houseUtil.js";
import {getLatestSensorData} from "../../utils/sensorUtil.js";
import AlertModal from "../../components/common/AlertModal.jsx";
import {playAlertBeep, SENSOR_TIMEOUT_SEC, getServerNow} from "../../components/sensor/LatestSensorMonitor.jsx";

export default function FarmManagementPage() {
    const navigate = useNavigate();
    const dispatch = useDispatch();
    const userInfo = useSelector((state) => state.auth.userInfo);
    const isAdmin = userInfo?.authLvel === "ADMIN";

    const [farms, setFarms] = useState([]);
    const [search, setSearch] = useState("");
    const [searchField, setSearchField] = useState("farmName");
    const [page, setPage] = useState(0);
    const [hasMore, setHasMore] = useState(true);
    const [loading, setLoading] = useState(false);
    const observer = useRef();

    // 농장별 RPi 에러 상태
    const [farmErrorMap, setFarmErrorMap] = useState({});

    // 모달
    const [showModal, setShowModal] = useState(false);
    const [modalMsg, setModalMsg] = useState({title: "", body: "", variant: "success"});
    const [showDeleteModal, setShowDeleteModal] = useState(false);
    const [deleteTarget, setDeleteTarget] = useState(null);
    const [showHardDeleteModal, setShowHardDeleteModal] = useState(false);
    const [hardDeleteTarget, setHardDeleteTarget] = useState(null);

    const fetchFarms = async (page) => {
        if (loading) return;
        setLoading(true);
        try {
            const res = await getFarmList(page, 20);
            const newFarms = res.data.content || [];

            setFarms(prev => {
                const existingIds = new Set(prev.map(f => f.farmId));
                const filteredNew = newFarms.filter(f => !existingIds.has(f.farmId));
                return [...prev, ...filteredNew];
            });

            if (newFarms.length === 0) setHasMore(false);
        } catch (err) {
            console.error(err);
        }
        setLoading(false);
    };

    const reloadFarms = () => {
        setFarms([]);
        setPage(0);
        setHasMore(true);
        fetchFarms(0);
    };

    useEffect(() => {
        fetchFarms(page);
    }, [page]);

    // 전체 농장 RPi 에러 상태 주기적 체크 (5초마다, Spring Boot API로 DB 테이블 직접 조회)
    useEffect(() => {
        if (!farms.length) return;

        const checkAllFarms = async () => {
            const now = getServerNow();
            const errorMap = {};

            // 모든 농장을 병렬로 조회 (순차 대비 즉시 응답)
            const activeFarms = farms.filter(f => f.dlteYn !== "Y");
            const results = await Promise.allSettled(
                activeFarms.map(async (farm) => {
                    const housesRes = await getHouseList({farmId: farm.farmId});
                    const houses = (housesRes.data || []).filter(h => h.housId !== 0);
                    if (!houses.length) return {farmId: farm.farmId, errList: []};

                    const sensorRes = await getLatestSensorData(farm.farmId, houses[0].housId);
                    const sensorMap = sensorRes.data || {};

                    const errList = [];
                    for (const house of houses) {
                        const sensor = sensorMap[house.housId];
                        if (!sensor || !sensor.recdDttm) {
                            errList.push(house.housName || `${house.housId}호`);
                        } else {
                            const ageSec = (now - new Date(sensor.recdDttm)) / 1000;
                            if (ageSec > SENSOR_TIMEOUT_SEC) {
                                errList.push(house.housName || `${house.housId}호`);
                            }
                        }
                    }
                    return {farmId: farm.farmId, errList};
                })
            );

            for (const r of results) {
                if (r.status === "fulfilled" && r.value.errList.length > 0) {
                    errorMap[r.value.farmId] = r.value.errList;
                }
            }

            setFarmErrorMap(errorMap);

            // 에러 농장이 있으면 비프음 2회
            if (Object.keys(errorMap).length > 0) {
                playAlertBeep();
            }
        };

        checkAllFarms();
        const timer = setInterval(checkAllFarms, 5000);
        return () => clearInterval(timer);
    }, [farms]);

    const lastFarmRef = useCallback(
        (node) => {
            if (loading) return;
            if (observer.current) observer.current.disconnect();
            observer.current = new IntersectionObserver(entries => {
                if (entries[0].isIntersecting && hasMore) {
                    setPage(prev => prev + 1);
                }
            });
            if (node) observer.current.observe(node);
        },
        [loading, hasMore]
    );

    // soft delete
    const confirmDelete = (farm) => {
        setDeleteTarget(farm);
        setShowDeleteModal(true);
    };

    const handleDelete = async () => {
        setShowDeleteModal(false);
        try {
            await deleteFarm(deleteTarget.farmId);
            reloadFarms();
            setTimeout(() => {
                setModalMsg({title: "삭제 완료", body: `'${deleteTarget.farmName}' 농장이 삭제되었습니다.`, variant: "success"});
                setShowModal(true);
            }, 300);
        } catch (err) {
            setTimeout(() => {
                setModalMsg({title: "삭제 실패", body: err.message, variant: "danger"});
                setShowModal(true);
            }, 300);
        }
    };

    // restore
    const handleRestore = async (farmId) => {
        try {
            await restoreFarm(farmId);
            setModalMsg({title: "복원 완료", body: "농장이 복원되었습니다.", variant: "success"});
            reloadFarms();
        } catch (err) {
            setModalMsg({title: "복원 실패", body: err.message, variant: "danger"});
        }
        setShowModal(true);
    };

    // hard delete
    const confirmHardDelete = (farm) => {
        setHardDeleteTarget(farm);
        setShowHardDeleteModal(true);
    };

    const handleHardDelete = async () => {
        setShowHardDeleteModal(false);
        try {
            await hardDeleteFarm(hardDeleteTarget.farmId);
            reloadFarms();
            setTimeout(() => {
                setModalMsg({title: "완전 삭제 완료", body: `'${hardDeleteTarget.farmName}' 농장이 완전히 삭제되었습니다.`, variant: "success"});
                setShowModal(true);
            }, 300);
        } catch (err) {
            setTimeout(() => {
                setModalMsg({title: "완전 삭제 실패", body: err.message, variant: "danger"});
                setShowModal(true);
            }, 300);
        }
    };

    const filteredFarms = farms.filter(farm =>
        farm[searchField]?.toLowerCase().includes(search.toLowerCase())
    );

    return (
        <Container className="mt-2 pt-3">
            <Row className="mb-3">
                <Col xs={12} md={6}>
                    <InputGroup>
                        <Dropdown onSelect={(key) => setSearchField(key)}>
                            <Dropdown.Toggle variant="secondary" id="dropdown-search">
                                {searchField === "farmName" ? "농장이름" : "주소"}
                            </Dropdown.Toggle>
                            <Dropdown.Menu>
                                <Dropdown.Item eventKey="farmName">농장이름</Dropdown.Item>
                                <Dropdown.Item eventKey="addr">주소</Dropdown.Item>
                            </Dropdown.Menu>
                        </Dropdown>
                        <Form.Control
                            type="text"
                            placeholder={`${searchField === "farmName" ? "농장이름" : "주소"} 검색...`}
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                        />
                    </InputGroup>
                </Col>
            </Row>

            <Table striped bordered hover responsive>
                <thead>
                <tr>
                    {isAdmin && <th style={{width: "5%"}}>상태</th>}
                    <th style={{width: "5%"}}>ID</th>
                    <th style={{width: "20%"}}>농장 이름</th>
                    <th style={{width: "40%"}}>주소</th>
                    <th className="d-none d-md-table-cell" style={{width: "15%"}}>등록일</th>
                    {isAdmin && <th style={{width: "15%"}}>관리</th>}
                </tr>
                </thead>
                <tbody>
                {filteredFarms.map((farm, index) => {
                    const isDeleted = farm.dlteYn === "Y";
                    const errorHouses = farmErrorMap[farm.farmId] || [];
                    const hasRpiError = errorHouses.length > 0;

                    return (
                        <tr key={farm.farmId}
                            ref={filteredFarms.length === index + 1 ? lastFarmRef : null}
                            className={isDeleted ? "table-secondary" : ""}
                            style={{
                                cursor: "pointer",
                                backgroundColor: hasRpiError && !isDeleted ? "#fff0f0" : undefined,
                            }}>
                            {isAdmin && (
                                <td className="text-center" style={{verticalAlign: "middle"}}>
                                    {isDeleted ? (
                                        <span
                                            className="badge bg-danger"
                                            style={{cursor: "pointer"}}
                                            onClick={() => confirmHardDelete(farm)}
                                            title="완전삭제"
                                        >삭제</span>
                                    ) : hasRpiError ? (
                                        <span
                                            className="badge bg-danger"
                                            title={`에러: ${errorHouses.join(", ")}`}
                                            style={{cursor: "help"}}
                                        >에러</span>
                                    ) : (
                                        <span className="badge bg-success">정상</span>
                                    )}
                                </td>
                            )}
                            <td style={{
                                    verticalAlign: "middle",
                                    color: hasRpiError && !isDeleted ? "#dc3545" : "#198754",
                                    fontWeight: hasRpiError ? "bold" : "normal",
                                }}
                                onClick={() => {
                                    if (!isDeleted) {
                                        dispatch(setSelectedFarm({farmId: farm.farmId, farmName: farm.farmName}));
                                        navigate(`/farm/${farm.farmId}/monitor`);
                                    }
                                }}>
                                {farm.farmId}
                            </td>

                            <td style={{
                                    color: hasRpiError && !isDeleted ? "#dc3545" : undefined,
                                    fontWeight: hasRpiError ? "bold" : "normal",
                                }}
                                onClick={() => {
                                    if (!isDeleted) {
                                        dispatch(setSelectedFarm({farmId: farm.farmId, farmName: farm.farmName}));
                                        navigate(`/farm/${farm.farmId}/monitor`);
                                    }
                                }}>
                                <TruncatedOverlayTrigger
                                    tooltipId={farm.farmId}
                                    overlayText={hasRpiError ? `${farm.farmName} [에러: ${errorHouses.join(", ")}]` : farm.farmName}
                                    divText={farm.farmName}
                                    maxWidth="20vw"
                                />
                            </td>

                            <td style={{
                                    color: hasRpiError && !isDeleted ? "#dc3545" : undefined,
                                    fontWeight: hasRpiError ? "bold" : "normal",
                                }}
                                onClick={() => {
                                if (!isDeleted) {
                                    dispatch(setSelectedFarm({farmId: farm.farmId, farmName: farm.farmName}));
                                    navigate(`/farm/${farm.farmId}/monitor`);
                                }
                            }}>
                                <TruncatedOverlayTrigger
                                    tooltipId={farm.farmId}
                                    overlayText={farm.addr}
                                    divText={farm.addr}
                                    maxWidth="50vw"
                                />
                            </td>

                            <td className="d-none d-md-table-cell" style={{
                                    verticalAlign: "middle",
                                    color: hasRpiError && !isDeleted ? "#dc3545" : undefined,
                                    fontWeight: hasRpiError ? "bold" : "normal",
                                }}
                                onClick={() => {
                                    if (!isDeleted) {
                                        dispatch(setSelectedFarm({farmId: farm.farmId, farmName: farm.farmName}));
                                        navigate(`/farm/${farm.farmId}/monitor`);
                                    }
                                }}>
                                {new Date(farm.rgstDttm).toLocaleDateString()}
                            </td>

                            {isAdmin && (
                                <td className="text-nowrap" style={{verticalAlign: "middle"}}>
                                    {isDeleted ? (
                                        <Button size="sm" variant="outline-primary"
                                                onClick={() => handleRestore(farm.farmId)}>삭제취소</Button>
                                    ) : (
                                        <Button size="sm" variant="outline-danger"
                                                onClick={() => confirmDelete(farm)}>삭제</Button>
                                    )}
                                </td>
                            )}
                        </tr>
                    );
                })}
                </tbody>
            </Table>

            {loading && (
                <div className="text-center my-3">
                    <Spinner animation="border"/>
                </div>
            )}

            {!hasMore && !loading && (
                <div className="text-center text-muted mb-3">마지막 데이터입니다.</div>
            )}

            {/* 결과 알림 */}
            <AlertModal show={showModal} hideModalFunc={() => setShowModal(false)}
                        title={modalMsg.title} body={modalMsg.body} variant={modalMsg.variant}/>

            {/* 삭제 확인 */}
            <AlertModal show={showDeleteModal} hideModalFunc={() => setShowDeleteModal(false)}
                        onClickFunc={handleDelete}
                        title="농장 삭제"
                        body={`'${deleteTarget?.farmName}' 농장을 삭제하시겠습니까?`}
                        variant="danger" buttonMsg="삭제"/>

            {/* 완전 삭제 확인 */}
            <AlertModal show={showHardDeleteModal} hideModalFunc={() => setShowHardDeleteModal(false)}
                        onClickFunc={handleHardDelete}
                        title="농장 완전 삭제"
                        body={`'${hardDeleteTarget?.farmName}' 농장을 완전히 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.`}
                        variant="danger" buttonMsg="완전삭제"/>
        </Container>
    );
}
