import React, {useState} from "react";
import {Button, Form, Spinner} from "react-bootstrap";
import VoiceMicButton from "./voice/VoiceMicButton.jsx";
import "./ChatInput.css";

const DEFAULT_PLACEHOLDER = "메시지를 입력하세요... (Shift+Enter: 줄바꿈, Enter: 전송)";

export default function ChatInput({value, onChange, onSend, isLoading, farmName, onStop}) {
    const [placeholder, setPlaceholder] = useState(DEFAULT_PLACEHOLDER);

    const handleKeyDown = (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onSend();
        }
    };

    return (
        <div style={{padding: "12px 16px", borderTop: "1px solid #DEE2E6", backgroundColor: "#FFFFFF"}}>
            {farmName && (
                <div style={{fontSize: "13px", fontWeight: "700", marginBottom: "4px"}}>
                    [{farmName}] 농장입니다. 무엇을 도와 드릴까요?
                </div>
            )}
            <div style={{display: "flex", gap: "8px", alignItems: "flex-end"}}>
                <Form.Control
                    as="textarea"
                    rows={3}
                    placeholder={placeholder}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    onKeyDown={handleKeyDown}
                    disabled={isLoading}
                    style={{resize: "none", flex: 1, border: "2px solid #28a745"}}
                />
                <div style={{display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end", gap: "4px"}}>
                    <Button
                        variant="success"
                        onClick={onSend}
                        disabled={isLoading || !value.trim()}
                        style={{width: "70px", height: "36px", padding: "4px 8px"}}
                    >
                        {isLoading ? <Spinner animation="border" size="sm"/> : "전송"}
                    </Button>
                    {isLoading ? (
                        <button
                            className="voice-mic-btn voice-mic-stop"
                            onClick={onStop}
                            title="진행 중지"
                        >
                            <span className="stop-square"/>
                        </button>
                    ) : (
                        <VoiceMicButton
                            onTranscribed={(text) => {
                                onChange(text);
                                onSend(text);
                            }}
                            onStatusChange={(status) => {
                                if (status === "recording") {
                                    setPlaceholder("🎤 질문을 말씀하세요!");
                                } else {
                                    setPlaceholder(DEFAULT_PLACEHOLDER);
                                }
                            }}
                            disabled={isLoading}
                        />
                    )}
                </div>
            </div>
        </div>
    );
}
