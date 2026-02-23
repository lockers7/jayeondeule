import React from "react";
import ReactMarkdown from "react-markdown";
import "./ChatBubble.css";

function renderContentWithLinks(text) {
    if (!text) return null;
    const urlRegex = /(https?:\/\/[^\s<>"')\]]+)/g;
    const parts = text.split(urlRegex);

    return parts.map((part, i) => {
        if (/^https?:\/\//.test(part)) {
            return (
                <a key={i} href={part} target="_blank" rel="noopener noreferrer"
                   style={{color: "#1976D2", textDecoration: "underline"}}>
                    {part}
                </a>
            );
        }
        return <React.Fragment key={i}>{part}</React.Fragment>;
    });
}

export default function ChatBubble({role, content}) {
    const isUser = role === "user";

    return (
        <div className={`d-flex ${isUser ? "justify-content-end" : "justify-content-start"} mb-2`}>
            <div
                className={isUser ? "" : "chat-markdown"}
                style={{
                    maxWidth: "75%",
                    padding: "10px 14px",
                    borderRadius: isUser ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                    backgroundColor: isUser ? "#E8F5E9" : "#FFFFFF",
                    border: isUser ? "1px solid #C8E6C9" : "1px solid #E0E0E0",
                    wordBreak: "break-word",
                    lineHeight: "1.6",
                    fontSize: "14px",
                    ...(isUser ? {whiteSpace: "pre-wrap"} : {}),
                }}
            >
                {isUser ? (
                    renderContentWithLinks(content)
                ) : (
                    <ReactMarkdown
                        components={{
                            a: ({href, children}) => {
                                const isValidUrl = href && /^https?:\/\/.+\..+/.test(href);
                                if (!isValidUrl) {
                                    return <span>{children}</span>;
                                }
                                return (
                                    <a href={href} target="_blank" rel="noopener noreferrer"
                                       style={{color: "#1976D2", textDecoration: "underline"}}>
                                        {children}
                                    </a>
                                );
                            },
                        }}
                    >
                        {(content || "").replace(/\n{3,}/g, "\n\n")}
                    </ReactMarkdown>
                )}
            </div>
        </div>
    );
}
