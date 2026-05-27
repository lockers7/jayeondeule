import React, { useEffect, useState, useCallback, useRef } from "react";
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
  const [detail, setDetail] = useState(null);

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
            <tr key={s.id} style={{cursor:"pointer"}} onClick={() => setDetail(s)}>
              <td>{s.id}</td>
              <td>{s.interval_min}</td>
              <td style={{maxWidth:"300px", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap"}}>{s.task}</td>
              <td>{s.total_runs}</td>
              <td style={{fontSize:"0.8em"}}>{fmtTime(s.next_run_at)}</td>
              <td>{s.intent === "__default_cron__" ? <Badge bg="info">기본</Badge> : <Badge bg="primary">사용자</Badge>}</td>
              <td>
                {s.intent !== "__default_cron__" && (
                  <Button size="sm" variant="outline-danger"
                    onClick={(e) => { e.stopPropagation(); handleCancel(s.id); }}>취소</Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>

      {/* 구독 상세 모달 */}
      <Modal show={!!detail} onHide={() => setDetail(null)} size="lg">
        <Modal.Header closeButton>
          <Modal.Title>구독 #{detail?.id} 상세</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {detail && (
            <>
              <Row className="g-2 mb-2">
                <Col xs={6}><strong>ID:</strong> {detail.id}</Col>
                <Col xs={6}><strong>구분:</strong> {detail.intent === "__default_cron__" ? <Badge bg="info">기본</Badge> : <Badge bg="primary">사용자</Badge>}</Col>
                <Col xs={6}><strong>주기:</strong> {detail.interval_min}분</Col>
                <Col xs={6}><strong>실행 횟수:</strong> {detail.total_runs ?? "-"}</Col>
                <Col xs={6}><strong>농장/재배사:</strong> {detail.farm_id ?? "-"} / {detail.house_id ?? "-"}</Col>
                <Col xs={6}><strong>사용자:</strong> {detail.user_id ?? "-"}</Col>
                <Col xs={6}><strong>다음 실행:</strong> {fmtTime(detail.next_run_at)}</Col>
                <Col xs={6}><strong>최근 실행:</strong> {fmtTime(detail.last_run_at)}</Col>
                <Col xs={6}><strong>등록:</strong> {fmtTime(detail.created_at)}</Col>
                <Col xs={6}><strong>상태:</strong> {detail.status ?? "active"}</Col>
              </Row>
              <hr />
              <p className="mb-1"><strong>작업(task):</strong></p>
              <pre style={{whiteSpace:"pre-wrap", background:"#f8f9fa", padding:"10px", borderRadius:"5px"}}>
                {detail.task || "-"}
              </pre>
              {detail.intent && detail.intent !== "__default_cron__" && (
                <>
                  <p className="mb-1"><strong>원본 의도(intent):</strong></p>
                  <pre style={{whiteSpace:"pre-wrap", background:"#f0f0f0", padding:"10px", borderRadius:"5px", fontSize:"0.85em"}}>
                    {detail.intent}
                  </pre>
                </>
              )}
            </>
          )}
        </Modal.Body>
        <Modal.Footer>
          {detail && detail.intent !== "__default_cron__" && (
            <Button variant="outline-danger"
              onClick={() => { handleCancel(detail.id); setDetail(null); }}>구독 취소</Button>
          )}
          <Button variant="secondary" onClick={() => setDetail(null)}>닫기</Button>
        </Modal.Footer>
      </Modal>
    </>
  );
}


