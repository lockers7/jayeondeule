import React, { useEffect, useMemo, useState } from "react";
import { Container, Table, Button, Modal, Form, Alert, Badge } from "react-bootstrap";

// ────────────────────────────────────────────────────────────────────
// LLM 제어 프롬프트 관리 (control_prompt_m).
//   system_prompt  — 농장 제어 system 프롬프트 섹션 (CTRL_ROLE, CTRL_SEC1~9)
//   user_label     — user 메시지 라벨
//   user_message   — user 메시지 본문 (센서 평가, 릴레이 상태, 룰 위반 등)
//   agent_system   — ai_monitor_agent 시스템 프롬프트 (CTRL_AGENT_SYSTEM)
// 변경 즉시 prompt_registry _CTRL_BLOCK_CACHE 무효화 → 다음 LLM 호출부터 적용.
// ────────────────────────────────────────────────────────────────────

const API = "/ai-api/api/v1/admin";

const CATEGORIES = [
    { value: "", label: "전체" },
    { value: "system_prompt", label: "system_prompt — 제어 시스템 프롬프트" },
    { value: "user_label",    label: "user_label — 유저 메시지 라벨" },
    { value: "user_message",  label: "user_message — 유저 메시지 본문" },
    { value: "agent_system",  label: "agent_system — 모니터링 에이전트 시스템 프롬프트" },
];

const GROWTH_STAGES = ["", "발이기", "생육기", "수확기"];

const CATEGORY_VARIANT = {
    system_prompt: "primary",
    user_label:    "info",
    user_message:  "success",
    agent_system:  "warning",
};

function categoryBadge(category) {
    return (
        <Badge bg={CATEGORY_VARIANT[category] || "secondary"}>
            {category}
        </Badge>
    );
}

const EMPTY_FORM = {
    block_id: "", section_key: "", growth_stage: "", sort_order: 0,
    category: "system_prompt", name: "", body_text: "",
    placeholders: "{}", description: "", active_yn: "Y",
};

