import React, {useCallback, useEffect, useRef, useState} from "react";
import {Button, Spinner, Container} from "react-bootstrap";
import ChatSidebar from "../../components/ai/ChatSidebar.jsx";
import ChatMessageList from "../../components/ai/ChatMessageList.jsx";
import ChatInput from "../../components/ai/ChatInput.jsx";
import {streamQuery, ragPerform, ragSave} from "../../utils/aiChatUtil.js";

const SESSION_STORAGE_KEY = "ai_chat_session_id";

function generateSessionId() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return crypto.randomUUID();
    }
    return `sess_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

export default function AiChatPage() {
    const [messages, setMessages] = useState([]);
    const [currentInput, setCurrentInput] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [ragLoading, setRagLoading] = useState("");
    const [selectedFarm, setSelectedFarm] = useState(null);
    const [selectedHouse, setSelectedHouse] = useState(null);
    const [speechStyle, setSpeechStyle] = useState(() => localStorage.getItem("ai_chat_speech_style") || "male");
    const [modelAlert, setModelAlert] = useState(null);
    const fileInputRef = useRef(null);
    const contentRef = useRef(null);
    const abortControllerRef = useRef(null);
    const [buttonsLeft, setButtonsLeft] = useState(0);
    const [sessionId, setSessionId] = useState(() => {
        const stored = localStorage.getItem(SESSION_STORAGE_KEY);
        if (stored && stored.trim()) return stored;
        const created = generateSessionId();
        localStorage.setItem(SESSION_STORAGE_KEY, created);
        return created;
    });

    useEffect(() => {
        if (sessionId) {
            localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
        }
    }, [sessionId]);

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
        );

        abortControllerRef.current = controller;
    };

    const handleRagPerform = () => {
        fileInputRef.current?.click();
    };

    const handleFileSelected = async (e) => {
        const files = e.target.files;
        if (!files || files.length === 0) return;

        setRagLoading("perform");
        try {
            const res = await ragPerform(
                files,
                selectedFarm ? String(selectedFarm.farmId) : null,
            );
            const data = res.data;
            setMessages((prev) => [
                ...prev,
                {role: "assistant", content: data.success ? data.message : `RAG 수행 오류: ${data.message}`, timestamp: new Date()},
            ]);
        } catch (err) {
            setMessages((prev) => [
                ...prev,
                {role: "assistant", content: `RAG 수행 중 오류가 발생했습니다: ${err.message}`, timestamp: new Date()},
            ]);
        } finally {
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
            );
            const data = res.data;
            setMessages((prev) => [
                ...prev,
                {role: "assistant", content: data.success ? data.message : `RAG 저장 오류: ${data.message}`, timestamp: new Date()},
            ]);
        } catch (err) {
            setMessages((prev) => [
                ...prev,
                {role: "assistant", content: `RAG 저장 중 오류가 발생했습니다: ${err.message}`, timestamp: new Date()},
            ]);
        } finally {
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
        const nextSessionId = generateSessionId();
        setSessionId(nextSessionId);
        localStorage.setItem(SESSION_STORAGE_KEY, nextSessionId);
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
                <Button
                    variant="outline-primary"
                    size="sm"
                    onClick={handleRagPerform}
                    disabled={!!ragLoading}
                >
                    {ragLoading === "perform" ? <Spinner animation="border" size="sm"/> : "RAG수행"}
                </Button>
                <Button
                    variant="outline-primary"
                    size="sm"
                    onClick={handleRagSave}
                    disabled={!!ragLoading}
                >
                    {ragLoading === "save" ? <Spinner animation="border" size="sm"/> : "RAG저장"}
                </Button>
            </div>
            <Container style={{display: "flex", height: "calc(100vh - 56px)"}}>
                <ChatSidebar
                    selectedFarm={selectedFarm}
                    setSelectedFarm={setSelectedFarm}
                    selectedHouse={selectedHouse}
                    setSelectedHouse={setSelectedHouse}
                    onClearMessages={handleClearMessages}
                    speechStyle={speechStyle}
                    setSpeechStyle={setSpeechStyle}
                    modelAlert={modelAlert}
                    setModelAlert={setModelAlert}
                />
                <div ref={contentRef} style={{flex: 1, display: "flex", flexDirection: "column"}}>
                    <ChatMessageList messages={messages}/>
                    <ChatInput
                        value={currentInput}
                        onChange={setCurrentInput}
                        onSend={handleSend}
                        isLoading={isLoading}
                        farmName={selectedFarm?.farmName}
                    />
                </div>
            </Container>
        </>
    );
}
