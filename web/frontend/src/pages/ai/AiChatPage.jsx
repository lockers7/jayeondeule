import React, {useCallback, useEffect, useRef, useState} from "react";
import {Button, Spinner, Container} from "react-bootstrap";
import ChatSidebar from "../../components/ai/ChatSidebar.jsx";
import ChatMessageList from "../../components/ai/ChatMessageList.jsx";
import ChatInput from "../../components/ai/ChatInput.jsx";
import {sendQuery, ragPerform, ragSave} from "../../utils/aiChatUtil.js";

export default function AiChatPage() {
    const [messages, setMessages] = useState([]);
    const [currentInput, setCurrentInput] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [ragLoading, setRagLoading] = useState("");
    const [selectedFarm, setSelectedFarm] = useState(null);
    const [selectedHouse, setSelectedHouse] = useState(null);
    const fileInputRef = useRef(null);
    const contentRef = useRef(null);
    const [buttonsLeft, setButtonsLeft] = useState(0);

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

    const handleSend = async () => {
        const query = currentInput.trim();
        if (!query || isLoading) return;

        setMessages((prev) => [...prev, {role: "user", content: query}]);
        setCurrentInput("");
        setIsLoading(true);

        try {
            const res = await sendQuery(
                query,
                selectedFarm ? String(selectedFarm.farmId) : null,
                selectedHouse ? String(selectedHouse.housId) : null,
                selectedFarm?.farmName || null,
                selectedHouse?.housName || null,
            );

            const data = res.data;
            setMessages((prev) => [
                ...prev,
                {role: "assistant", content: data.success ? data.response : `오류: ${data.response}`},
            ]);
        } catch (err) {
            setMessages((prev) => [
                ...prev,
                {role: "assistant", content: `응답 생성 중 오류가 발생했습니다: ${err.message}`},
            ]);
        } finally {
            setIsLoading(false);
        }
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
                {role: "assistant", content: data.success ? data.message : `RAG 수행 오류: ${data.message}`},
            ]);
        } catch (err) {
            setMessages((prev) => [
                ...prev,
                {role: "assistant", content: `RAG 수행 중 오류가 발생했습니다: ${err.message}`},
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
                {role: "assistant", content: "저장할 대화 내용이 없습니다."},
            ]);
            return;
        }

        setRagLoading("save");
        try {
            const res = await ragSave(
                messages,
                selectedFarm ? String(selectedFarm.farmId) : null,
                selectedFarm?.farmName || null,
                selectedHouse?.housName || null,
            );
            const data = res.data;
            setMessages((prev) => [
                ...prev,
                {role: "assistant", content: data.success ? data.message : `RAG 저장 오류: ${data.message}`},
            ]);
        } catch (err) {
            setMessages((prev) => [
                ...prev,
                {role: "assistant", content: `RAG 저장 중 오류가 발생했습니다: ${err.message}`},
            ]);
        } finally {
            setRagLoading("");
        }
    };

    const handleClearMessages = () => {
        setMessages([]);
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
                    accept=".txt,.md,.csv,.json"
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