// ════════════════════════════════════════════════════════════════════
// 3) 알림 탭
// ════════════════════════════════════════════════════════════════════
function AlertsTab() {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState(null);

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
              <tr key={a.id} style={{cursor:"pointer"}} onClick={() => setDetail(a)}>
                <td style={{fontSize:"0.8em"}}>{fmtTime(a.created_at)}</td>
                <td><Badge bg={a.level === "critical" ? "danger" : a.level === "warning" ? "warning" : "info"}>{a.level}</Badge></td>
                <td>{a.title || "-"}</td>
                <td style={{maxWidth:"400px", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap"}}>{a.body}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      {/* 알림 상세 모달 */}
      <Modal show={!!detail} onHide={() => setDetail(null)} size="lg">
        <Modal.Header closeButton>
          <Modal.Title>알림 #{detail?.id} 상세</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {detail && (
            <>
              <Row className="g-2 mb-2">
                <Col xs={6}><strong>레벨:</strong> <Badge bg={detail.level === "critical" ? "danger" : detail.level === "warning" ? "warning" : "info"}>{detail.level}</Badge></Col>
                <Col xs={6}><strong>시각:</strong> {fmtTime(detail.created_at)}</Col>
                <Col xs={6}><strong>구독 ID:</strong> {detail.subscription_id ?? "-"}</Col>
                <Col xs={6}><strong>Agent 이력 ID:</strong> {detail.agent_log_id ?? "-"}</Col>
                <Col xs={12}><strong>사용자:</strong> {detail.user_id ?? "(전체)"}</Col>
              </Row>
              <hr />
              <p className="mb-1"><strong>{detail.title || "(제목 없음)"}</strong></p>
              <pre style={{whiteSpace:"pre-wrap", background:"#f8f9fa", padding:"10px", borderRadius:"5px", maxHeight:"400px", overflow:"auto"}}>
                {detail.body || "-"}
              </pre>
            </>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setDetail(null)}>닫기</Button>
        </Modal.Footer>
      </Modal>
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
  const [error, setError] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const pollRef = useRef(null);
  const timerRef = useRef(null);
  const startRef = useRef(0);

  const POLL_MS = 3000;
  const MAX_WAIT_MS = 20 * 60 * 1000;   // 20분 안전 상한

  const stopTimers = () => {
    if (pollRef.current) { clearTimeout(pollRef.current); pollRef.current = null; }
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
  };
  // 컴포넌트 unmount 시 polling/timer 정리
  useEffect(() => stopTimers, []);

  // 비-JSON(504/HTML 등) 응답을 의미 있는 에러로 변환
  const safeJson = async (r) => {
    const ct = r.headers.get("content-type") || "";
    if (!ct.includes("application/json")) {
      await r.text().catch(() => "");
      throw new Error(r.status === 504
        ? "게이트웨이 시간 초과(504). 잠시 후 다시 시도하세요."
        : `서버가 JSON이 아닌 응답을 반환 (HTTP ${r.status}).`);
    }
    return r.json();
  };

  // job 상태 polling — running 이면 재예약, done/error 면 결과 표시
  const poll = useCallback(async (jobId) => {
    try {
      const r = await fetch(`${API}/trigger/status/${jobId}`);
      const d = await safeJson(r);
      if (d.status === "running") {
        if (Date.now() - startRef.current > MAX_WAIT_MS) {
          stopTimers(); setRunning(false);
          setError("분석이 20분을 초과했습니다. '사이클 이력' 탭에서 결과를 확인하세요.");
          return;
        }
        pollRef.current = setTimeout(() => poll(jobId), POLL_MS);
        return;
      }
      stopTimers(); setRunning(false); setResult(d);   // done | error
    } catch (e) {
      stopTimers(); setRunning(false); setError(e.message);
    }
  }, []);

  const handleTrigger = async () => {
    if (!task.trim() || running) return;
    setRunning(true); setResult(null); setError(null); setElapsed(0);
    startRef.current = Date.now();
    timerRef.current = setInterval(
      () => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 1000);
    try {
      const r = await fetch(`${API}/trigger`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task, farm_id: farmId }),
      });
      const d = await safeJson(r);
      if (!d.job_id) throw new Error(d.detail || "서버가 job_id를 반환하지 않았습니다.");
      pollRef.current = setTimeout(() => poll(d.job_id), POLL_MS);
    } catch (e) {
      stopTimers(); setRunning(false); setError(e.message);
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
      {running && (
        <Alert variant="info">
          ReAct agent 가 분석 중입니다... ({elapsed}초 경과, 최대 수 분 소요)
          <br /><small className="text-muted">백그라운드 실행이라 탭을 떠나도 결과는 '사이클 이력'에 저장됩니다.</small>
        </Alert>
      )}
      {error && <Alert variant="danger"><strong>✗ 실패</strong> — {error}</Alert>}
      {result && (
        <div className="mt-3">
          <Alert variant={result.success ? "success" : "danger"}>
            <strong>{result.success ? "✓ 분석 완료" : "✗ 실패"}</strong>
            {result.duration_sec && <span> ({result.duration_sec}초, {result.steps}단계)</span>}
            {result.reason && <span> — {result.reason}</span>}
            {result.log_id && <span> · 이력 #{result.log_id}</span>}
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
