import {useQuery, useMutation, useQueryClient} from "@tanstack/react-query";
import {useMemo, useState} from "react";
import {Row, Col, Card, Form, OverlayTrigger, Tooltip} from "react-bootstrap";
import {InfoCircle} from "react-bootstrap-icons";
import axios from "axios";

import {getRelayStatus, patchRelayStatus} from "../../utils/relayUtil.js";
import {patchHouse} from "../../utils/houseUtil.js";
import RelayCard from "./RelayCard.jsx";
import AiJudgmentModal from "./AiJudgmentModal.jsx";
import LoadingPage from "../../pages/common/LoadingPage.jsx";
import ErrorPage from "../../pages/common/ErrorPage.jsx";

const AI_API_BASE = "/ai-api";

async function fetchAiJudgment(farmId, houseId) {
    try {
        const res = await axios.get(`${AI_API_BASE}/api/v1/ai-judgment/${farmId}/${houseId}`, {timeout: 5000});
        if (res.data && res.data.success) {
            return res.data;
        }
    } catch (e) {
        console.warn("AI 판단 조회 실패:", e.message);
    }
    return null;
}

export default function RelayDashboard({farmId, house, setSelectedHouse}) {
    const queryClient = useQueryClient();

    const [showAiModal, setShowAiModal] = useState(false);
    const [aiJudgment, setAiJudgment] = useState(null);
    const [toggledDeviceLabel, setToggledDeviceLabel] = useState("");

    const relayLabels = useMemo(() => {
        if (farmId == 1 && house.housId == 2) {
            // 릴레이 라벨(2동 임시)
            return [
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
            ];
        }
        // 릴레이 라벨(1, 3동)
        return [
            {label: "흡입팬(5)", num: 5},
            {label: "배출팬(6)", num: 6},
            {label: "순환밸브(10)", num: 10},
            {label: "흡입밸브(14)", num: 14},
            {label: "배출밸브(11)", num: 11},
            {label: "배수밸브(3)", num: 3},
            {label: "포그생성(순환모터)(2)", num: 2},
            {label: "조명(7)", num: 7},
            {label: "관수(8)", num: 8},
            {label: "수온히터(1)", num: 1},
            {label: "실내히터(9)", num: 9},
            {label: "히터밸브(15)", num: 15},
        ];
    }, [farmId, house.housId]);

    // relay 상태 조회 (polling)
    // gcTime: 0 → 재배사 전환 시 이전 캐시 즉시 삭제하여 깜빡임 방지
    const {data: relayStatus = {}, isLoading: isRelayLoading, error: relayError} = useQuery({
        queryKey: ["relayStatus", farmId, house.housId],
        queryFn: () => getRelayStatus(farmId, house.housId).then(res => res.data),
        refetchInterval: 5000,
        enabled: !!farmId && !!house.housId,
        gcTime: 0,
    });

    // relay toggle mutation
    const toggleRelayMutation = useMutation({
        mutationFn: (updatedStatus) => patchRelayStatus(farmId, house.housId, updatedStatus),
        onSuccess: () => queryClient.invalidateQueries(["relayStatus", farmId, house.housId]),
    });

    const handleToggleRelay = async (relayNum) => {
        const key = `relay${relayNum}stFlag`;
        const currentValue = relayStatus[key];
        const newValue = !currentValue;
        const updatedStatus = {...relayStatus, [key]: newValue};

        // 토글된 장치 라벨 찾기
        const item = relayLabels.find(r => r.num === relayNum);
        const deviceLabel = item ? item.label : `릴레이 ${relayNum}`;
        const actionLabel = newValue ? "ON" : "OFF";

        // 낙관적 업데이트 + 릴레이 토글
        queryClient.setQueryData(["relayStatus", farmId, house.housId], updatedStatus);
        toggleRelayMutation.mutate(updatedStatus);

        // 수동 모드에서만 AI 판단 팝업 표시
        if (!house.mnulCtrlFlag) {
            setToggledDeviceLabel(`${deviceLabel} → ${actionLabel}`);
            const judgment = await fetchAiJudgment(farmId, house.housId);
            if (judgment) {
                setAiJudgment(judgment);
                setShowAiModal(true);
            }
        }
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
            {/* 운용방식 카드 숨김 — 상단 그리드에서 선택 */}
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

            {/* AI 판단 팝업 모달 */}
            <AiJudgmentModal
                show={showAiModal}
                onHide={() => setShowAiModal(false)}
                judgment={aiJudgment}
                toggledDevice={toggledDeviceLabel}
            />
        </div>
    );
}
