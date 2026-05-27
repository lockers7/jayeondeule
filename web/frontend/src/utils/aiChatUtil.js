import axios from "axios";

const aiApi = axios.create({
    baseURL: "/ai-api",
});

export async function sendQuery(query, farmId, houseId, farmName, houseName, sessionId) {
    return aiApi.post("/api/v1/query", {
        query,
        session_id: sessionId || null,
        farm_id: farmId,
        house_id: houseId,
        farm_name: farmName,
        house_name: houseName,
    });
}

/**
 * SSE 스트리밍 질의 — 실시간 status/token/done 이벤트를 콜백으로 전달
 * @returns {AbortController} 스트림 중단용 컨트롤러
 */
export function streamQuery(query, farmId, houseId, farmName, houseName, sessionId, speechStyle, callbacks, authFarmId) {
    const {onStatus, onToken, onDone, onError} = callbacks;
    const controller = new AbortController();

    fetch("/ai-api/api/v1/query/stream", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            query,
            session_id: sessionId || null,
            farm_id: farmId,
            house_id: houseId,
            farm_name: farmName,
            house_name: houseName,
            speech_style: speechStyle || "male",
            auth_farm_id: authFarmId !== undefined ? authFarmId : null,
        }),
        signal: controller.signal,
    })
        .then((response) => {
            if (!response.ok) {
                throw new Error(`서버 응답 오류 (HTTP ${response.status})`);
            }
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            let doneEventReceived = false;

            function processLines() {
                const lines = buffer.split("\n");
                buffer = lines.pop() || "";
                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed || !trimmed.startsWith("data: ")) continue;
                    const payload = trimmed.slice(6);
                    if (payload === "[DONE]") return;
                    try {
                        const event = JSON.parse(payload);
                        switch (event.type) {
                            case "status":  onStatus?.(event.content); break;
                            case "token":   onToken?.(event.content);  break;
                            case "done":    doneEventReceived = true; onDone?.(event); break;
                            case "error":   onError?.(event.content);  break;
                        }
                    } catch { /* non-JSON line, skip */ }
                }
            }

            function pump() {
                reader.read().then(({done, value}) => {
                    if (done) {
                        if (buffer.trim()) processLines();
                        // 서버가 done 이벤트 없이 스트림을 종료한 경우 강제 완료 처리
                        if (!doneEventReceived) {
                            onDone?.({type: "done"});
                        }
                        return;
                    }
                    buffer += decoder.decode(value, {stream: true});
                    processLines();
                    pump();
                }).catch((err) => {
                    if (err.name !== "AbortError") {
                        onError?.(err.message || "스트리밍 연결 오류");
                    }
                });
            }

            pump();
        })
        .catch((err) => {
            if (err.name !== "AbortError") {
                onError?.(err.message || "스트리밍 연결 오류");
            }
        });

    return controller;
}

export async function ragPerform(files, farmId, signal) {
    const formData = new FormData();
    for (const file of files) {
        formData.append("files", file);
    }
    if (farmId) formData.append("farm_id", farmId);
    return aiApi.post("/api/v1/rag/perform", formData, {
        headers: {"Content-Type": "multipart/form-data"},
        signal,
    });
}

export async function ragSave(messages, farmId, farmName, houseName, signal) {
    return aiApi.post("/api/v1/rag/save", {
        messages,
        farm_id: farmId,
        farm_name: farmName,
        house_name: houseName,
    }, {signal});
}

export async function getConversationHistory(sessionId, limit = 10) {
    return aiApi.get("/api/v1/conversation/history", {
        params: { session_id: sessionId, limit },
    });
}

// ── 주식 자동매매 API (수치=PostgreSQL trading_*, 판단·분석·학습=전용 VectorDB) ──
export const tradingCandidates = () => aiApi.get("/api/v1/trading/candidates");
export const tradingPerformance = () => aiApi.get("/api/v1/trading/performance");
export const tradingRun = () => aiApi.post("/api/v1/trading/run", {});
export const tradingGetPrompt = () => aiApi.get("/api/v1/trading/prompt");
export const tradingSetPrompt = (prompt) => aiApi.post("/api/v1/trading/prompt", {prompt});
export const tradingGetUserdata = () => aiApi.get("/api/v1/trading/userdata");
export const tradingSetUserdata = (data) => aiApi.post("/api/v1/trading/userdata", {data});
export const tradingAnalysis = (query) => aiApi.get("/api/v1/trading/analysis", {params: {query}});
export const tradingLearning = () => aiApi.get("/api/v1/trading/learning");
export const tradingLearn = (summary) => aiApi.post("/api/v1/trading/learn", {summary});

// ── Phase 2/3: 관리자 컨트롤(전략·제외·승인) + 최신 방법론(트렌드) + 자가개선 ──
export const tradingStrategies = () => aiApi.get("/api/v1/trading/strategies");
export const tradingSaveStrategy = (name, prompt_text) => aiApi.post("/api/v1/trading/strategies", {name, prompt_text});
export const tradingActivateStrategy = (name) => aiApi.post("/api/v1/trading/strategy/activate", {name});
export const tradingCandidateStatus = (stock_code, status, scan_date) => aiApi.post("/api/v1/trading/candidate/status", {stock_code, status, scan_date});
export const tradingGetExclusions = () => aiApi.get("/api/v1/trading/exclusions");
export const tradingSetExclusions = (exclusions) => aiApi.post("/api/v1/trading/exclusions", {exclusions});
export const tradingControlContext = () => aiApi.get("/api/v1/trading/control-context");
export const tradingTrends = () => aiApi.get("/api/v1/trading/trends");
export const tradingSeedTrends = (force) => aiApi.post("/api/v1/trading/seed-trends", {force});
export const tradingLearnPerformance = () => aiApi.post("/api/v1/trading/learn-performance", {});
// 3종 개선: 포트폴리오 집중도 · 팩터 컨빅션 가중치
export const tradingPortfolio = (status) => aiApi.get("/api/v1/trading/portfolio", {params: status ? {status} : {}});
export const tradingGetFactorWeights = () => aiApi.get("/api/v1/trading/factor-weights");
export const tradingSetFactorWeights = (weights) => aiApi.post("/api/v1/trading/factor-weights", {weights});
