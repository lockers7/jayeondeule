import React, { useEffect, useState, useCallback } from "react";
import {
  Container, Table, Button, Badge, Alert, Row, Col, Form,
  Tabs, Tab, Modal, Spinner
} from "react-bootstrap";

// ══════════════════════════════════════════════════════════════════════
// Agent 이력 관리 페이지 (Phase 4 W) [2026-05-27]
//
// 탭 4개:
//   1. 사이클 이력   — agent_decision_log 타임라인 (성공/실패/도구/보고 미리보기)
//   2. 구독 관리     — agent_subscriptions 목록 + 등록/취소
//   3. 알림          — agent_user_alerts 미읽/전체
//   4. 즉시 분석     — agent_one_shot 수동 trigger
//
// API: /ai-api/api/v1/agent/* (agent_router.py)
// ══════════════════════════════════════════════════════════════════════
const API = "/ai-api/api/v1/agent";

// ─── 유틸 ───
const fmtTime = (s) => s ? new Date(s).toLocaleString("ko-KR", { hour12: false }) : "-";
const badgeVariant = (ok) => ok ? "success" : "danger";

export default function AgentHistoryPage() {
  const [tab, setTab] = useState("history");

  return (
    <Container className="py-3">
      <h4 className="mb-3">🤖 AI Agent 관리</h4>
      <Tabs activeKey={tab} onSelect={setTab} className="mb-3">
        <Tab eventKey="history" title="사이클 이력">
          <HistoryTab />
        </Tab>
        <Tab eventKey="subs" title="구독 관리">
          <SubsTab />
        </Tab>
        <Tab eventKey="alerts" title="알림">
          <AlertsTab />
        </Tab>
        <Tab eventKey="trigger" title="즉시 분석">
          <TriggerTab />
        </Tab>
      </Tabs>
    </Container>
  );
}


