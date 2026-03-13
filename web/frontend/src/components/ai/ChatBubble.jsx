// ------------------------------------------------------------------------------------------------------------
// AI 채팅 말풍선 컴포넌트
// --->
// escapeSingleTilde: 단일 ~를 \~로 이스케이프 (remark-gfm 취소선 오인 방지, ~~는 보존)
// preserveLineBreaksForMarkdown: 단일 개행 → hard break 변환, 코드펜스/표 보호, 단일 ~ 이스케이프
// renderContentWithLinks: 사용자 메시지 내 URL을 클릭 가능한 링크로 변환
// formatTime: 타임스탬프를 "오전/오후 HH:MM" 형식으로 포맷
// ChatBubble: 채팅 말풍선 렌더링 (ReactMarkdown + remark-gfm, 출처/도구/유형 메타 표시)
// ------------------------------------------------------------------------------------------------------------
import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import VoiceTtsButton from "./voice/VoiceTtsButton.jsx";
import "./ChatBubble.css";

// 단일 물결표(~) 이스케이프: remark-gfm이 단일 ~를 취소선(strikethrough)으로 해석하는 것을 방지한다.
// ~~(이중 물결표 = 정상 취소선 문법)은 유지하고, 단일 ~만 \~로 이스케이프한다.
// 코드 펜스(```...```) 내부는 원문 그대로 유지한다.
function escapeSingleTilde(text) {
    if (!text) return text;
    // ~~는 보존(플레이스홀더 치환) → 단일 ~ 이스케이프 → ~~복원
    return text
        .replace(/~~/g, "\x00DT\x00")
        .replace(/~/g, "\\~")
        .replace(/\x00DT\x00/g, "~~");
}

function preserveLineBreaksForMarkdown(text) {
    if (!text) return "";

    const normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

    // 코드 펜스(```...```) 내부는 원문 그대로 유지하고,
    // 일반 텍스트 구간의 단일 개행만 markdown hard break("  \n")로 변환한다.
    // 마크다운 표 행(| 로 시작)도 원문 그대로 유지한다.
    // 단일 물결표(~)는 remark-gfm 취소선 오인 방지를 위해 이스케이프한다.
    const parts = normalized.split(/(```[\s\S]*?```)/g);
    return parts
        .map((part) => {
            if (part.startsWith("```") && part.endsWith("```")) {
                return part;
            }

            // 단일 ~ 이스케이프 (remark-gfm 취소선 오인 방지)
            part = escapeSingleTilde(part);

            const lines = part.split("\n");
            if (lines.length <= 1) {
                return part;
            }

            let output = "";
            for (let i = 0; i < lines.length; i += 1) {
                const current = lines[i];
                output += current;

                if (i === lines.length - 1) {
                    continue;
                }

                const next = lines[i + 1];
                const hasBlankBoundary = current.trim() === "" || next.trim() === "";
                // 마크다운 표 행은 hard break 없이 그대로 유지 (remark-gfm 테이블 파싱 보호)
                const isTableRow = current.trim().startsWith("|") || next.trim().startsWith("|");
                output += (hasBlankBoundary || isTableRow) ? "\n" : "  \n";
            }

            return output;
        })
        .join("");
}

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

function formatTime(timestamp) {
    if (!timestamp) return null;
    const d = timestamp instanceof Date ? timestamp : new Date(timestamp);
    if (isNaN(d.getTime())) return null;
    const h = d.getHours();
    const m = String(d.getMinutes()).padStart(2, "0");
    const period = h < 12 ? "오전" : "오후";
    const hour12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
    return `${period} ${hour12}:${m}`;
}

export default function ChatBubble({role, content, sources = [], toolsUsed = [], responseType = null, elapsedSec = null, timestamp = null}) {
    const isUser = role === "user";
    const statusMessage = (content || "").trim();
    const isGeneratingStatus =
        statusMessage === "답변을 생성하고 있습니다..."
        || statusMessage.startsWith("답변 생성 중입니다...");
    const statusTextColor = !isUser
        ? (
            statusMessage === "질문을 분석하고 있습니다..."
                ? "#8B0000"
                : isGeneratingStatus
                    ? "#0B3D91"
                    : null
        )
        : null;
    const showMeta = !isUser && (sources.length > 0 || toolsUsed.length > 0 || responseType);
    const timeStr = formatTime(timestamp);

    return (
        <div className={`d-flex ${isUser ? "justify-content-end" : "justify-content-start"} mb-2`}>
            <div
                className={isUser ? "" : "chat-markdown"}
                style={{
                    maxWidth: "75%",
                    minWidth: 0,
                    padding: "10px 14px",
                    borderRadius: isUser ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                    backgroundColor: isUser ? "#E8F5E9" : "#FFFFFF",
                    border: isUser ? "1px solid #C8E6C9" : "1px solid #E0E0E0",
                    wordBreak: "break-word",
                    overflowWrap: "break-word",
                    overflow: "hidden",
                    lineHeight: "1.6",
                    fontSize: "14px",
                    ...(isUser ? {whiteSpace: "pre-wrap"} : {}),
                    ...(statusTextColor ? {color: statusTextColor} : {}),
                }}
            >
                {isUser ? (
                    renderContentWithLinks(content)
                ) : (
                    <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
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
                            // 표를 스크롤 가능한 래퍼로 감싸서 말풍선 밖으로 넘치지 않도록 함
                            table: ({children}) => (
                                <div className="chat-table-wrapper">
                                    <table>{children}</table>
                                </div>
                            ),
                        }}
                    >
                        {preserveLineBreaksForMarkdown(content || "")}
                    </ReactMarkdown>
                )}
                {!isUser && <VoiceTtsButton text={content}/>}
                {showMeta && (
                    <div className="chat-response-meta">
                        {sources.length > 0 && (
                            <div className="chat-meta-row">
                                <span className="chat-meta-label">출처</span>
                                <span className="chat-meta-sources">
                                    {sources.map((source, index) => (
                                        <a
                                            key={`${source.url}-${index}`}
                                            href={source.url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                        >
                                            {source.title || source.url}
                                        </a>
                                    ))}
                                </span>
                            </div>
                        )}
                        {responseType && (
                            <div className="chat-meta-row">
                                <span className="chat-meta-label">유형</span>
                                <span className="chat-meta-value">
                                    {responseType}
                                    {elapsedSec != null && ` (${elapsedSec} sec)`}
                                </span>
                            </div>
                        )}
                        {toolsUsed.length > 0 && (
                            <div className="chat-meta-row">
                                <span className="chat-meta-label">도구</span>
                                <span className="chat-meta-value">{toolsUsed.join(", ")}</span>
                            </div>
                        )}
                    </div>
                )}
            </div>
            {timeStr && (
                <div className={`chat-timestamp ${isUser ? "chat-timestamp-user" : "chat-timestamp-assistant"}`}>
                    {timeStr}
                </div>
            )}
        </div>
    );
}
