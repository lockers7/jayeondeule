import React, { useEffect, useState, useCallback } from "react";
import { Container, Table, Button, Modal, Form, Alert, Badge, Row, Col } from "react-bootstrap";
import { useSelector } from "react-redux";

// ────────────────────────────────────────────────────────────────────
// [프롬프트 자동화 · Phase 5-3] 자체 진화 — 룰 후보 검토/승인 페이지.
// 백엔드 API:
//   GET  /api/v1/admin/rule-candidates?farm_id=&house_id=&days=&min_freq=&top_k=
//   POST /api/v1/admin/rule-candidates/approve  body: {title, content, category, rule_id?, farm_id?, house_id?}
// ai_decision_log 의 정상 결정(action='change') 빈번 패턴을 룰 후보로 추출 →
// 농장주가 검토 후 승인 → ChromaDB domain_rule 등록 → 다음 LLM 호출부터 자동 활용.
// ────────────────────────────────────────────────────────────────────
export default function RuleCandidatesPage() {
    const selectedFarm = useSelector(state => state.auth.selectedFarm);
    const farmId = selectedFarm?.farmId ?? null;

    const [candidates, setCandidates] = useState([]);
    const [loading, setLoading] = useState(false);
    const [days, setDays] = useState(7);
    const [minFreq, setMinFreq] = useState(10);
    const [topK, setTopK] = useState(20);
    const [houseId, setHouseId] = useState("");
    const [editing, setEditing] = useState(null);
    const [editTitle, setEditTitle] = useState("");
    const [editContent, setEditContent] = useState("");
    const [editCategory, setEditCategory] = useState("운영노하우");
    const [alert, setAlert] = useState(null);

    const loadCandidates = useCallback(async () => {
        if (farmId == null) return;
        setLoading(true);
        try {
            const params = new URLSearchParams({
                farm_id: farmId,
                days: String(days),
                min_freq: String(minFreq),
                top_k: String(topK),
            });
            if (houseId !== "") params.set("house_id", String(houseId));
            const res = await fetch(`/ai-api/api/v1/admin/rule-candidates?${params}`);
            const data = await res.json();
            if (data.success) {
                setCandidates(data.candidates || []);
            } else {
                setAlert({ variant: "danger", text: `조회 실패: ${data.detail || "알 수 없음"}` });
            }
        } catch (e) {
            setAlert({ variant: "danger", text: `조회 실패: ${e.message}` });
        } finally {
            setLoading(false);
        }
    }, [farmId, days, minFreq, topK, houseId]);

    useEffect(() => { loadCandidates(); }, [loadCandidates]);

    const openReview = (cand) => {
        setEditing(cand);
        setEditTitle(cand.title || "");
        setEditContent(cand.content || "");
        setEditCategory(cand.category || "운영노하우");
    };

    const approve = async () => {
        if (!editTitle.trim() || !editContent.trim()) {
            setAlert({ variant: "warning", text: "제목과 본문은 비어있을 수 없습니다." });
            return;
        }
        try {
            const body = {
                title: editTitle,
                content: editContent,
                category: editCategory,
                farm_id: farmId,
            };
            if (houseId !== "") body.house_id = parseInt(houseId, 10);
            const res = await fetch("/ai-api/api/v1/admin/rule-candidates/approve", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            const data = await res.json();
            if (data.success) {
                setAlert({
                    variant: "success",
                    text: `룰 등록 완료 (rule_id=${data.rule_id}). 다음 LLM 호출부터 자동 활용됩니다.`,
                });
                setEditing(null);
            } else {
                setAlert({ variant: "danger", text: `등록 실패: ${data.detail || data.error || "알 수 없음"}` });
            }
        } catch (e) {
            setAlert({ variant: "danger", text: `등록 실패: ${e.message}` });
        }
    };

    if (farmId == null) {
        return (
            <Container className="py-4">
                <Alert variant="warning">
                    농장을 먼저 선택하세요. 상단 농장 선택 메뉴에서 대상 농장을 지정해야 합니다.
                </Alert>
            </Container>
        );
    }

    return (
        <Container className="py-4">
            <h2 className="mb-3">자체 진화 — 룰 후보 검토</h2>
            <p className="text-muted small mb-3">
                AI 의사결정 로그에서 빈번한 정상 결정 패턴을 추출하여 룰 후보로 제시합니다.
                농장주가 검토하여 승인하면 ChromaDB 학습 데이터로 등록되고, 이후 LLM 판단 시 자동 참고됩니다.
            </p>

            {alert && (
                <Alert variant={alert.variant} dismissible onClose={() => setAlert(null)}>
                    {alert.text}
                </Alert>
            )}

            <Row className="mb-3 g-2 align-items-end">
                <Col xs="auto">
                    <Form.Label className="small mb-1">조회 기간(일)</Form.Label>
                    <Form.Control size="sm" type="number" min={1} max={90}
                                  value={days} onChange={(e) => setDays(parseInt(e.target.value || "7", 10))}
                                  style={{ width: "90px" }}/>
                </Col>
                <Col xs="auto">
                    <Form.Label className="small mb-1">최소 빈도</Form.Label>
                    <Form.Control size="sm" type="number" min={1}
                                  value={minFreq} onChange={(e) => setMinFreq(parseInt(e.target.value || "10", 10))}
                                  style={{ width: "90px" }}/>
                </Col>
                <Col xs="auto">
                    <Form.Label className="small mb-1">상위 N건</Form.Label>
                    <Form.Control size="sm" type="number" min={1} max={100}
                                  value={topK} onChange={(e) => setTopK(parseInt(e.target.value || "20", 10))}
                                  style={{ width: "90px" }}/>
                </Col>
                <Col xs="auto">
                    <Form.Label className="small mb-1">재배사 ID (선택)</Form.Label>
                    <Form.Control size="sm" type="number" placeholder="전체"
                                  value={houseId} onChange={(e) => setHouseId(e.target.value)}
                                  style={{ width: "120px" }}/>
                </Col>
                <Col xs="auto">
                    <Button size="sm" variant="primary" onClick={loadCandidates} disabled={loading}>
                        {loading ? "조회 중..." : "다시 조회"}
                    </Button>
                </Col>
            </Row>

            <Table striped bordered hover size="sm">
                <thead>
                    <tr>
                        <th style={{ width: "60px" }}>빈도</th>
                        <th>제목</th>
                        <th>본문 요약</th>
                        <th style={{ width: "110px" }}>관리</th>
                    </tr>
                </thead>
                <tbody>
                    {candidates.length === 0 ? (
                        <tr>
                            <td colSpan={4} className="text-center text-muted py-4">
                                {loading ? "조회 중..." : "표시할 후보가 없습니다 (조건을 완화해 보세요)."}
                            </td>
                        </tr>
                    ) : (
                        candidates.map((c, idx) => (
                            <tr key={`${c.title}-${idx}`}>
                                <td>
                                    <Badge bg={c.frequency >= 100 ? "danger" : c.frequency >= 30 ? "warning" : "secondary"}>
                                        {c.frequency}회
                                    </Badge>
                                </td>
                                <td><strong>{c.title}</strong></td>
                                <td className="small text-muted">
                                    {(c.content || "").split("\n")[0].slice(0, 100)}
                                    {(c.content || "").length > 100 ? "..." : ""}
                                </td>
                                <td>
                                    <Button size="sm" variant="outline-primary" onClick={() => openReview(c)}>
                                        검토/승인
                                    </Button>
                                </td>
                            </tr>
                        ))
                    )}
                </tbody>
            </Table>

            <Modal show={!!editing} onHide={() => setEditing(null)} size="lg">
                <Modal.Header closeButton>
                    <Modal.Title>룰 후보 검토</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <p className="text-muted small">
                        승인 시 ChromaDB <code>domain_rule</code> 컬렉션에 등록되어 LLM 의 의사결정 시
                        의미 검색으로 참고됩니다. 제목·본문은 등록 전에 자유롭게 다듬을 수 있습니다.
                    </p>
                    {editing?.pattern && (
                        <Alert variant="light" className="small mb-3">
                            <strong>원시 패턴:</strong> 순환={editing.pattern.circulation}, 수온히터={editing.pattern.water_heater ? "ON" : "OFF"},
                            포그={editing.pattern.fog_occurs ? "ON" : "OFF"}, 빈도={editing.pattern.frequency}회
                        </Alert>
                    )}
                    <Form.Group className="mb-3">
                        <Form.Label>제목 (30자 이내 권장)</Form.Label>
                        <Form.Control
                            type="text" maxLength={60}
                            value={editTitle}
                            onChange={(e) => setEditTitle(e.target.value)}
                        />
                        <Form.Text className="text-muted">{editTitle.length} / 60</Form.Text>
                    </Form.Group>
                    <Form.Group className="mb-3">
                        <Form.Label>본문</Form.Label>
                        <Form.Control
                            as="textarea" rows={10}
                            style={{ fontFamily: "monospace", fontSize: "12px" }}
                            value={editContent}
                            onChange={(e) => setEditContent(e.target.value)}
                        />
                        <Form.Text className="text-muted">{editContent.length} bytes</Form.Text>
                    </Form.Group>
                    <Form.Group>
                        <Form.Label>분류</Form.Label>
                        <Form.Select value={editCategory} onChange={(e) => setEditCategory(e.target.value)}>
                            <option value="운영노하우">운영노하우</option>
                            <option value="안전">안전</option>
                            <option value="결합규칙">결합규칙</option>
                            <option value="기타">기타</option>
                        </Form.Select>
                    </Form.Group>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={() => setEditing(null)}>취소</Button>
                    <Button variant="primary" onClick={approve}>승인 (ChromaDB 등록)</Button>
                </Modal.Footer>
            </Modal>
        </Container>
    );
}
