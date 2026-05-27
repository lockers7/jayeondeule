import {useQuery, useMutation, useQueryClient} from "@tanstack/react-query";
import {useMemo, useRef, useState} from "react";
import {Row, Col, Card, Form, OverlayTrigger, Tooltip, Modal, Button} from "react-bootstrap";
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
    // [2026-04-27] 인터록 위반(밸브 OFF 차단 / 팬 ON 차단) 팝업 메시지
    const [interlockMessage, setInterlockMessage] = useState("");

    const relayLabels = useMemo(() => {
        if (farmId == 1 && house.housId == 2) {
            // 릴레이 라벨(2호 재배사) — [변경1 · 2026-04-19] 순환/흡기/배기/배수 +1 shift로
            // 웹 버튼 번호 = DB relay_N_flag 컬럼 번호 = 현장 장비가 모두 일치
            return [
                {label: "흡입팬(7)", num: 7},
                {label: "배출팬(8)", num: 8},
                {label: "순환밸브(10)", num: 10},   // [변경1] 9 → 10
                {label: "흡입밸브(11)", num: 11},   // [변경1] 10 → 11
                {label: "배출밸브(12)", num: 12},   // [변경1] 11 → 12
                {label: "배수밸브(13)", num: 13},   // [변경1] 12 → 13
                {label: "포그생성(2)", num: 2},
                {label: "조명(5)", num: 5},
                {label: "관수(6)", num: 6},
                {label: "수온히터(1)", num: 1},
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
            {label: "포그생성(2)", num: 2},
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

    // ════════════════════════════════════════════════════════════════════════
    // 흡입팬/배출팬 인터록 잔여시간 폴링 (1초)
    // 백엔드 GET /api/v1/rpi/interlock/{farm}/{house} → 카운트다운 표시용.
    // 실패해도 UI 깨지지 않도록 (data 없으면 카드는 잔여시간 미표시).
    // ════════════════════════════════════════════════════════════════════════
    const {data: interlockData} = useQuery({
        queryKey: ["interlock", farmId, house.housId],
        queryFn: async () => {
            const res = await axios.get(
                `${AI_API_BASE}/api/v1/rpi/interlock/${farmId}/${house.housId}`,
                {timeout: 3000},
            );
            return res.data;
        },
        refetchInterval: 1000,
        enabled: !!farmId && !!house.housId,
        gcTime: 0,
        retry: false,
    });

    // relayNum → 인터록 정보 매핑 (흡입팬·배출팬만)
    const fanInterlockByNum = useMemo(() => {
        if (!interlockData?.fans) return {};
        const intakeNum = (farmId == 1 && house.housId == 2) ? 7 : 5;
        const exhaustNum = (farmId == 1 && house.housId == 2) ? 8 : 6;
        return {
            [intakeNum]:  interlockData.fans.intake_fan_flag || null,
            [exhaustNum]: interlockData.fans.exhaust_fan_flag || null,
        };
    }, [interlockData, farmId, house.housId]);

    // 미사용 장치 비활성화 (UI 표시용 — 백엔드 force_off_unmapped_relays 가 항상 OFF 강제).
    //   1·3호(STANDARD): relay 9(실내히터)·15(히터밸브) 미사용
    //   2호(E타입):       relay 3(라디에이터)·4(칠러Ⅱ) 미사용 — 1·3호와 동일한 disable 패턴 적용
    const disabledRelayNums = useMemo(() => {
        if (farmId == 1 && house.housId == 2) return new Set([3, 4]);
        return new Set([9, 15]);
    }, [farmId, house.housId]);


    // relay toggle mutation
    // [2026-04-27] 응답에 interlock_violations 가 있으면 차단 팝업 표시 + 낙관적
    // 업데이트 롤백을 위해 즉시 invalidate (서버가 반환한 corrected 상태로 재조회).
    const toggleRelayMutation = useMutation({
        mutationFn: (updatedStatus) => patchRelayStatus(farmId, house.housId, updatedStatus),
        onSuccess: (response) => {
            queryClient.invalidateQueries(["relayStatus", farmId, house.housId]);
            const violations = response?.data?.interlockViolations || [];
            const blockedReasons = violations
                .filter(v => v.action === "off_blocked" || v.action === "on_blocked")
                .map(v => v.reason)
                .filter(Boolean);
            if (blockedReasons.length > 0) {
                setInterlockMessage(blockedReasons.join("\n\n"));
            }
        },
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
                        interlockInfo={fanInterlockByNum[item.num]}
                        disabledDevice={disabledRelayNums.has(item.num)}
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

            {/* [2026-04-27] 인터록 위반 차단 팝업 — 닫기 버튼 자동 포커스로
                스페이스바/Enter 즉시 닫기 가능 */}
            <InterlockBlockedModal
                message={interlockMessage}
                onHide={() => setInterlockMessage("")}
            />
        </div>
    );
}

// ════════════════════════════════════════════════════════════════════════════
// 인터록 위반(밸브 OFF 차단 / 팬 ON 차단) 안내 모달.
// onEntered 시점에 닫기 버튼에 포커스 → 사용자가 마우스 없이 스페이스바/Enter
// 만으로 즉시 닫을 수 있다. ESC 는 react-bootstrap 기본 동작으로 처리.
// ════════════════════════════════════════════════════════════════════════════
function InterlockBlockedModal({message, onHide}) {
    const closeBtnRef = useRef(null);
    if (!message) return null;
    return (
        <Modal show={!!message} onHide={onHide} centered
               onEntered={() => closeBtnRef.current && closeBtnRef.current.focus()}>
            <Modal.Header closeButton className="bg-warning bg-opacity-25">
                <Modal.Title>제어 차단</Modal.Title>
            </Modal.Header>
            <Modal.Body style={{whiteSpace: "pre-line"}}>
                {message}
            </Modal.Body>
            <Modal.Footer>
                <Button ref={closeBtnRef} variant="secondary" onClick={onHide}>닫기</Button>
            </Modal.Footer>
        </Modal>
    );
}
