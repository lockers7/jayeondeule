/**
 * AI 채팅 스트림 매니저 (모듈 레벨 싱글톤)
 *
 * 컴포넌트 마운트/언마운트와 무관하게 SSE 스트림을 유지한다.
 * - 페이지 이동(언마운트) 시 스트림이 중단되지 않음
 * - 돌아오면(재마운트) 진행 중이거나 완료된 결과를 즉시 동기화
 */
import {streamQuery} from "./aiChatUtil.js";

// ─── 내부 상태 ───
let _stream = null;   // 활성 스트림 정보
let _listener = null;  // React 상태 업데이트 콜백 (마운트 시에만 설정)

/**
 * 스트림 상태 구조:
 * {
 *   active: boolean,
 *   controller: AbortController | null,
 *   content: string,           // 누적된 어시스턴트 응답
 *   tokenStarted: boolean,
 *   doneData: object | null,   // 완료 시 서버 데이터
 *   errorMsg: string | null,   // 에러 메시지
 *   userQuery: string,         // 사용자 질문 (복원용)
 *   userTimestamp: Date,       // 질문 시각
 * }
 */

function _notify(type, payload) {
    if (_listener) _listener(type, payload);
}

function _saveMessagesToSession(messages) {
    try {
        sessionStorage.setItem("ai_chat_messages", JSON.stringify(messages));
    } catch { /* 무시 */ }
}

/**
 * React 컴포넌트가 마운트될 때 리스너를 등록한다.
 * @param {Function} listener - (type, payload) => void
 */
export function subscribe(listener) {
    _listener = listener;
}

/**
 * React 컴포넌트가 언마운트될 때 리스너를 해제한다.
 * 스트림은 중단하지 않는다.
 */
export function unsubscribe() {
    _listener = null;
}

/**
 * 활성 스트림이 있는지 확인한다.
 */
export function isActive() {
    return !!(_stream && _stream.active);
}

/**
 * 현재 스트림 상태의 스냅샷을 반환한다.
 * 재마운트 시 상태 복원에 사용.
 */
export function getSnapshot() {
    if (!_stream) return null;
    return { ..._stream };
}

/**
 * SSE 스트리밍을 시작한다.
 * 콜백은 매니저 내부에서 처리하고, React에는 리스너를 통해 전파한다.
 */
export function startStream(query, farmId, houseId, farmName, houseName, sessionId, speechStyle, authFarmId) {
    // 기존 스트림이 있으면 정리
    if (_stream && _stream.controller) {
        _stream.controller.abort();
    }

    _stream = {
        active: true,
        controller: null,
        content: "",
        tokenStarted: false,
        doneData: null,
        errorMsg: null,
        userQuery: query,
        userTimestamp: new Date(),
    };

    const controller = streamQuery(
        query, farmId, houseId, farmName, houseName, sessionId, speechStyle,
        {
            onStatus: (text) => {
                if (!_stream || _stream.tokenStarted) return;
                _stream.content = text;
                _notify("status", text);
            },
            onToken: (text) => {
                if (!_stream) return;
                if (!_stream.tokenStarted) {
                    _stream.tokenStarted = true;
                    _stream.content = text;
                } else {
                    _stream.content += text;
                }
                _notify("token", { content: _stream.content, chunk: text, first: !_stream.tokenStarted });
            },
            onDone: (data) => {
                if (!_stream) return;
                _stream.doneData = data;
                _stream.active = false;
                _stream.controller = null;
                _notify("done", data);
            },
            onError: (errMsg) => {
                if (!_stream) return;
                _stream.errorMsg = errMsg;
                _stream.active = false;
                _stream.controller = null;
                _notify("error", errMsg);
            },
        },
        authFarmId,
    );

    _stream.controller = controller;
    return controller;
}

/**
 * 스트림을 중단한다 (사용자가 "중지" 버튼을 누른 경우).
 */
export function abortStream() {
    if (_stream && _stream.controller) {
        _stream.controller.abort();
        _stream.controller = null;
        _stream.active = false;
    }
    _stream = null;
}

/**
 * 완료/에러 상태의 스트림을 소비(consume)한 후 정리한다.
 * 재마운트 시 상태를 읽고 나면 호출.
 */
export function consumeCompleted() {
    if (_stream && !_stream.active) {
        _stream = null;
    }
}
