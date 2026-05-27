import React, {useCallback, useEffect, useRef, useState} from "react";
import {Button, Spinner, Container} from "react-bootstrap";
import {useSelector} from "react-redux";
import {useNavigate} from "react-router-dom";
import ChatSidebar from "../../components/ai/ChatSidebar.jsx";
import ChatMessageList from "../../components/ai/ChatMessageList.jsx";
import ChatInput from "../../components/ai/ChatInput.jsx";
import {ragPerform, ragSave, getConversationHistory} from "../../utils/aiChatUtil.js";
import * as streamManager from "../../utils/aiChatStreamManager.js";
import "./AiChatPage.css";

const SESSION_STORAGE_KEY = "ai_chat_session_id";
const MESSAGES_STORAGE_KEY = "ai_chat_messages";

function generateSessionId() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return crypto.randomUUID();
    }
    return `sess_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

// sessionStorage에서 메시지 복원 (날짜 문자열 → Date 변환)
function loadMessagesFromSession() {
    try {
        const raw = sessionStorage.getItem(MESSAGES_STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return parsed.map(m => ({...m, timestamp: m.timestamp ? new Date(m.timestamp) : undefined}));
    } catch {
        return null;
    }
}

function saveMessagesToSession(msgs) {
    try {
        sessionStorage.setItem(MESSAGES_STORAGE_KEY, JSON.stringify(msgs));
    } catch { /* 무시 */ }
}

export default function AiChatPage() {
    const userInfo = useSelector(state => state.auth.userInfo);
    const globalSelectedFarm = useSelector(state => state.auth.selectedFarm);
    const isAdmin = userInfo?.authLvel === "ADMIN";
    const isSysMonitor = userInfo?.authLvel === "SYS_MONITOR";
    const isMonitor = isSysMonitor || userInfo?.authLvel === "FARM_MONITOR";

    const [messages, setMessages] = useState([]);   // ⛔ 브라우저 글로벌 캐시 복원 금지(사용자 혼입 방지) — 서버에서 사용자별 이력 로드
    const loadedSessionRef = useRef(null);            // 서버 대화이력을 로드한 session 추적(사용자별 격리)
    const [currentInput, setCurrentInput] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [ragLoading, setRagLoading] = useState("");
    const [selectedFarm, setSelectedFarm] = useState(null);
    const [selectedHouse, setSelectedHouse] = useState(null);

    // ADMIN/SYS_MONITOR: Redux selectedFarm 변경 시 로컬 상태 동기화 (헤더 선택 농장 = 절대 기준)
    useEffect(() => {
        if ((isAdmin || isSysMonitor) && globalSelectedFarm?.farmId != null) {
            setSelectedFarm(prev => {
                if (prev?.farmId === globalSelectedFarm.farmId) return prev;
                setSelectedHouse(null); // 농장 변경 시 재배사 선택 초기화
                return globalSelectedFarm;
            });
        }
    }, [isAdmin, isSysMonitor, globalSelectedFarm?.farmId]);
    const [speechStyle, setSpeechStyle] = useState(() => localStorage.getItem("ai_chat_speech_style") || "male");
    const [modelAlert, setModelAlert] = useState(null);
    const [isModelChanging, setIsModelChanging] = useState(false);
    const fileInputRef = useRef(null);
    const contentRef = useRef(null);
    const abortControllerRef = useRef(null);
    const ragAbortRef = useRef(null);
    const navigate = useNavigate();
    const [buttonsLeft, setButtonsLeft] = useState(0);
    const [sessionId, setSessionId] = useState(() => {
        // ADMIN 또는 userInfo 미확정: localStorage 기반 UUID 세션 (현행)
        const stored = localStorage.getItem(SESSION_STORAGE_KEY);
        if (stored && stored.trim()) return stored;
        const created = generateSessionId();
        localStorage.setItem(SESSION_STORAGE_KEY, created);
        return created;
    });

    // userInfo 확정 시 세션 ID 결정
    // ADMIN: localStorage UUID 유지 (현행)
    // 농장 사용자: farm_id 기반 고정 세션 (브라우저 무관, 동일 농장 = 동일 세션)
    useEffect(() => {
        if (!userInfo) return;
        // ⛔ 대화이력은 로그인 사용자별로 격리한다 — 브라우저 공유 UUID 금지(다른 관리자 대화가
        //   보이던 버그 수정, 2026-07-26). 로그인 ID(userId) 기반 고정 세션 → 같은 브라우저라도
        //   사용자가 다르면 세션이 달라 서버가 각자의 이력만 반환한다.
        const sid = (userInfo.userId != null && String(userInfo.userId).trim())
            ? `user_${userInfo.userId}`
            : (userInfo.farmId != null ? `farm_${userInfo.farmId}` : null);
        if (sid) setSessionId(prev => prev === sid ? prev : sid);
    }, [userInfo?.userId, userInfo?.farmId]);

    // 메시지 변경 시 sessionStorage 동기화
    useEffect(() => {
        saveMessagesToSession(messages);
    }, [messages]);

    // 최초 로드 시 sessionStorage가 비어 있으면 서버에서 최근 10개 Q&A 조회
    useEffect(() => {
        if (!sessionId) return;
        // 사용자 확정(userInfo) 전 초기 UUID 세션으로는 로드하지 않는다 — 사용자별 세션 확정 후 로드.
        if (!userInfo) return;
        if (loadedSessionRef.current === sessionId) return;   // 이 세션(=사용자)은 이미 로드함
        loadedSessionRef.current = sessionId;
        setMessages([]);                                       // 세션(사용자) 전환 시 이전 사용자 대화 잔여 제거
        getConversationHistory(sessionId, 10)
            .then((res) => {
                const rows = res.data?.history || [];
                if (rows.length === 0) return;
                setMessages(rows.map((r) => ({
                    role: r.role, content: r.content, timestamp: undefined, _fromHistory: true,
                })));
            })
            .catch(() => { /* 서버 이력 없으면 빈 화면 유지 */ });
    }, [sessionId, userInfo]);

    // ADMIN/SYS_MONITOR만 localStorage에 세션 저장 (농장 사용자는 farm_id로 고정이므로 저장 불필요)
    useEffect(() => {
        if (sessionId && (!userInfo || userInfo.authLvel === "ADMIN" || userInfo.authLvel === "SYS_MONITOR")) {
            localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
        }
    }, [sessionId, userInfo?.authLvel]);

    useEffect(() => {
        localStorage.setItem("ai_chat_speech_style", speechStyle);
    }, [speechStyle]);

    // 스트림 매니저 리스너 등록/해제 + 재마운트 시 상태 복원
    useEffect(() => {
        // 리스너: 매니저에서 스트림 이벤트를 받아 React 상태에 반영
        const listener = (type, payload) => {
            if (type === "status") {
                setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last?.role === "assistant" && !last._tokenStarted) {
                        updated[updated.length - 1] = { ...last, content: payload };
                    }
                    return updated;
                });
            } else if (type === "token") {
                setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last?.role === "assistant") {
                        updated[updated.length - 1] = { ...last, content: payload.content, _tokenStarted: true };
                    }
                    return updated;
                });
            } else if (type === "done") {
                const data = payload;
                const nextSessionId = data.session_id || sessionId;
                setSessionId(nextSessionId);
                setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last?.role === "assistant") {
                        updated[updated.length - 1] = {
                            ...last,
                            content: last._tokenStarted ? last.content : "",
                            sources: Array.isArray(data.sources) ? data.sources : [],
                            toolsUsed: Array.isArray(data.tools_used) ? data.tools_used : [],
                            responseType: data.response_type || "general",
                            elapsedSec: data.elapsed_sec ?? null,
                            sessionId: nextSessionId,
                            timestamp: new Date(),
                        };
                    }
                    return updated;
                });
                setIsLoading(false);
                abortControllerRef.current = null;
                setModelAlert(null);
            } else if (type === "error") {
                setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last?.role === "assistant") {
                        updated[updated.length - 1] = {
                            ...last,
                            content: `응답 생성 중 오류가 발생했습니다: ${payload}`,
                            timestamp: new Date(),
                        };
                    }
                    return updated;
                });
                setIsLoading(false);
                abortControllerRef.current = null;
            }
        };

        streamManager.subscribe(listener);

        // 재마운트 시: 매니저에 진행 중이거나 완료된 스트림이 있으면 복원
        const snapshot = streamManager.getSnapshot();
        if (snapshot) {
            if (snapshot.active) {
                // 스트림 진행 중 — 로딩 상태 복원, 현재까지 누적된 내용 반영
                setIsLoading(true);
                setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last?.role === "assistant") {
                        updated[updated.length - 1] = { ...last, content: snapshot.content, _tokenStarted: snapshot.tokenStarted };
                    }
                    return updated;
                });
            } else if (snapshot.doneData) {
                // 스트림 완료됨 (부재 중 완료) — 최종 결과 반영
                const data = snapshot.doneData;
                const nextSessionId = data.session_id || sessionId;
                setSessionId(nextSessionId);
                setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last?.role === "assistant") {
                        updated[updated.length - 1] = {
                            ...last,
                            content: snapshot.content || "",
                            sources: Array.isArray(data.sources) ? data.sources : [],
                            toolsUsed: Array.isArray(data.tools_used) ? data.tools_used : [],
                            responseType: data.response_type || "general",
                            elapsedSec: data.elapsed_sec ?? null,
                            sessionId: nextSessionId,
                            timestamp: new Date(),
                        };
                    }
                    return updated;
                });
                setIsLoading(false);
                streamManager.consumeCompleted();
            } else if (snapshot.errorMsg) {
                // 에러로 종료됨 — 에러 메시지 반영
                setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last?.role === "assistant") {
                        updated[updated.length - 1] = {
                            ...last,
                            content: `응답 생성 중 오류가 발생했습니다: ${snapshot.errorMsg}`,
                            timestamp: new Date(),
                        };
                    }
                    return updated;
                });
                setIsLoading(false);
                streamManager.consumeCompleted();
            }
        }

        return () => {
            streamManager.unsubscribe();
        };
    }, []);

    const updateButtonPosition = useCallback(() => {
        if (contentRef.current) {
            const rect = contentRef.current.getBoundingClientRect();
            setButtonsLeft(rect.left + 10);
        }
    }, []);

    useEffect(() => {
        updateButtonPosition();
        window.addEventListener("resize", updateButtonPosition);
        return () => window.removeEventListener("resize", updateButtonPosition);
    }, [updateButtonPosition]);

    const handleSend = (directText) => {
        const query = (directText || currentInput).trim();
        if (!query) return;
        // 이전 스트림 진행 중이면 자동 취소 후 새 질문 전송
        if (isLoading && abortControllerRef.current) {
            abortControllerRef.current.abort();
            abortControllerRef.current = null;
        }

        setMessages((prev) => [...prev, {role: "user", content: query, timestamp: new Date()}]);
        setCurrentInput("");
        setIsLoading(true);

        // 어시스턴트 메시지 플레이스홀더 추가
        setMessages((prev) => [...prev, {role: "assistant", content: ""}]);

        // auth_farm_id: RAG 파일 목록/삭제 권한 결정용
        const authFarmId = (!userInfo || userInfo.authLvel === "ADMIN" || userInfo.authLvel === "SYS_MONITOR")
            ? null
            : userInfo.farmId ? String(userInfo.farmId) : null;

        // 스트림 매니저를 통해 시작 — 페이지 이동해도 스트림 유지
        const controller = streamManager.startStream(
            query,
            selectedFarm ? String(selectedFarm.farmId) : null,
            selectedHouse ? String(selectedHouse.housId) : null,
            selectedFarm?.farmName || null,
            selectedHouse?.housName || null,
            sessionId,
            speechStyle,
            authFarmId,
        );

        abortControllerRef.current = controller;
    };

    const handleStop = () => {
        // 대화 스트리밍 중지 (매니저를 통해)
        if (streamManager.isActive() || abortControllerRef.current) {
            streamManager.abortStream();
            abortControllerRef.current = null;
            setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === "assistant") {
                    updated[updated.length - 1] = {
                        ...last,
                        content: (last.content || "") + "\n\n_(응답이 중지되었습니다.)_",
                        timestamp: new Date(),
                    };
                }
                return updated;
            });
            setIsLoading(false);
        }
        // RAG 중지
        if (ragAbortRef.current) {
            ragAbortRef.current.abort();
            ragAbortRef.current = null;
            setRagLoading("");
        }
    };

    const handleRagPerform = () => {
        fileInputRef.current?.click();
    };

    const handleFileSelected = async (e) => {
        const files = e.target.files;
        if (!files || files.length === 0) return;

        setRagLoading("perform");
        const controller = new AbortController();
        ragAbortRef.current = controller;
        try {
            const res = await ragPerform(
                files,
                selectedFarm ? String(selectedFarm.farmId) : null,
                controller.signal,
            );
            const data = res.data;
            setMessages((prev) => [
                ...prev,
                {role: "assistant", content: data.success ? data.message : `RAG 수행 오류: ${data.message}`, timestamp: new Date()},
            ]);
        } catch (err) {
            if (err.name === "CanceledError" || err.code === "ERR_CANCELED") return;
            setMessages((prev) => [
                ...prev,
                {role: "assistant", content: `RAG 수행 중 오류가 발생했습니다: ${err.message}`, timestamp: new Date()},
            ]);
        } finally {
            ragAbortRef.current = null;
            setRagLoading("");
            e.target.value = "";
        }
    };

    const handleRagSave = async () => {
        if (messages.length === 0) {
            setMessages((prev) => [
                ...prev,
                {role: "assistant", content: "저장할 대화 내용이 없습니다.", timestamp: new Date()},
            ]);
            return;
        }

        setRagLoading("save");
        const controller = new AbortController();
        ragAbortRef.current = controller;
        try {
            const compactMessages = messages.map((msg) => ({
                role: msg.role,
                content: msg.content,
            }));
            const res = await ragSave(
                compactMessages,
                selectedFarm ? String(selectedFarm.farmId) : null,
                selectedFarm?.farmName || null,
                selectedHouse?.housName || null,
                controller.signal,
            );
            const data = res.data;
            setMessages((prev) => [
                ...prev,
                {role: "assistant", content: data.success ? data.message : `RAG 저장 오류: ${data.message}`, timestamp: new Date()},
            ]);
        } catch (err) {
            if (err.name === "CanceledError" || err.code === "ERR_CANCELED") return;
            setMessages((prev) => [
                ...prev,
                {role: "assistant", content: `RAG 저장 중 오류가 발생했습니다: ${err.message}`, timestamp: new Date()},
            ]);
        } finally {
            ragAbortRef.current = null;
            setRagLoading("");
        }
    };

    const handleClearMessages = () => {
        streamManager.abortStream();
        abortControllerRef.current = null;
        setIsLoading(false);
        setMessages([]);
        sessionStorage.removeItem(MESSAGES_STORAGE_KEY);
        if (!userInfo || userInfo.authLvel === "ADMIN" || userInfo.authLvel === "SYS_MONITOR") {
            // ADMIN/SYS_MONITOR: 새 빈 세션(UUID) 생성 — 새 대화 스레드
            const nextSessionId = generateSessionId();
            loadedSessionRef.current = nextSessionId; // 새 세션은 재조회 불필요(빈 이력)
            setSessionId(nextSessionId);
            localStorage.setItem(SESSION_STORAGE_KEY, nextSessionId);
        } else {
            // 농장 사용자: farm_id 기반 세션 유지 — 현재 세션 재조회 방지(화면만 초기화)
            loadedSessionRef.current = sessionId;
        }
    };

    // 농장 변경 시 메시지 초기화 후 최근 10개 재조회
    const handleFarmChange = (farm) => {
        if (selectedFarm && farm && selectedFarm.farmId !== farm.farmId) {
            setMessages([]);
            sessionStorage.removeItem(MESSAGES_STORAGE_KEY);
            loadedSessionRef.current = null; // 재조회 트리거(현재 세션 이력 다시 로드)
        }
        setSelectedFarm(farm);
    };

    return (
        <>
            {/* RAG 버튼: fixed로 Header 첫라인에 표시, 좌측은 채팅영역 좌측과 정렬 */}
            <div style={{
                position: "fixed",
                top: "10px",
                left: `${buttonsLeft}px`,
                zIndex: 1031,
                display: "flex",
                gap: "8px",
            }}>
                <input
                    type="file"
                    ref={fileInputRef}
                    onChange={handleFileSelected}
                    accept=".txt,.md,.csv,.json,.pdf"
                    multiple
                    style={{display: "none"}}
                />
                {!isMonitor && (
                    <>
                        <Button
                            variant="outline-primary"
                            size="sm"
                            onClick={handleRagPerform}
                            disabled={!!ragLoading || isLoading}
                        >
                            {ragLoading === "perform" ? <Spinner animation="border" size="sm"/> : "RAG수행"}
                        </Button>
                        <Button
                            variant="outline-primary"
                            size="sm"
                            onClick={handleRagSave}
                            disabled={!!ragLoading || isLoading}
                        >
                            {ragLoading === "save" ? <Spinner animation="border" size="sm"/> : "RAG저장"}
                        </Button>
                        {isAdmin && (
                            // ⛔ 주식자동매매 = 시스템관리자(ADMIN) 전용 — 프롬프트관리·룰후보·
                            //   Agent이력·LLM제어관리 메뉴와 동일 권한(authLvel==='ADMIN'). 그 외 숨김.
                            <Button
                                variant="outline-success"
                                size="sm"
                                onClick={() => window.open("/stock-trading", "stock_trading_window")}
                            >
                                주식자동매매
                            </Button>
                        )}
                    </>
                )}
            </div>
            <Container className="ai-chat-container">
                <ChatSidebar
                    selectedFarm={selectedFarm}
                    setSelectedFarm={handleFarmChange}
                    selectedHouse={selectedHouse}
                    setSelectedHouse={setSelectedHouse}
                    onClearMessages={handleClearMessages}
                    speechStyle={speechStyle}
                    setSpeechStyle={setSpeechStyle}
                    modelAlert={modelAlert}
                    setModelAlert={setModelAlert}
                    isModelChanging={isModelChanging}
                    setIsModelChanging={setIsModelChanging}
                />
                <div ref={contentRef} style={{flex: 1, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden"}}>
                    <ChatMessageList messages={messages}/>
                    <ChatInput
                        value={currentInput}
                        onChange={setCurrentInput}
                        onSend={handleSend}
                        isLoading={isLoading || !!ragLoading || isModelChanging}
                        farmName={selectedFarm?.farmName}
                        onStop={handleStop}
                    />
                </div>
            </Container>
        </>
    );
}