// ════════════════════════════════════════════════════════════════════
// 1) 사이클 이력 탭
// ════════════════════════════════════════════════════════════════════
function HistoryTab() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(0);
  const [detail, setDetail] = useState(null);
  const limit = 15;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/history?limit=${limit}&offset=${page * limit}`);
      const d = await r.json();
      if (d.success) { setItems(d.items); setTotal(d.total); }
    } finally { setLoading(false); }
  }, [page]);

  useEffect(() => { load(); }, [load]);

  const openDetail = async (id) => {
    const r = await fetch(`${API}/history/${id}`);
    const d = await r.json();
    if (d.success !== false) setDetail(d);
  };

  return (
    <>
      {loading && <Spinner animation="border" size="sm" />}
      <Table striped bordered hover size="sm" responsive>
        <thead>
          <tr>
            <th>ID</th><th>시작</th><th>유형</th><th>성공</th>
            <th>소요(s)</th><th>LLM</th><th>도구</th><th>보고 미리보기</th>
          </tr>
        </thead>
        <tbody>
          {items.map(it => (
            <tr key={it.id} style={{cursor:"pointer"}} onClick={() => openDetail(it.id)}>
              <td>{it.id}</td>
              <td style={{fontSize:"0.8em"}}>{fmtTime(it.started_at)}</td>
              <td><Badge bg="secondary">{it.trigger_type}</Badge></td>
              <td><Badge bg={badgeVariant(it.success)}>{it.success ? "✓" : "✗"}</Badge></td>
              <td>{it.duration_sec ?? "-"}</td>
              <td>{it.llm_calls}</td>
              <td style={{fontSize:"0.75em"}}>{it.tool_calls ? JSON.stringify(it.tool_calls) : "-"}</td>
              <td style={{fontSize:"0.8em", maxWidth:"300px", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap"}}>
                {it.final_preview || it.reason || "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      <div className="d-flex justify-content-between">
        <Button size="sm" disabled={page === 0} onClick={() => setPage(p => p - 1)}>이전</Button>
        <span>{page * limit + 1}~{Math.min((page + 1) * limit, total)} / {total}</span>
        <Button size="sm" disabled={(page + 1) * limit >= total} onClick={() => setPage(p => p + 1)}>다음</Button>
      </div>

      {/* 상세 모달 */}
      <Modal show={!!detail} onHide={() => setDetail(null)} size="lg">
        <Modal.Header closeButton>
          <Modal.Title>사이클 #{detail?.id} 상세</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {detail && (
            <>
              <p><strong>Task:</strong> {detail.task}</p>
              <p><strong>결과:</strong> <Badge bg={badgeVariant(detail.success)}>{detail.success ? "성공" : "실패"}</Badge> {detail.reason}</p>
              <p><strong>소요:</strong> {detail.duration_sec}s / LLM {detail.llm_calls}회</p>
              <p><strong>도구:</strong> {JSON.stringify(detail.tool_calls)}</p>
              <hr />
              <p><strong>최종 보고:</strong></p>
              <pre style={{whiteSpace:"pre-wrap", maxHeight:"300px", overflow:"auto", background:"#f8f9fa", padding:"10px", borderRadius:"5px"}}>
                {detail.final_report || "(없음)"}
              </pre>
              <hr />
              <p><strong>Step History:</strong></p>
              <pre style={{whiteSpace:"pre-wrap", maxHeight:"400px", overflow:"auto", background:"#f0f0f0", padding:"10px", borderRadius:"5px", fontSize:"0.8em"}}>
                {JSON.stringify(detail.steps, null, 2)}
              </pre>
            </>
          )}
        </Modal.Body>
      </Modal>
    </>
  );
}


// ════════════════════════════════════════════════════════════════════
// 2) 구독 관리 탭
// ════════════════════════════════════════════════════════════════════
function SubsTab() {
  const [subs, setSubs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [newTask, setNewTask] = useState("");
  const [newInterval, setNewInterval] = useState(30);
  const [alert, setAlert] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/subscriptions?include_default=true`);
      const d = await r.json();
      if (d.success) setSubs(d.subscriptions || []);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSubscribe = async () => {
    if (!newTask.trim()) return;
    try {
      const r = await fetch(`${API}/subscribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task: newTask, interval_min: newInterval, farm_id: 1 }),
      });
      const d = await r.json();
      if (d.success) {
        setAlert({ variant: "success", text: `등록 완료 (id=${d.subscription_id})` });
        setNewTask("");
        load();
      } else {
        setAlert({ variant: "danger", text: d.message || d.detail });
      }
    } catch (e) {
      setAlert({ variant: "danger", text: e.message });
    }
  };

  const handleCancel = async (id) => {
    if (!window.confirm(`구독 #${id} 취소?`)) return;
    const r = await fetch(`${API}/subscriptions/${id}/cancel`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    });
    const d = await r.json();
    if (d.success) { setAlert({ variant: "info", text: `#${id} 취소됨` }); load(); }
    else setAlert({ variant: "danger", text: d.message || d.detail });
  };

  return (
    <>
      {alert && <Alert variant={alert.variant} dismissible onClose={() => setAlert(null)}>{alert.text}</Alert>}

      {/* 신규 등록 */}
      <Row className="mb-3 g-2">
        <Col md={6}><Form.Control placeholder="모니터링 작업 (한국어)" value={newTask} onChange={e => setNewTask(e.target.value)} /></Col>
        <Col md={2}><Form.Control type="number" min={5} max={1440} value={newInterval} onChange={e => setNewInterval(Number(e.target.value))} /></Col>
        <Col md={2}><Button onClick={handleSubscribe} disabled={!newTask.trim()}>등록</Button></Col>
      </Row>

      {loading && <Spinner animation="border" size="sm" />}
      <Table striped bordered size="sm" responsive>
        <thead><tr><th>ID</th><th>주기(분)</th><th>작업</th><th>실행횟수</th><th>다음실행</th><th>상태</th><th>동작</th></tr></thead>
        <tbody>
          {subs.map(s => (
            <tr key={s.id}>
              <td>{s.id}</td>
              <td>{s.interval_min}</td>
              <td style={{maxWidth:"300px", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap"}}>{s.task}</td>
              <td>{s.total_runs}</td>
              <td style={{fontSize:"0.8em"}}>{fmtTime(s.next_run_at)}</td>
              <td>{s.intent === "__default_cron__" ? <Badge bg="info">기본</Badge> : <Badge bg="primary">사용자</Badge>}</td>
              <td>
                {s.intent !== "__default_cron__" && (
                  <Button size="sm" variant="outline-danger" onClick={() => handleCancel(s.id)}>취소</Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
    </>
  );
}


// ════════════════════════════════════════════════════════════════════
// 3) 알림 탭
// ════════════════════════════════════════════════════════════════════
function AlertsTab() {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/alerts?limit=50&mark_read=false`);
      const d = await r.json();
      if (d.success) setAlerts(d.alerts || []);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const markRead = async () => {
    await fetch(`${API}/alerts?mark_read=true&limit=50`);
    load();
  };

  return (
    <>
      <div className="mb-2 d-flex justify-content-between">
        <span>미읽 알림 {alerts.length}건</span>
        <Button size="sm" variant="outline-primary" onClick={markRead}>모두 읽음 처리</Button>
      </div>
      {loading && <Spinner animation="border" size="sm" />}
      {alerts.length === 0 ? (
        <Alert variant="info">알림이 없습니다.</Alert>
      ) : (
        <Table striped bordered size="sm" responsive>
          <thead><tr><th>시각</th><th>레벨</th><th>제목</th><th>내용 미리보기</th></tr></thead>
          <tbody>
            {alerts.map(a => (
              <tr key={a.id}>
                <td style={{fontSize:"0.8em"}}>{fmtTime(a.created_at)}</td>
                <td><Badge bg={a.level === "critical" ? "danger" : a.level === "warning" ? "warning" : "info"}>{a.level}</Badge></td>
                <td>{a.title || "-"}</td>
                <td style={{maxWidth:"400px", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap"}}>{a.body}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </>
  );
}


// ════════════════════════════════════════════════════════════════════
// 4) 즉시 분석 탭
// ════════════════════════════════════════════════════════════════════
function TriggerTab() {
  const [task, setTask] = useState("농장 1 전체 호기 현재 센서 상태 + 임계 근접 + AI 결정 추세 종합 진단");
  const [farmId, setFarmId] = useState(1);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);

  const handleTrigger = async () => {
    if (!task.trim() || running) return;
    setRunning(true);
    setResult(null);
    try {
      const r = await fetch(`${API}/trigger`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task, farm_id: farmId }),
      });
      const d = await r.json();
      setResult(d);
    } catch (e) {
      setResult({ success: false, reason: e.message });
    } finally {
      setRunning(false);
    }
  };

  return (
    <>
      <Row className="mb-3 g-2">
        <Col md={8}><Form.Control placeholder="분석 작업 (한국어)" value={task} onChange={e => setTask(e.target.value)} /></Col>
        <Col md={2}><Form.Control type="number" value={farmId} onChange={e => setFarmId(Number(e.target.value))} /></Col>
        <Col md={2}><Button onClick={handleTrigger} disabled={running || !task.trim()}>
          {running ? <><Spinner animation="border" size="sm" /> 분석 중...</> : "즉시 분석"}
        </Button></Col>
      </Row>
      {running && <Alert variant="info">ReAct agent 가 분석 중입니다... (100~250초 소요)</Alert>}
      {result && (
        <div className="mt-3">
          <Alert variant={result.success ? "success" : "danger"}>
            <strong>{result.success ? "✓ 분석 완료" : "✗ 실패"}</strong>
            {result.duration_sec && <span> ({result.duration_sec}초, {result.steps}단계)</span>}
            {result.reason && <span> — {result.reason}</span>}
          </Alert>
          {result.final && (
            <pre style={{whiteSpace:"pre-wrap", background:"#f8f9fa", padding:"12px", borderRadius:"5px"}}>
              {result.final}
            </pre>
          )}
        </div>
      )}
    </>
  );
}
