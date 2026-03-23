import React, {useCallback, useEffect, useRef, useState} from "react";
import {Button, Spinner, Container} from "react-bootstrap";
import {useSelector} from "react-redux";
import ChatSidebar from "../../components/ai/ChatSidebar.jsx";
import ChatMessageList from "../../components/ai/ChatMessageList.jsx";
import ChatInput from "../../components/ai/ChatInput.jsx";
import {streamQuery, ragPerform, ragSave, getConversationHistory} from "../../utils/aiChatUtil.js";

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

    const [messages, setMessages] = useState(() => loadMessagesFromSession() || []);
    const [historyLoaded, setHistoryLoaded] = useState(() => !!sessionStorage.getItem(MESSAGES_STORAGE_KEY));
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
    const fileInputRef = useRef(null);
    const contentRef = useRef(null);
    const abortControllerRef = useRef(null);
    const ragAbortRef = useRef(null);
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
        if (userInfo.authLvel !== "ADMIN" && userInfo.authLvel !== "SYS_MONITOR" && userInfo.farmId) {
            const farmSid = `farm_${userInfo.farmId}`;
            setSessionId(prev => prev === farmSid ? prev : farmSid);
        }
    }, [userInfo?.authLvel, userInfo?.farmId]);

    // 메시지 변경 시 sessionStorage 동기화
    useEffect(() => {
        saveMessagesToSession(messages);
    }, [messages]);

    // 최초 로드 시 sessionStorage가 비어 있으면 서버에서 최근 10개 Q&A 조회
    useEffect(() => {
        if (historyLoaded) return;
        if (!sessionId) return;
        setHistoryLoaded(true);
        getConversationHistory(sessionId, 10)
            .then((res) => {
                const rows = res.data?.history || [];
                if (rows.length === 0) return;
                // user/assistant 쌍을 메시지 배열로 변환
                const restored = rows.map((r) => ({
                    role: r.role,
                    content: r.content,
                    timestamp: undefined,
                    _fromHistory: true,
                }));
                setMessages(restored);
            })
            .catch(() => { /* 서버 이력 없으면 빈 화면 유지 */ });
    }, [sessionId, historyLoaded]);

    // ADMIN/SYS_MONITOR만 localStorage에 세션 저장 (농장 사용자는 farm_id로 고정이므로 저장 불필요)
    useEffect(() => {
        if (sessionId && (!userInfo || userInfo.authLvel === "ADMIN" || userInfo.authLvel === "SYS_MONITOR")) {
            localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
        }
    }, [sessionId, userInfo?.authLvel]);

    useEffect(() => {
        localStorage.setItem("ai_chat_speech_style", speechStyle);
    }, [speechStyle]);

    useEffect(() => {
        return () => {
            if (abortControllerRef.current) {
                abortControllerRef.current.abort();
            }
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
        if (!query || isLoading) return;

        setMessages((prev) => [...prev, {role: "user", content: query, timestamp: new Date()}]);
        setCurrentInput("");
        setIsLoading(true);

        // 어시스턴트 메시지 플레이스홀더 추가
        setMessages((prev) => [...prev, {role: "assistant", content: ""}]);

        let tokenStarted = false;

        // auth_farm_id: RAG 파일 목록/삭제 권한 결정용
        // 시스템관리자 → null(전체 접근), SYS_MONITOR → null(전체 접근), 농장사용자 → 자기 farmId
        const authFarmId = (!userInfo || userInfo.authLvel === "ADMIN" || userInfo.authLvel === "SYS_MONITOR")
            ? null
            : userInfo.farmId ? String(userInfo.farmId) : null;

        const controller = streamQuery(
            query,
            selectedFarm ? String(selectedFarm.farmId) : null,
            selectedHouse ? String(selectedHouse.housId) : null,
            selectedFarm?.farmName || null,
            selectedHouse?.housName || null,
            sessionId,
            speechStyle,
            {
                onStatus: (text) => {
                    if (!tokenStarted) {
                        setMessages((prev) => {
                            const updated = [...prev];
                            updated[updated.length - 1] = {
                                ...updated[updated.length - 1],
                                content: text,
                            };
                            return updated;
                        });
                    }
                },
                onToken: (text) => {
                    if (!tokenStarted) {
                        tokenStarted = true;
                        setMessages((prev) => {
                            const updated = [...prev];
                            updated[updated.length - 1] = {
                                ...updated[updated.length - 1],
                                content: text,
                            };
                            return updated;
                        });
                    } else {
                        setMessages((prev) => {
                            const updated = [...prev];
                            const last = updated[updated.length - 1];
                            updated[updated.length - 1] = {
                                ...last,
                                content: last.content + text,
                            };
                            return updated;
                        });
                    }
                },
                onDone: (data) => {
                    const nextSessionId = data.session_id || sessionId;
                    setSessionId(nextSessionId);
                    setMessages((prev) => {
                        const updated = [...prev];
                        const last = updated[updated.length - 1];
                        updated[updated.length - 1] = {
                            ...last,
                            content: tokenStarted ? last.content : "",
                            sources: Array.isArray(data.sources) ? data.sources : [],
                            toolsUsed: Array.isArray(data.tools_used) ? data.tools_used : [],
                            responseType: data.response_type || "general",
                            elapsedSec: data.elapsed_sec ?? null,
                            sessionId: nextSessionId,
                            timestamp: new Date(),
                        };
                        return updated;
                    });
                    setIsLoading(false);
                    abortControllerRef.current = null;
                    // 모델 변경 알림이 있으면 응답 완료 시 자동 제거
                    setModelAlert(null);
                },
                onError: (errMsg) => {
                    setMessages((prev) => {
                        const updated = [...prev];
                        updated[updated.length - 1] = {
                            ...updated[updated.length - 1],
                            content: `응답 생성 중 오류가 발생했습니다: ${errMsg}`,
                            timestamp: new Date(),
                        };
                        return updated;
                    });
                    setIsLoading(false);
                    abortControllerRef.current = null;
                },
            },
            authFarmId,
        );

        abortControllerRef.current = controller;
    };

    const handleStop = () => {
        // 대화 스트리밍 중지
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
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
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
            abortControllerRef.current = null;
        }
        setIsLoading(false);
        setMessages([]);
        sessionStorage.removeItem(MESSAGES_STORAGE_KEY);
        if (!userInfo || userInfo.authLvel === "ADMIN" || userInfo.authLvel === "SYS_MONITOR") {
            // ADMIN/SYS_MONITOR: 새 UUID 세션 생성
            const nextSessionId = generateSessionId();
            setSessionId(nextSessionId);
            localStorage.setItem(SESSION_STORAGE_KEY, nextSessionId);
        }
        // 농장 사용자: farm_id 기반 세션 유지 (ID 변경 없음)
        setHistoryLoaded(true); // 이력 재조회 불필요 (화면만 초기화)
    };

    // 농장 변경 시 메시지 초기화 후 최근 10개 재조회
    const handleFarmChange = (farm) => {
        if (selectedFarm && farm && selectedFarm.farmId !== farm.farmId) {
            setMessages([]);
            sessionStorage.removeItem(MESSAGES_STORAGE_KEY);
            setHistoryLoaded(false); // 최근 10개 재조회 트리거
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
                    </>
                )}
            </div>
            <Container style={{display: "flex", height: "calc(100vh - 56px)"}}>
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
                />
                <div ref={contentRef} style={{flex: 1, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden"}}>
                    <ChatMessageList messages={messages}/>
                    <ChatInput
                        value={currentInput}
                        onChange={setCurrentInput}
                        onSend={handleSend}
                        isLoading={isLoading || !!ragLoading}
                        farmName={selectedFarm?.farmName}
                        onStop={handleStop}
                    />
                </div>
            </Container>
        </>
    );
}
