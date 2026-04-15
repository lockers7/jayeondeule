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
                            case "done":    onDone?.(event);           break;
                            case "error":   onError?.(event.content);  break;
                        }
                    } catch { /* non-JSON line, skip */ }
                }
            }

            function pump() {
                reader.read().then(({done, value}) => {
                    if (done) {
                        if (buffer.trim()) processLines();
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
