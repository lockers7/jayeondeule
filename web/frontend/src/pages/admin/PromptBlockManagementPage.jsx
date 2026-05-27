import React, { useEffect, useMemo, useState } from "react";
import { Container, Table, Button, Modal, Form, Alert, Badge } from "react-bootstrap";

// ────────────────────────────────────────────────────────────────────
// [프롬프트 자동화 · Phase 4/5] 관리자 전용 프롬프트 관리.
//   탭 1. DB 블록 (prompt_block_m, PostgreSQL)        — CRUD 전체 + dead code 경고
//   탭 2. Vector 청크 (prompt_chunk, ChromaDB)        — 대화 LLM system 프롬프트
//   탭 3. 도구 정의 (tool_definition_m, PostgreSQL)    — 활성 토글
// 변경 즉시 prompt_registry 캐시 무효화 → 다음 LLM 호출부터 적용.
//
// [2026-05-17] PROMPT_BLOCK_M.CONTROL_*/CIRCULATION_* 는 5/4 이후 dead code.
// [2026-07-04] 제어 system 프롬프트 현행 단일 source 는 control_prompt_m 테이블
// (LLM 제어관리 메뉴, 저장 즉시 반영) — 경고문을 현행 안내로 갱신.
// ────────────────────────────────────────────────────────────────────

const API = "/ai-api/api/v1/admin";

// block_id prefix → 카테고리 분류
function classifyBlock(blockId) {
    if (!blockId) return { label: "기타", variant: "secondary", dead: false };
    if (blockId.startsWith("CONTROL_") || blockId.startsWith("CIRCULATION_")) {
        return { label: "제어 system (dead code)", variant: "danger", dead: true };
    }
    if (blockId.startsWith("ANALYZER_") || blockId.startsWith("VALIDATOR_") ||
        blockId.startsWith("ANSWER_") || blockId.startsWith("CHAT_")) {
        return { label: "대화 system", variant: "info", dead: false };
    }
    return { label: "기타", variant: "secondary", dead: false };
}

function classifyChunk(meta) {
    const mode = (meta?.mode || "").toString();
    const role = (meta?.role || "").toString();
    if (mode === "chat" && role === "system") {
        return { label: "대화 system", variant: "info" };
    }
    if (mode === "chat") return { label: "대화", variant: "primary" };
    return { label: meta?.category || "기타", variant: "secondary" };
}

