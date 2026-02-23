import {useQuery, useMutation, useQueryClient} from "@tanstack/react-query";
import {useEffect, useState} from "react";
import {Row, Col, Card, Form, OverlayTrigger, Tooltip} from "react-bootstrap";
import {InfoCircle} from "react-bootstrap-icons";

import {getRelayStatus, patchRelayStatus} from "../../utils/relayUtil.js";
import {patchHouse} from "../../utils/houseUtil.js";
import RelayCard from "./RelayCard.jsx";
import LoadingPage from "../../pages/common/LoadingPage.jsx";
import ErrorPage from "../../pages/common/ErrorPage.jsx";

export default function RelayDashboard({farmId, house, setSelectedHouse}) {
    const queryClient = useQueryClient();

    const [relayLabels, setRelayLabels] = useState([]);

    useEffect(() => {
        if (farmId == 1 && house.housId == 2) {
            // 릴레이 라벨(2동 임시)
            setRelayLabels([
                {label: "흡입팬(7)", num: 7},
                {label: "배출팬(8)", num: 8},
                {label: "순환밸브(9)", num: 9},
                {label: "흡입밸브(10)", num: 10},
                {label: "배출밸브(11)", num: 11},
                {label: "배수밸브(12)", num: 12},
                {label: "포그생성(순환모터)(2)", num: 2},
                {label: "조명(5)", num: 5},
                {label: "관수(6)", num: 6},
                {label: "칠러Ⅰ(1)", num: 1},
                {label: "칠러Ⅱ(4)", num: 4},
                {label: "라디에이터(3)", num: 3},
            ]);
        } else {
            // 릴레이 라벨(1, 3동)
            setRelayLabels([
                {label: "흡입팬(5)", num: 5},
                {label: "배출팬(6)", num: 6},
                {label: "순환밸브(10)", num: 10},
                {label: "흡입밸브(11)", num: 11},
                {label: "배출밸브(14)", num: 14},
                {label: "배수밸브(3)", num: 3},
                {label: "포그생성(순환모터)(2)", num: 2},
                {label: "조명(7)", num: 7},
                {label: "관수(8)", num: 8},
                {label: "수온히터(1)", num: 1},
                {label: "실내히터(9)", num: 9},
                {label: "히터밸브(15)", num: 15},
            ]);
        }
    }, [house])

    // relay 상태 조회 (polling)
    const {data: relayStatus = {}, isLoading: isRelayLoading, error: relayError} = useQuery({
        queryKey: ["relayStatus", farmId, house.housId],
        queryFn: () => getRelayStatus(farmId, house.housId).then(res => res.data),
        refetchInterval: 5000,
        enabled: !!farmId && !!house.housId,
    });

    // relay toggle mutation
    const toggleRelayMutation = useMutation({
        mutationFn: (updatedStatus) => patchRelayStatus(farmId, house.housId, updatedStatus),
        onSuccess: () => queryClient.invalidateQueries(["relayStatus", farmId, house.housId]),
    });

    const handleToggleRelay = (relayNum) => {
        const key = `relay${relayNum}stFlag`;
        const updatedStatus = {...relayStatus, [key]: !relayStatus[key]};
        queryClient.setQueryData(["relayStatus", farmId, house.housId], updatedStatus);
        toggleRelayMutation.mutate(updatedStatus);
    };

    // 수동/자동 모드 mutation
    const toggleModeMutation = useMutation({
        mutationFn: (updatedHouse) => patchHouse({farmId, ...updatedHouse}),
        onSuccess: async () => {
            await queryClient.invalidateQueries(["houses", farmId]);
            const newHouses = queryClient.getQueryData(["houses", farmId]);
            if (newHouses) {
                const newHouse = newHouses.find(h => h.housId === house.housId);
                if (newHouse) setSelectedHouse(newHouse);
            }
        },
    });

    const getOperationMode = () => {
        if (!house.mnulCtrlFlag) return "manual";
        if (house.ctrlType === "ai") return "ai";
        return "algorithm";
    };

    const handleModeChange = (e) => {
        const mode = e.target.value;
        let mnulCtrlFlag, ctrlType;
        if (mode === "manual") { mnulCtrlFlag = false; ctrlType = "algorithm"; }
        else if (mode === "ai") { mnulCtrlFlag = true; ctrlType = "ai"; }
        else { mnulCtrlFlag = true; ctrlType = "algorithm"; }
        toggleModeMutation.mutate({...house, mnulCtrlFlag, ctrlType});
    };

    const modeCardBorder = () => {
        const mode = getOperationMode();
        if (mode === "manual") return "border-warning";
        if (mode === "ai") return "border-primary";
        return "border-success";
    };

    if (isRelayLoading) return <LoadingPage/>;
    if (relayError) return <ErrorPage/>;

    return (
        <div>
            <Row className="mt-4 d-flex justify-content-center">
                <Col xs="auto" key={house.housId} className="mb-3">
                    <Card className={`text-center shadow-sm ${modeCardBorder()}`}>
                        <Card.Body className="position-relative">
                            <div style={{position: "absolute", top: "0.2rem", right: "0.35rem", zIndex: 10}}>
                                <OverlayTrigger
                                    placement="top"
                                    overlay={
                                        <Tooltip id={`tooltip-info`}>
                                            인공지능: AI가 릴레이를 자동 제어합니다.<br/>
                                            알고리즘: 센서 기반 알고리즘이 자동 제어합니다.<br/>
                                            수동제어: 개별 릴레이를 직접 제어할 수 있습니다.
                                        </Tooltip>
                                    }
                                >
                                    <InfoCircle size={16}/>
                                </OverlayTrigger>
                            </div>
                            <Card.Title className="mb-2">운용방식</Card.Title>
                            <Form.Select
                                value={getOperationMode()}
                                onChange={handleModeChange}
                                disabled={toggleModeMutation.isPending}
                                style={{padding: "4px 2.75rem 4px 8px", width: "fit-content", margin: "0 auto"}}
                            >
                                <option value="ai">인공지능</option>
                                <option value="algorithm">알고리즘</option>
                                <option value="manual">수동제어</option>
                            </Form.Select>
                        </Card.Body>
                    </Card>
                </Col>
            </Row>
            <hr/>
            <Row>
                {relayLabels.map((item) => (
                    <RelayCard
                        key={item.num}
                        label={item.label}
                        relayNum={item.num}
                        relayStatus={relayStatus}
                        manualMode={!house.mnulCtrlFlag}
                        handleToggle={handleToggleRelay}
                        toggleRelayMutation={toggleRelayMutation}
                    />
                ))}
            </Row>
        </div>
    );
}