export default function ControlPromptManagementPage() {
    const [prompts, setPrompts] = useState([]);
    const [filterCategory, setFilterCategory] = useState("");
    const [filterGrowth, setFilterGrowth] = useState("");
    const [alert, setAlert] = useState(null);
    const [modal, setModal] = useState(null);
    // modal: { kind: 'edit' | 'create', data: {...} }

    const loadPrompts = () => {
        const params = new URLSearchParams();
        if (filterCategory) params.set("category", filterCategory);
        if (filterGrowth)   params.set("growth_stage", filterGrowth);
        fetch(`${API}/control-prompts?${params}`)
            .then(r => r.json())
            .then(d => setPrompts(d.prompts || []))
            .catch(() => setPrompts([]));
    };

    useEffect(() => { loadPrompts(); }, [filterCategory, filterGrowth]);

    const flash = (variant, text) => {
        setAlert({ variant, text });
        setTimeout(() => setAlert(null), 4000);
    };

    // ─── 편집 모달 열기 ─────────────────────────────────────────────
    const openEdit = (p) => setModal({
        kind: "edit",
        data: {
            block_id:     p.block_id,
            section_key:  p.section_key || "",
            growth_stage: p.growth_stage || "",
            sort_order:   p.sort_order ?? 0,
            category:     p.category || "system_prompt",
            name:         p.name || "",
            body_text:    p.body_text || "",
            placeholders: JSON.stringify(p.placeholders ?? {}, null, 2),
            description:  p.description || "",
            active_yn:    p.active_yn || "Y",
        },
    });

    const openCreate = () => setModal({ kind: "create", data: { ...EMPTY_FORM } });

    const closeModal = () => setModal(null);

    const setField = (key, val) =>
        setModal(m => ({ ...m, data: { ...m.data, [key]: val } }));

    // ─── 저장 (편집/신규 공통) ──────────────────────────────────────
    const handleSave = async () => {
        if (!modal) return;
        const d = modal.data;

        let placeholdersParsed;
        try { placeholdersParsed = JSON.parse(d.placeholders || "{}"); }
        catch { flash("danger", "placeholders JSON 형식 오류입니다."); return; }

        const payload = {
            ...d,
            sort_order: Number(d.sort_order),
            placeholders: placeholdersParsed,
            growth_stage: d.growth_stage || null,
        };

        const isEdit = modal.kind === "edit";
        const url  = isEdit
            ? `${API}/control-prompts/${encodeURIComponent(d.block_id)}`
            : `${API}/control-prompts`;
        const method = isEdit ? "PUT" : "POST";

        try {
            const res = await fetch(url, {
                method,
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const json = await res.json();
            if (!res.ok) { flash("danger", json.detail || "저장 실패"); return; }
            flash("success", isEdit ? `'${d.block_id}' 갱신 완료` : `'${d.block_id}' 등록 완료`);
            closeModal();
            loadPrompts();
        } catch (e) {
            flash("danger", `저장 오류: ${e.message}`);
        }
    };

    // ─── 삭제 ───────────────────────────────────────────────────────
    const handleDelete = async (blockId) => {
        if (!window.confirm(`'${blockId}' 을(를) 삭제하시겠습니까?`)) return;
        try {
            const res = await fetch(`${API}/control-prompts/${encodeURIComponent(blockId)}`, {
                method: "DELETE",
            });
            const json = await res.json();
            if (!res.ok) { flash("danger", json.detail || "삭제 실패"); return; }
            flash("success", `'${blockId}' 삭제 완료`);
            loadPrompts();
        } catch (e) {
            flash("danger", `삭제 오류: ${e.message}`);
        }
    };

    // ─── active_yn 토글 ─────────────────────────────────────────────
    const handleToggleActive = async (p) => {
        const next = p.active_yn === "Y" ? "N" : "Y";
        try {
            const res = await fetch(
                `${API}/control-prompts/${encodeURIComponent(p.block_id)}`,
                {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ active_yn: next }),
                }
            );
            if (!res.ok) { flash("danger", "토글 실패"); return; }
            loadPrompts();
        } catch (e) {
            flash("danger", `토글 오류: ${e.message}`);
        }
    };

    // ─── 표시 목록 ──────────────────────────────────────────────────
    const displayed = useMemo(() => prompts, [prompts]);

    // ─── 모달 폼 ────────────────────────────────────────────────────
    const renderModal = () => {
        if (!modal) return null;
        const d = modal.data;
        const isEdit = modal.kind === "edit";
        return (
            <Modal show size="lg" onHide={closeModal} scrollable>
                <Modal.Header closeButton>
                    <Modal.Title>{isEdit ? "프롬프트 편집" : "신규 프롬프트 등록"}</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <Form>
                        <Form.Group className="mb-2">
                            <Form.Label>block_id</Form.Label>
                            <Form.Control
                                value={d.block_id}
                                disabled={isEdit}
                                onChange={e => setField("block_id", e.target.value)}
                                placeholder="예: CTRL_SEC1"
                            />
                        </Form.Group>
                        <Form.Group className="mb-2">
                            <Form.Label>category</Form.Label>
                            <Form.Select value={d.category} onChange={e => setField("category", e.target.value)}>
                                {CATEGORIES.filter(c => c.value).map(c => (
                                    <option key={c.value} value={c.value}>{c.label}</option>
                                ))}
                            </Form.Select>
                        </Form.Group>
                        <Form.Group className="mb-2">
                            <Form.Label>section_key</Form.Label>
                            <Form.Control
                                value={d.section_key}
                                onChange={e => setField("section_key", e.target.value)}
                                placeholder="예: CTRL_SEC2"
                            />
                        </Form.Group>
                        <Form.Group className="mb-2">
                            <Form.Label>growth_stage (없으면 공란)</Form.Label>
                            <Form.Select value={d.growth_stage} onChange={e => setField("growth_stage", e.target.value)}>
                                {GROWTH_STAGES.map(s => (
                                    <option key={s} value={s}>{s || "—"}</option>
                                ))}
                            </Form.Select>
                        </Form.Group>
                        <Form.Group className="mb-2">
                            <Form.Label>sort_order</Form.Label>
                            <Form.Control
                                type="number"
                                value={d.sort_order}
                                onChange={e => setField("sort_order", e.target.value)}
                            />
                        </Form.Group>
                        <Form.Group className="mb-2">
                            <Form.Label>name</Form.Label>
                            <Form.Control
                                value={d.name}
                                onChange={e => setField("name", e.target.value)}
                            />
                        </Form.Group>
                        <Form.Group className="mb-2">
                            <Form.Label>body_text</Form.Label>
                            <Form.Control
                                as="textarea"
                                rows={12}
                                value={d.body_text}
                                onChange={e => setField("body_text", e.target.value)}
                                style={{ fontFamily: "monospace", fontSize: "0.82rem" }}
                            />
                        </Form.Group>
                        <Form.Group className="mb-2">
                            <Form.Label>placeholders (JSON)</Form.Label>
                            <Form.Control
                                as="textarea"
                                rows={3}
                                value={d.placeholders}
                                onChange={e => setField("placeholders", e.target.value)}
                                style={{ fontFamily: "monospace", fontSize: "0.82rem" }}
                            />
                        </Form.Group>
                        <Form.Group className="mb-2">
                            <Form.Label>description</Form.Label>
                            <Form.Control
                                value={d.description}
                                onChange={e => setField("description", e.target.value)}
                            />
                        </Form.Group>
                        <Form.Group className="mb-2">
                            <Form.Label>active_yn</Form.Label>
                            <Form.Select value={d.active_yn} onChange={e => setField("active_yn", e.target.value)}>
                                <option value="Y">Y — 활성</option>
                                <option value="N">N — 비활성</option>
                            </Form.Select>
                        </Form.Group>
                    </Form>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={closeModal}>취소</Button>
                    <Button variant="primary" onClick={handleSave}>저장</Button>
                </Modal.Footer>
            </Modal>
        );
    };

    return (
        <Container fluid className="py-3">
            <h4 className="mb-3">LLM 제어 프롬프트 관리 (control_prompt_m)</h4>

            {alert && (
                <Alert variant={alert.variant} dismissible onClose={() => setAlert(null)}>
                    {alert.text}
                </Alert>
            )}

            {/* 필터 + 신규 버튼 */}
            <div className="d-flex gap-2 mb-3 flex-wrap align-items-center">
                <Form.Select
                    style={{ maxWidth: 320 }}
                    value={filterCategory}
                    onChange={e => setFilterCategory(e.target.value)}
                >
                    {CATEGORIES.map(c => (
                        <option key={c.value} value={c.value}>{c.label}</option>
                    ))}
                </Form.Select>
                <Form.Select
                    style={{ maxWidth: 160 }}
                    value={filterGrowth}
                    onChange={e => setFilterGrowth(e.target.value)}
                >
                    {GROWTH_STAGES.map(s => (
                        <option key={s} value={s}>{s || "생육단계 전체"}</option>
                    ))}
                </Form.Select>
                <Button variant="success" onClick={openCreate}>+ 신규 등록</Button>
                <Button variant="outline-secondary" onClick={loadPrompts}>새로고침</Button>
                <span className="ms-auto text-muted small">{displayed.length}건</span>
            </div>

            <Table bordered hover size="sm" style={{ fontSize: "0.82rem" }}>
                <thead className="table-dark">
                    <tr>
                        <th style={{ width: 200 }}>block_id</th>
                        <th style={{ width: 110 }}>category</th>
                        <th style={{ width: 80 }}>생육단계</th>
                        <th style={{ width: 40 }}>sort</th>
                        <th>name</th>
                        <th style={{ width: 50 }}>활성</th>
                        <th style={{ width: 90 }}>updt_dttm</th>
                        <th style={{ width: 100 }}>동작</th>
                    </tr>
                </thead>
                <tbody>
                    {displayed.length === 0 && (
                        <tr><td colSpan={8} className="text-center text-muted">데이터 없음</td></tr>
                    )}
                    {displayed.map(p => (
                        <tr key={p.block_id} className={p.active_yn === "N" ? "table-secondary" : ""}>
                            <td><code style={{ fontSize: "0.78rem" }}>{p.block_id}</code></td>
                            <td>{categoryBadge(p.category)}</td>
                            <td>{p.growth_stage || <span className="text-muted">—</span>}</td>
                            <td className="text-center">{p.sort_order}</td>
                            <td>{p.name}</td>
                            <td className="text-center">
                                <Button
                                    size="sm"
                                    variant={p.active_yn === "Y" ? "success" : "outline-secondary"}
                                    onClick={() => handleToggleActive(p)}
                                    style={{ padding: "0 6px", fontSize: "0.75rem" }}
                                >
                                    {p.active_yn}
                                </Button>
                            </td>
                            <td style={{ fontSize: "0.72rem" }}>
                                {p.updt_dttm ? p.updt_dttm.slice(0, 16) : "—"}
                            </td>
                            <td>
                                <Button size="sm" variant="outline-primary" className="me-1"
                                    onClick={() => openEdit(p)}>편집</Button>
                                <Button size="sm" variant="outline-danger"
                                    onClick={() => handleDelete(p.block_id)}>삭제</Button>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </Table>

            {renderModal()}
        </Container>
    );
}