export default function PromptBlockManagementPage() {
    const [blocks, setBlocks] = useState([]);
    const [chunks, setChunks] = useState([]);
    const [tools, setTools] = useState([]);
    const [activeTab, setActiveTab] = useState("blocks");
    const [alert, setAlert] = useState(null);

    // 편집/신규 공통 모달 상태
    const [modal, setModal] = useState(null);
    // modal: { kind: 'block-edit' | 'block-create' | 'chunk-edit' | 'chunk-create', data: {...} }

    const loadBlocks = () =>
        fetch(`${API}/prompt-blocks`).then(r => r.json())
            .then(d => setBlocks(d.blocks || []))
            .catch(() => setBlocks([]));
    const loadChunks = () =>
        fetch(`${API}/prompt-chunks`).then(r => r.json())
            .then(d => setChunks(d.chunks || []))
            .catch(() => setChunks([]));
    const loadTools = () =>
        fetch(`${API}/tool-definitions`).then(r => r.json())
            .then(d => setTools(d.tools || []))
            .catch(() => setTools([]));

    useEffect(() => { loadBlocks(); loadChunks(); loadTools(); }, []);

    const flash = (variant, text) => setAlert({ variant, text });

    // ─── 블록 CRUD ──────────────────────────────────────────────────
    const openBlockEdit = (b) => setModal({
        kind: "block-edit",
        data: {
            block_id: b.block_id,
            name: b.name || "",
            body_text: b.body_text || "",
            placeholders: JSON.stringify(b.placeholders ?? {}, null, 2),
            description: b.description || "",
            active_yn: b.active_yn || "Y",
        },
    });
    const openBlockCreate = () => setModal({
        kind: "block-create",
        data: {
            block_id: "", name: "", body_text: "",
            placeholders: "{}", description: "", active_yn: "Y",
        },
    });

    const saveBlock = async () => {
        const m = modal.data;
        let placeholders;
        try { placeholders = JSON.parse(m.placeholders || "{}"); }
        catch (e) { return flash("danger", `placeholders JSON 파싱 실패: ${e.message}`); }

        const isCreate = modal.kind === "block-create";
        const url = isCreate ? `${API}/prompt-blocks` : `${API}/prompt-blocks/${m.block_id}`;
        const method = isCreate ? "POST" : "PUT";
        const body = isCreate
            ? { block_id: m.block_id.trim(), name: m.name, body_text: m.body_text,
                placeholders, description: m.description, active_yn: m.active_yn }
            : { name: m.name, body_text: m.body_text,
                placeholders, description: m.description, active_yn: m.active_yn };

        try {
            const res = await fetch(url, {
                method, headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            const data = await res.json();
            if (!res.ok || !data.success) {
                return flash("danger", `${isCreate ? "등록" : "갱신"} 실패: ${data.detail || JSON.stringify(data)}`);
            }
            flash("success", `'${m.block_id}' ${isCreate ? "신규 등록" : "갱신"} 완료. 다음 LLM 호출부터 반영.`);
            setModal(null); loadBlocks();
        } catch (e) {
            flash("danger", `실패: ${e.message}`);
        }
    };

    const deleteBlock = async (block_id) => {
        if (!window.confirm(`'${block_id}' 블록을 정말 삭제하시겠어요? 되돌릴 수 없습니다.`)) return;
        try {
            const res = await fetch(`${API}/prompt-blocks/${block_id}`, { method: "DELETE" });
            const data = await res.json();
            if (!res.ok || !data.success) {
                return flash("danger", `삭제 실패: ${data.detail || JSON.stringify(data)}`);
            }
            flash("warning", `'${block_id}' 삭제됨.`);
            loadBlocks();
        } catch (e) { flash("danger", `삭제 실패: ${e.message}`); }
    };

    // ─── 청크 CRUD ──────────────────────────────────────────────────
    const openChunkEdit = (c) => setModal({
        kind: "chunk-edit",
        data: {
            chunk_id: c.chunk_id,
            content: c.content || "",
            metadata: JSON.stringify(c.metadata || {}, null, 2),
        },
    });
    const openChunkCreate = () => setModal({
        kind: "chunk-create",
        data: { chunk_id: "", content: "",
                metadata: '{\n  "mode": "chat",\n  "role": "system",\n  "category": "대화모드",\n  "stage": ""\n}' },
    });

    const saveChunk = async () => {
        const m = modal.data;
        let metadata;
        try { metadata = JSON.parse(m.metadata || "{}"); }
        catch (e) { return flash("danger", `metadata JSON 파싱 실패: ${e.message}`); }

        const isCreate = modal.kind === "chunk-create";
        const url = isCreate ? `${API}/prompt-chunks` : `${API}/prompt-chunks/${m.chunk_id}`;
        const method = isCreate ? "POST" : "PUT";
        const body = isCreate
            ? { chunk_id: m.chunk_id.trim(), content: m.content, metadata }
            : { content: m.content, metadata };

        try {
            const res = await fetch(url, {
                method, headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            const data = await res.json();
            if (!res.ok || !data.success) {
                return flash("danger", `${isCreate ? "등록" : "갱신"} 실패: ${data.detail || JSON.stringify(data)}`);
            }
            flash("success", `'${m.chunk_id}' ${isCreate ? "신규 등록" : "갱신"} 완료.`);
            setModal(null); loadChunks();
        } catch (e) { flash("danger", `실패: ${e.message}`); }
    };

    const deleteChunk = async (chunk_id) => {
        if (!window.confirm(`'${chunk_id}' 청크를 정말 삭제하시겠어요?`)) return;
        try {
            const res = await fetch(`${API}/prompt-chunks/${chunk_id}`, { method: "DELETE" });
            const data = await res.json();
            if (!res.ok || !data.success) {
                return flash("danger", `삭제 실패: ${data.detail || JSON.stringify(data)}`);
            }
            flash("warning", `'${chunk_id}' 삭제됨.`);
            loadChunks();
        } catch (e) { flash("danger", `삭제 실패: ${e.message}`); }
    };

    // ─── 도구 정의 토글 ─────────────────────────────────────────────
    const toggleTool = async (t) => {
        const next = t.active_yn === "Y" ? "N" : "Y";
        try {
            const res = await fetch(`${API}/tool-definitions/${t.tool_id}`, {
                method: "PATCH", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ active_yn: next }),
            });
            const data = await res.json();
            if (!data.success) return flash("danger", `토글 실패: ${data.detail || data.error}`);
            flash("info", `'${t.tool_id}' → active=${next}`);
            loadTools();
            return next;
        } catch (e) { flash("danger", `토글 실패: ${e.message}`); }
    };

    // 도구 상세 보기 (백엔드는 R + active 토글만 지원 — create/delete 없음)
    const openToolDetail = (t) => setModal({ kind: "tool-detail", data: { ...t } });
    const toggleToolInModal = async (t) => {
        const next = await toggleTool(t);
        if (next) setModal(m => (m && m.kind === "tool-detail")
            ? { ...m, data: { ...m.data, active_yn: next } } : m);
    };

    const hasDeadCodeBlocks = useMemo(
        () => blocks.some(b => classifyBlock(b.block_id).dead),
        [blocks]
    );

    // ─── 모달 input helper ──────────────────────────────────────────
    const setField = (key, value) => setModal(m => ({ ...m, data: { ...m.data, [key]: value } }));

    return (
        <Container fluid className="py-4">
            <h2 className="mb-3">LLM 프롬프트 관리</h2>
            <p className="text-muted small mb-3">
                LLM 에 주입되는 모든 시스템·사용자 프롬프트 (PostgreSQL <code>prompt_block_m</code>,
                ChromaDB <code>prompt_chunk</code>) + 도구 정의를 한 화면에서 관리합니다.
                저장 즉시 캐시가 무효화되어 다음 LLM 호출부터 적용됩니다.
            </p>

            {alert && (
                <Alert variant={alert.variant} dismissible onClose={() => setAlert(null)}>
                    {alert.text}
                </Alert>
            )}

            <div className="mb-3 d-flex align-items-center flex-wrap gap-2">
                <Button variant={activeTab === "blocks" ? "primary" : "outline-primary"}
                        size="sm" onClick={() => setActiveTab("blocks")}>
                    DB 블록 ({blocks.length})
                </Button>
                <Button variant={activeTab === "chunks" ? "primary" : "outline-primary"}
                        size="sm" onClick={() => setActiveTab("chunks")}>
                    Vector 청크 ({chunks.length})
                </Button>
                <Button variant={activeTab === "tools" ? "primary" : "outline-primary"}
                        size="sm" onClick={() => setActiveTab("tools")}>
                    도구 정의 ({tools.length})
                </Button>

                <div className="ms-auto">
                    {activeTab === "blocks" && (
                        <Button size="sm" variant="success" onClick={openBlockCreate}>+ 신규 블록</Button>
                    )}
                    {activeTab === "chunks" && (
                        <Button size="sm" variant="success" onClick={openChunkCreate}>+ 신규 청크</Button>
                    )}
                </div>
            </div>

            {activeTab === "blocks" && hasDeadCodeBlocks && (
                <Alert variant="warning" className="small">
                    <strong>⚠ dead code 경고</strong> — <code>CONTROL_*</code> / <code>CIRCULATION_*</code> 블록은
                    2026-05-04 이후 LLM 에 반영되지 않습니다. 제어 system 프롬프트의 현행 단일 source 는
                    <code> control_prompt_m </code> 테이블이며, 상단 <strong>LLM 제어관리</strong> 메뉴에서
                    수정하세요(저장 즉시 다음 제어 사이클부터 반영 · 재기동 불필요). 이 탭의
                    CONTROL_* 블록 UPDATE/INSERT/DELETE 는 여전히 무효합니다.
                </Alert>
            )}

            {activeTab === "blocks" && (
                <Table striped bordered hover size="sm">
                    <thead>
                        <tr>
                            <th>block_id</th>
                            <th>이름</th>
                            <th style={{ width: "150px" }}>카테고리</th>
                            <th style={{ width: "80px" }}>크기</th>
                            <th style={{ width: "70px" }}>활성</th>
                            <th style={{ width: "160px" }}>관리</th>
                        </tr>
                    </thead>
                    <tbody>
                        {blocks.map((b) => {
                            const cat = classifyBlock(b.block_id);
                            return (
                                <tr key={b.block_id} className={cat.dead ? "table-warning" : ""}>
                                    <td><code>{b.block_id}</code></td>
                                    <td>{b.name}</td>
                                    <td><Badge bg={cat.variant}>{cat.label}</Badge></td>
                                    <td>{(b.body_text || "").length}B</td>
                                    <td>
                                        <Badge bg={b.active_yn === "Y" ? "success" : "secondary"}>
                                            {b.active_yn}
                                        </Badge>
                                    </td>
                                    <td>
                                        <Button size="sm" variant="outline-primary" onClick={() => openBlockEdit(b)} className="me-1">편집</Button>
                                        <Button size="sm" variant="outline-danger" onClick={() => deleteBlock(b.block_id)}>삭제</Button>
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </Table>
            )}

            {activeTab === "chunks" && (
                <Table striped bordered hover size="sm">
                    <thead>
                        <tr>
                            <th>chunk_id</th>
                            <th style={{ width: "120px" }}>카테고리</th>
                            <th>mode / stage</th>
                            <th>본문 미리보기</th>
                            <th style={{ width: "80px" }}>크기</th>
                            <th style={{ width: "160px" }}>관리</th>
                        </tr>
                    </thead>
                    <tbody>
                        {chunks.map((c) => {
                            const cat = classifyChunk(c.metadata);
                            const preview = (c.content || "").slice(0, 80);
                            return (
                                <tr key={c.chunk_id}>
                                    <td><code>{c.chunk_id}</code></td>
                                    <td><Badge bg={cat.variant}>{cat.label}</Badge></td>
                                    <td className="small text-muted">
                                        {c.metadata?.mode || "-"} / {c.metadata?.stage || "-"}
                                    </td>
                                    <td className="small">{preview}{(c.content || "").length > 80 ? "..." : ""}</td>
                                    <td>{(c.content || "").length}B</td>
                                    <td>
                                        <Button size="sm" variant="outline-primary" onClick={() => openChunkEdit(c)} className="me-1">편집</Button>
                                        <Button size="sm" variant="outline-danger" onClick={() => deleteChunk(c.chunk_id)}>삭제</Button>
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </Table>
            )}

            {activeTab === "tools" && (
                <Table striped bordered hover size="sm">
                    <thead>
                        <tr>
                            <th>tool_id</th>
                            <th>카테고리</th>
                            <th style={{ width: "70px" }}>우선순위</th>
                            <th>설명 (요약)</th>
                            <th style={{ width: "100px" }}>활성</th>
                        </tr>
                    </thead>
                    <tbody>
                        {tools.map((t) => (
                            <tr key={t.tool_id} style={{ cursor: "pointer" }} onClick={() => openToolDetail(t)}>
                                <td><code>{t.tool_id}</code></td>
                                <td>{t.category}</td>
                                <td>{t.priority}</td>
                                <td>{(t.description || "").slice(0, 80)}{(t.description || "").length > 80 ? "..." : ""}</td>
                                <td>
                                    <Button size="sm"
                                            variant={t.active_yn === "Y" ? "success" : "outline-secondary"}
                                            onClick={(e) => { e.stopPropagation(); toggleTool(t); }}>
                                        {t.active_yn === "Y" ? "ON" : "OFF"}
                                    </Button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </Table>
            )}

            {/* ─── 블록 편집/신규 공통 모달 ─────────────────────────── */}
            <Modal show={modal?.kind === "block-edit" || modal?.kind === "block-create"}
                   onHide={() => setModal(null)} size="lg">
                <Modal.Header closeButton>
                    <Modal.Title>
                        {modal?.kind === "block-create" ? "블록 신규 등록" : `블록 편집 — ${modal?.data?.block_id}`}
                    </Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    {modal?.kind === "block-create" && (
                        <Form.Group className="mb-3">
                            <Form.Label>block_id <span className="text-danger">*</span></Form.Label>
                            <Form.Control value={modal.data.block_id}
                                          onChange={e => setField("block_id", e.target.value)}
                                          placeholder="대문자_스네이크 (예: USER_GUIDE_INTRO)"
                                          style={{ fontFamily: "monospace" }}/>
                            <Form.Text className="text-muted">
                                저장 후 변경 불가. <code>CONTROL_*/CIRCULATION_*</code> 는 dead code 권역이므로 다른 prefix 권장.
                            </Form.Text>
                        </Form.Group>
                    )}
                    <Form.Group className="mb-3">
                        <Form.Label>이름</Form.Label>
                        <Form.Control value={modal?.data?.name || ""}
                                      onChange={e => setField("name", e.target.value)}/>
                    </Form.Group>
                    <Form.Group className="mb-3">
                        <Form.Label>본문 (body_text)</Form.Label>
                        <Form.Control as="textarea" rows={14}
                                      style={{ fontFamily: "monospace", fontSize: "12px" }}
                                      value={modal?.data?.body_text || ""}
                                      onChange={e => setField("body_text", e.target.value)}/>
                        <Form.Text className="text-muted">{(modal?.data?.body_text || "").length} bytes</Form.Text>
                    </Form.Group>
                    <Form.Group className="mb-3">
                        <Form.Label>placeholders (JSON)</Form.Label>
                        <Form.Control as="textarea" rows={3}
                                      style={{ fontFamily: "monospace", fontSize: "12px" }}
                                      value={modal?.data?.placeholders || "{}"}
                                      onChange={e => setField("placeholders", e.target.value)}/>
                        <Form.Text className="text-muted">
                            본문의 <code>{"${KEY}"}</code> 가 코드 인자로 동적 치환됩니다. 예: <code>{"{\"TEMP_LOW\": 25}"}</code>
                        </Form.Text>
                    </Form.Group>
                    <Form.Group className="mb-3">
                        <Form.Label>설명 (description)</Form.Label>
                        <Form.Control value={modal?.data?.description || ""}
                                      onChange={e => setField("description", e.target.value)}/>
                    </Form.Group>
                    <Form.Group>
                        <Form.Label>활성 여부</Form.Label>
                        <Form.Select value={modal?.data?.active_yn || "Y"}
                                     onChange={e => setField("active_yn", e.target.value)}>
                            <option value="Y">Y (활성)</option>
                            <option value="N">N (비활성)</option>
                        </Form.Select>
                    </Form.Group>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={() => setModal(null)}>취소</Button>
                    <Button variant="primary" onClick={saveBlock}>
                        {modal?.kind === "block-create" ? "등록" : "저장 (즉시 반영)"}
                    </Button>
                </Modal.Footer>
            </Modal>

            {/* ─── 청크 편집/신규 공통 모달 ─────────────────────────── */}
            <Modal show={modal?.kind === "chunk-edit" || modal?.kind === "chunk-create"}
                   onHide={() => setModal(null)} size="lg">
                <Modal.Header closeButton>
                    <Modal.Title>
                        {modal?.kind === "chunk-create" ? "청크 신규 등록 (ChromaDB)" : `청크 편집 — ${modal?.data?.chunk_id}`}
                    </Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    {modal?.kind === "chunk-create" && (
                        <Form.Group className="mb-3">
                            <Form.Label>chunk_id <span className="text-danger">*</span></Form.Label>
                            <Form.Control value={modal.data.chunk_id}
                                          onChange={e => setField("chunk_id", e.target.value)}
                                          placeholder="소문자_스네이크 (예: chat_user_intro)"
                                          style={{ fontFamily: "monospace" }}/>
                        </Form.Group>
                    )}
                    <Form.Group className="mb-3">
                        <Form.Label>본문 (content)</Form.Label>
                        <Form.Control as="textarea" rows={14}
                                      style={{ fontFamily: "monospace", fontSize: "12px" }}
                                      value={modal?.data?.content || ""}
                                      onChange={e => setField("content", e.target.value)}/>
                        <Form.Text className="text-muted">{(modal?.data?.content || "").length} bytes</Form.Text>
                    </Form.Group>
                    <Form.Group>
                        <Form.Label>메타데이터 (JSON)</Form.Label>
                        <Form.Control as="textarea" rows={6}
                                      style={{ fontFamily: "monospace", fontSize: "12px" }}
                                      value={modal?.data?.metadata || "{}"}
                                      onChange={e => setField("metadata", e.target.value)}/>
                        <Form.Text className="text-muted">
                            예: <code>{'{"mode":"chat","role":"system","category":"대화모드","stage":"answer_generation"}'}</code>
                        </Form.Text>
                    </Form.Group>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={() => setModal(null)}>취소</Button>
                    <Button variant="primary" onClick={saveChunk}>
                        {modal?.kind === "chunk-create" ? "등록" : "저장"}
                    </Button>
                </Modal.Footer>
            </Modal>

            {/* ─── 도구 정의 상세 모달 (Read + active 토글) ───────────── */}
            <Modal show={modal?.kind === "tool-detail"} onHide={() => setModal(null)} size="lg">
                <Modal.Header closeButton>
                    <Modal.Title>도구 정의 — <code>{modal?.data?.tool_id}</code></Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    {modal?.kind === "tool-detail" && (
                        <>
                            <Table size="sm" borderless className="mb-3">
                                <tbody>
                                    <tr><td style={{ width: "110px" }}><strong>카테고리</strong></td><td>{modal.data.category || "-"}</td></tr>
                                    <tr><td><strong>우선순위</strong></td><td>{modal.data.priority ?? "-"}</td></tr>
                                    <tr>
                                        <td><strong>활성</strong></td>
                                        <td>
                                            <Badge bg={modal.data.active_yn === "Y" ? "success" : "secondary"} className="me-2">
                                                {modal.data.active_yn}
                                            </Badge>
                                            <Button size="sm"
                                                    variant={modal.data.active_yn === "Y" ? "outline-secondary" : "success"}
                                                    onClick={() => toggleToolInModal(modal.data)}>
                                                {modal.data.active_yn === "Y" ? "비활성화 (OFF)" : "활성화 (ON)"}
                                            </Button>
                                        </td>
                                    </tr>
                                    <tr><td><strong>수정시각</strong></td><td className="small text-muted">{modal.data.updt_dttm || "-"}</td></tr>
                                </tbody>
                            </Table>
                            <Form.Group className="mb-3">
                                <Form.Label><strong>설명 (description)</strong></Form.Label>
                                <div style={{ whiteSpace: "pre-wrap", background: "#f8f9fa", padding: "10px", borderRadius: "5px", fontSize: "0.9em" }}>
                                    {modal.data.description || "(없음)"}
                                </div>
                            </Form.Group>
                            <Form.Group>
                                <Form.Label><strong>schema_json (함수·파라미터 정의)</strong></Form.Label>
                                <pre style={{ whiteSpace: "pre-wrap", maxHeight: "360px", overflow: "auto", background: "#f0f0f0", padding: "10px", borderRadius: "5px", fontSize: "12px" }}>
                                    {(() => {
                                        const s = modal.data.schema_json;
                                        try { return JSON.stringify(typeof s === "string" ? JSON.parse(s) : s, null, 2); }
                                        catch { return String(s ?? "-"); }
                                    })()}
                                </pre>
                            </Form.Group>
                            <p className="text-muted small mb-0">
                                ※ 도구 정의는 조회 + 활성 토글만 지원합니다 (신규/삭제 백엔드 미제공).
                                스키마·설명 편집이 필요하면 별도 엔드포인트 추가가 필요합니다.
                            </p>
                        </>
                    )}
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={() => setModal(null)}>닫기</Button>
                </Modal.Footer>
            </Modal>
        </Container>
    );
}
