import React, {useEffect, useRef} from "react";
import ChatBubble from "./ChatBubble.jsx";

export default function ChatMessageList({messages}) {
    const bottomRef = useRef(null);

    useEffect(() => {
        bottomRef.current?.scrollIntoView({behavior: "smooth"});
    }, [messages]);

    return (
        <div
            style={{
                flex: 1,
                overflowY: "auto",
                padding: "16px",
                backgroundColor: "#F5F5F5",
                border: "2px solid #28a745",
                borderRadius: "6px",
                margin: "8px",
            }}
        >
            {messages.length === 0 ? (
                <div className="text-center text-muted" style={{paddingTop: "40px"}}>
                    <span style={{fontSize: "14px", fontWeight: "700"}}>
                        대화를 시작해보세요!
                    </span>
                </div>
            ) : (
                messages.map((msg, index) => (
                    <ChatBubble key={index} role={msg.role} content={msg.content}/>
                ))
            )}
            <div ref={bottomRef}/>
        </div>
    );
}
