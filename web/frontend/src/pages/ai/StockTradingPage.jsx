import React, {useCallback, useEffect, useMemo, useState} from "react";
import {Badge, Button, Card, Col, Container, Form, InputGroup, ListGroup, Modal, Row, Spinner, Tab, Table, Tabs} from "react-bootstrap";
import {useNavigate} from "react-router-dom";
import {
    tradingCandidates, tradingPerformance, tradingRun,
    tradingGetPrompt, tradingSetPrompt, tradingGetUserdata, tradingSetUserdata,
    tradingAnalysis, tradingLearning, tradingLearn,
    tradingStrategies, tradingSaveStrategy, tradingActivateStrategy,
    tradingCandidateStatus, tradingGetExclusions, tradingSetExclusions,
    tradingControlContext, tradingTrends, tradingSeedTrends, tradingLearnPerformance,
    tradingPortfolio, tradingGetFactorWeights, tradingSetFactorWeights,
} from "../../utils/aiChatUtil.js";

// 컨빅션 팩터 라벨(우리 이벤트드리븐 판단축 — ⛔전통 TA 아님)
const FACTOR_LABELS = {
    event_novelty: "사건 신규성", magnitude: "규모", persistence: "지속성",
    sentiment: "심리", supply_demand: "수급", alt_data: "대체데이터", regime_fit: "레짐적합",
};

// ══════════════════════════════════════════════════════════════════════════════
// 주식 자동매매 — 모던 정보형 대시보드 (농장관리와 분리)
//   수치=PostgreSQL trading_*, 판단·분석·학습·방법론=전용 VectorDB(trading_knowledge).
//   핵심: ⛔전통 TA 배제 · 최신 AI/LLM 방법론(이벤트·공시·뉴스·심리·수급·대체데이터) ·
//         관리자 다양한 컨트롤(전략 프리셋·제외·수동 승인) · 자가개선(학습 회상·주입).
// ══════════════════════════════════════════════════════════════════════════════
// 밝은 테마 — 매끄러운 카드 + 명확한 라인 그리드
const G = "linear-gradient(135deg,#5b86e5,#36d1dc)";                 // 밝은 블루→시안 헤더
const PAGE_BG = "#f4f7fb";                                           // 페이지 밝은 배경
const CARD = {border: "1px solid #e3e8ef", borderRadius: 12, boxShadow: "0 2px 10px rgba(30,60,90,.06)"};
const GRID_BORDER = "1px solid #cfd8e3";                             // 명확한 그리드 라인
const TH_BG = "#eef3f9";                                             // 표 헤더 밝은 배경
// 선정구분 색(추천=초록 · 임의=앰버 · 불가=회색)
const SEL_STYLE = {
    "추천": {bg: "#e7f6ec", fg: "#1e7e34", bd: "#a3d9b1", badge: "success"},
    "임의": {bg: "#fff7e6", fg: "#b8860b", bd: "#f0d090", badge: "warning"},
    "불가": {bg: "#f1f3f5", fg: "#6c757d", bd: "#d0d5db", badge: "secondary"},
};

export default function StockTradingPage() {
    const navigate = useNavigate();
    const [candidates, setCandidates] = useState([]);
    const [performance, setPerformance] = useState([]);
    const [analysis, setAnalysis] = useState([]);
    const [learning, setLearning] = useState([]);
    const [prompt, setPrompt] = useState("");
    const [userData, setUserData] = useState({capital: "", max_per_stock: "", daily_loss_limit: ""});
    const [learnText, setLearnText] = useState("");
    const [strategies, setStrategies] = useState([]);
    const [activeStrategy, setActiveStrategy] = useState(null);
    const [newStrat, setNewStrat] = useState({name: "", prompt_text: ""});
    const [exclusions, setExclusions] = useState([]);
    const [exclText, setExclText] = useState("");
    const [controlContext, setControlContext] = useState("");
    const [methodology, setMethodology] = useState([]);
    const [trendContext, setTrendContext] = useState("");
    const [portfolio, setPortfolio] = useState(null);
    const [factorWeights, setFactorWeights] = useState({});
    const [detailCand, setDetailCand] = useState(null);      // 구분 클릭 시 사유 모달
    const [running, setRunning] = useState(false);
    const [msg, setMsg] = useState("");

    const reload = useCallback(async () => {
        try {
            // 개별 엔드포인트 실패가 전체 로드를 막지 않도록 방어(신규 API 미배포 시에도 페이지 정상)
            const safe = (pr) => pr.catch(() => ({data: {}}));
            const [c, p, a, l, pr, ud, st, ex, cc, tr, pf, fw] = await Promise.all([
                tradingCandidates(), tradingPerformance(), tradingAnalysis("매매 판단 분석 실적"),
                tradingLearning(), tradingGetPrompt(), tradingGetUserdata(),
                tradingStrategies(), tradingGetExclusions(), tradingControlContext(), tradingTrends(),
                safe(tradingPortfolio()), safe(tradingGetFactorWeights()),
            ].map(safe));
            setCandidates(c.data.candidates || []);
            setPerformance(p.data.performance || []);
            setAnalysis(a.data.analysis || []);
            setLearning(l.data.learning || []);
            setPrompt(pr.data.prompt || "");
            setUserData({capital: "", max_per_stock: "", daily_loss_limit: "", ...(ud.data.userdata || {})});
            setStrategies(st.data.strategies || []);
            setActiveStrategy(st.data.active || null);
            setExclusions(ex.data.exclusions || []);
            setControlContext(cc.data.context || "");
            setMethodology(tr.data.methodology || []);
            setTrendContext(tr.data.trend_context || "");
            setPortfolio(pf.data.concentration || null);
            setFactorWeights(fw.data.weights || {});
        } catch (e) {
            setMsg("데이터 로드 오류: " + (e?.message || e));
        }
    }, []);

    useEffect(() => { reload(); }, [reload]);

    const num = (v) => (v === null || v === undefined || v === "" ? "-" : Number(v).toLocaleString());

    // KPI 요약
    const kpi = useMemo(() => {
        const approved = candidates.filter((c) => c.status === "approved").length;
        const rets = candidates.map((c) => Number(c.expected_return_pct)).filter((n) => !isNaN(n));
        const avgRet = rets.length ? (rets.reduce((a, b) => a + b, 0) / rets.length).toFixed(1) : "-";
        const closed = performance.filter((p) => p.pnl !== null && p.pnl !== undefined);
        const wins = closed.filter((p) => Number(p.pnl) > 0).length;
        const winRate = closed.length ? Math.round((100 * wins) / closed.length) : "-";
        const totalPnl = closed.reduce((a, b) => a + Number(b.pnl || 0), 0);
        return {total: candidates.length, approved, avgRet, winRate, totalPnl};
    }, [candidates, performance]);

    const handleRun = async () => {
        setRunning(true);
        setMsg("로컬 AI 가 공시·이벤트를 스캔하고, 관리자 컨트롤·최신 방법론·과거 학습을 반영해 종목을 선정 중입니다… (수 분)");
        try {
            const r = await tradingRun();
            setMsg(r.data.success ? `자동매매 스캔 완료 (${r.data.steps}단계). ${r.data.final || ""}` : `실패: ${r.data.message || ""}`);
            await reload();
        } catch (e) { setMsg("실행 오류: " + (e?.message || e)); } finally { setRunning(false); }
    };
    const savePrompt = async () => { await tradingSetPrompt(prompt); setMsg("사용자 프롬프트 저장됨"); await reload(); };
    const saveUserData = async () => { await tradingSetUserdata(userData); setMsg("사용자 데이터 저장됨"); await reload(); };
    const saveLearn = async () => {
        if (!learnText.trim()) return;
        await tradingLearn(learnText.trim()); setLearnText(""); setMsg("학습 데이터 저장됨(VectorDB)");
        const l = await tradingLearning(); setLearning(l.data.learning || []);
    };
    const setStatus = async (c, status) => { await tradingCandidateStatus(c.stock_code, status, c.scan_date); setMsg(`${c.stock_name} → ${status}`); await reload(); };
    const saveStrategy = async () => {
        if (!newStrat.name.trim()) { setMsg("전략 이름을 입력하세요"); return; }
        await tradingSaveStrategy(newStrat.name.trim(), newStrat.prompt_text); setNewStrat({name: "", prompt_text: ""});
        setMsg("전략 저장됨"); await reload();
    };
    const activate = async (name) => { await tradingActivateStrategy(name); setMsg(`활성 전략 → ${name}`); await reload(); };
    const saveExcl = async () => {
        const list = exclText.split(",").map((x) => x.trim()).filter(Boolean);
        await tradingSetExclusions(list); setExclText(""); setMsg("제외 목록 저장됨"); await reload();
    };
    const seedTrends = async () => { await tradingSeedTrends(false); setMsg("최신 방법론 시드 확인/보강 완료"); await reload(); };
    const learnPerf = async () => { const r = await tradingLearnPerformance(); setMsg(r.data.success ? "실적 자가학습 완료(인사이트 저장)" : (r.data.message || "실적 없음")); await reload(); };
    const saveWeights = async () => { await tradingSetFactorWeights(factorWeights); setMsg("팩터 가중치 저장됨(종합 컨빅션·AI 힌트에 반영)"); await reload(); };

    // 컨빅션 색상 + 팩터 분해 툴팁 + 근거 커버리지 뱃지(⛔전통 TA 아님 — 우리 팩터)
    const convColor = (v) => v == null ? "#888" : v >= 70 ? "#2e7d32" : v >= 50 ? "#f9a825" : "#c62828";
    const factorTip = (fs) => !fs ? "" : Object.entries(FACTOR_LABELS)
        .filter(([k]) => fs[k] != null).map(([k, lab]) => `${lab} ${fs[k]}`).join(" · ");
    const CoverageBadges = ({cov}) => {
        if (!cov || !cov.total) return <span className="text-muted">-</span>;
        return (<span title={`근거 ${cov.count}/${cov.total} (신뢰도 ${cov.level})`}>
            {(cov.available_labels || []).map((l, j) => <Badge key={"a" + j} bg="info" className="me-1">{l}</Badge>)}
            {(cov.missing_labels || []).map((l, j) => <Badge key={"m" + j} bg="secondary" className="me-1" style={{opacity: .45}}>{l}✗</Badge>)}
        </span>);
    };

    const Kpi = ({label, value, sub, color}) => (
        <Col xs={6} md={true}>
            <Card className="text-center h-100" style={{...CARD, background: "#fff"}}>
                <Card.Body className="py-2">
                    <div className="text-muted" style={{fontSize: 12}}>{label}</div>
                    <div style={{fontSize: 22, fontWeight: 700, color: color || "#1f2d3d"}}>{value}</div>
                    {sub && <div className="text-muted" style={{fontSize: 11}}>{sub}</div>}
                </Card.Body>
            </Card>
        </Col>
    );

    return (
        <Container fluid className="py-3" style={{maxWidth: 1280, background: PAGE_BG, minHeight: "100vh"}}>
            {/* 헤더 */}
            <div className="p-3 mb-3 rounded text-white d-flex align-items-center justify-content-between flex-wrap"
                 style={{background: G}}>
                <div>
                    <h4 className="mb-1">📈 AI 주식 자동매매 <Badge bg="warning" text="dark">모의투자</Badge></h4>
                    <small style={{opacity: .85}}>이벤트·공시·뉴스·심리·수급·대체데이터 기반 · ⛔전통 차트/TA 배제 · 자가개선</small>
                </div>
                <div className="d-flex gap-2 flex-wrap">
                    <Button variant="light" onClick={handleRun} disabled={running}>
                        {running ? <Spinner animation="border" size="sm"/> : "▶ 자동매매 실행(스캔·선정)"}
                    </Button>
                    <Button variant="outline-light" onClick={reload} disabled={running}>새로고침</Button>
                    <Button variant="outline-light" onClick={() => navigate("/ai-chat")}>← 채팅</Button>
                </div>
            </div>
            {msg && <div className="alert alert-info py-2">{msg}</div>}

            {/* KPI */}
            <Row className="g-2 mb-3">
                <Kpi label="선정 종목" value={kpi.total}/>
                <Kpi label="승인" value={kpi.approved} color="#2e7d32"/>
                <Kpi label="평균 기대수익" value={kpi.avgRet === "-" ? "-" : kpi.avgRet + "%"}/>
                <Kpi label="실적 승률" value={kpi.winRate === "-" ? "-" : kpi.winRate + "%"}/>
                <Kpi label="누적 손익" value={num(kpi.totalPnl) + "원"} color={kpi.totalPnl >= 0 ? "#2e7d32" : "#c62828"}/>
                <Kpi label="활성 전략" value={activeStrategy?.name || "미설정"}/>
            </Row>

            <Tabs defaultActiveKey="dash" className="mb-3">
                {/* 대시보드 — 선정 종목 + 수동 승인/거부 */}
                <Tab eventKey="dash" title="① 선정 종목·승인">
                    {/* 포트폴리오 집중도 — 섹터·이벤트유형 편중 리스크 점검 */}
                    {portfolio && portfolio.total > 0 && (
                        <Card className="mb-3" style={{...CARD, background: "#fff"}}>
                            <Card.Body className="py-2">
                                <Row className="align-items-center">
                                    <Col md="auto"><strong>📊 포트폴리오 집중도</strong> <span className="text-muted small">({portfolio.total}종목)</span></Col>
                                    <Col>
                                        {Object.entries(portfolio.by_event_type || {}).map(([g, info], i) => (
                                            <Badge key={i} bg="info" className="me-1">{g} {Math.round(info.share * 100)}%</Badge>
                                        ))}
                                    </Col>
                                    <Col md="auto">
                                        {portfolio.warning
                                            ? <Badge bg="danger">⚠ {portfolio.notes?.[0]}</Badge>
                                            : <Badge bg="success">분산 양호 (HHI {portfolio.hhi})</Badge>}
                                    </Col>
                                </Row>
                            </Card.Body>
                        </Card>
                    )}
                    <Card style={CARD}>
                        <Card.Header style={{background: TH_BG, fontWeight: 600}}>
                            오늘 스캔 후보 — 관리자 수동 승인/거부(모의투자도 승인제)
                            <span className="text-muted small ms-2">구분: <Badge bg="success">추천</Badge> <Badge bg="warning" text="dark">임의</Badge> <Badge bg="secondary">불가</Badge> · 컨빅션=우리 팩터 종합(⛔전통 TA 아님)</span>
                        </Card.Header>
                        <Card.Body className="p-0" style={{overflowX: "auto"}}>
                            <Table bordered hover size="sm" className="mb-0 align-middle"
                                   style={{"--bs-table-border-color": "#cfd8e3"}}>
                                <thead>
                                <tr style={{background: TH_BG}}>
                                    {["구분", "종목", "코드", "섹터", "이벤트", "매수가", "목표가", "손절가", "기대%", "컨빅션", "근거(커버리지)", "상태", "제어"].map((h, k) => (
                                        <th key={k} style={{background: TH_BG, borderBottom: "2px solid #b6c2d2", whiteSpace: "nowrap"}}>{h}</th>
                                    ))}
                                </tr>
                                </thead>
                                <tbody>
                                {candidates.length === 0 && <tr><td colSpan={13} className="text-center py-4">
                                    <div style={{fontSize: 15, fontWeight: 600, color: "#6c757d"}}>🚫 선정 불가 — 표시할 후보가 없습니다 (관망)</div>
                                    <div className="text-muted small mt-1">추천할 종목도 임의 선정할 종목도 없으면 억지로 만들지 않고 비워둡니다. 새 호재 발생 시 후보가 표시됩니다. · 스캔: 상단 "자동매매 실행"</div>
                                </td></tr>}
                                {candidates.map((c, i) => {
                                    const st = SEL_STYLE[c.selection_type] || SEL_STYLE["추천"];
                                    return (
                                    <tr key={i} style={{background: st.bg}}>
                                        <td style={{borderLeft: "4px solid " + st.bd}}>
                                            <Badge bg={st.badge} text={st.badge === "warning" ? "dark" : undefined}
                                                   style={{cursor: "pointer"}} title="클릭 → 선정 사유 보기"
                                                   onClick={() => setDetailCand(c)}>{c.selection_type || "임의"} ⓘ</Badge>
                                        </td>
                                        <td style={{fontWeight: 600}}>{c.stock_name}</td><td>{c.stock_code}</td><td>{c.sector || "-"}</td><td>{c.event_type}</td>
                                        <td>{num(c.target_buy)}</td><td>{num(c.target_sell)}</td><td>{num(c.stop_loss)}</td>
                                        <td>{c.expected_return_pct ?? "-"}</td>
                                        <td title={factorTip(c.factor_scores)}>
                                            {c.conviction != null
                                                ? <strong style={{color: convColor(c.conviction)}}>{c.conviction}</strong>
                                                : <span className="text-muted" title="확신도">{c.confidence != null ? "(" + c.confidence + ")" : "-"}</span>}
                                        </td>
                                        <td><CoverageBadges cov={c.coverage}/></td>
                                        <td><Badge bg={c.status === "approved" ? "success" : c.status === "rejected" ? "danger" : "warning"} text={c.status !== "approved" && c.status !== "rejected" ? "dark" : undefined}>{c.status}</Badge></td>
                                        <td style={{whiteSpace: "nowrap"}}>
                                            <Button size="sm" variant="outline-success" className="me-1 py-0" onClick={() => setStatus(c, "approved")}>승인</Button>
                                            <Button size="sm" variant="outline-danger" className="py-0" onClick={() => setStatus(c, "rejected")}>거부</Button>
                                        </td>
                                    </tr>);
                                })}
                                </tbody>
                            </Table>
                        </Card.Body>
                    </Card>
                </Tab>

                {/* 관리자 컨트롤 — 전략 프리셋 + 제외 + 리스크 + 프롬프트 + 컨텍스트 미리보기 */}
                <Tab eventKey="control" title="② 관리자 컨트롤">
                    <Row>
                        <Col md={6}>
                            <Card className="mb-3">
                                <Card.Header>전략 프리셋 (활성 전략을 AI 판단에 주입)</Card.Header>
                                <Card.Body>
                                    <ListGroup className="mb-2">
                                        {strategies.length === 0 && <div className="text-muted small">저장된 전략이 없습니다.</div>}
                                        {strategies.map((s, i) => (
                                            <ListGroup.Item key={i} className="d-flex justify-content-between align-items-center py-1">
                                                <span>{s.active_yn === "Y" && <Badge bg="success" className="me-1">활성</Badge>}<b>{s.name}</b>
                                                    <span className="text-muted small ms-2">{(s.prompt_text || "").slice(0, 40)}</span></span>
                                                {s.active_yn !== "Y" && <Button size="sm" variant="outline-primary" className="py-0" onClick={() => activate(s.name)}>활성화</Button>}
                                            </ListGroup.Item>
                                        ))}
                                    </ListGroup>
                                    <InputGroup size="sm" className="mb-2">
                                        <InputGroup.Text>이름</InputGroup.Text>
                                        <Form.Control value={newStrat.name} onChange={(e) => setNewStrat({...newStrat, name: e.target.value})} placeholder="예: 이벤트소수정예"/>
                                    </InputGroup>
                                    <Form.Control as="textarea" rows={2} size="sm" className="mb-2" value={newStrat.prompt_text}
                                                  onChange={(e) => setNewStrat({...newStrat, prompt_text: e.target.value})}
                                                  placeholder="전략 지시(자연어): 예) 자사주·실적 서프라이즈 위주, 하루 3종목 이내, 확신도 0.7↑"/>
                                    <Button size="sm" onClick={saveStrategy}>전략 저장</Button>
                                </Card.Body>
                            </Card>
                            <Card className="mb-3">
                                <Card.Header>제외 종목·섹터 (AI 가 회피)</Card.Header>
                                <Card.Body>
                                    <div className="mb-2">{exclusions.length === 0 ? <span className="text-muted small">제외 없음</span> :
                                        exclusions.map((x, i) => <Badge bg="secondary" className="me-1" key={i}>{x}</Badge>)}</div>
                                    <InputGroup size="sm">
                                        <Form.Control value={exclText} onChange={(e) => setExclText(e.target.value)} placeholder="쉼표로 구분: 삼성전자, 바이오, 000660"/>
                                        <Button size="sm" onClick={saveExcl}>저장</Button>
                                    </InputGroup>
                                </Card.Body>
                            </Card>
                        </Col>
                        <Col md={6}>
                            <Card className="mb-3">
                                <Card.Header>사용자 프롬프트 (전략 지시)</Card.Header>
                                <Card.Body>
                                    <Form.Control as="textarea" rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)}
                                                  placeholder="예: 자기주식취득·실적개선 호재 위주, 종목당 100만원, 손절 -5%"/>
                                    <Button size="sm" className="mt-2" onClick={savePrompt}>프롬프트 저장</Button>
                                </Card.Body>
                            </Card>
                            <Card className="mb-3">
                                <Card.Header>사용자 데이터 (자본·리스크 한도)</Card.Header>
                                <Card.Body>
                                    {[["capital", "자본금(원)"], ["max_per_stock", "종목당 한도(원)"], ["daily_loss_limit", "일일 손실한도(원)"]].map(([k, label]) => (
                                        <Form.Group className="mb-2 d-flex align-items-center" key={k}>
                                            <Form.Label className="mb-0 me-2" style={{width: 140}}>{label}</Form.Label>
                                            <Form.Control size="sm" value={userData[k] || ""} onChange={(e) => setUserData({...userData, [k]: e.target.value})}/>
                                        </Form.Group>
                                    ))}
                                    <Button size="sm" onClick={saveUserData}>사용자 데이터 저장</Button>
                                </Card.Body>
                            </Card>
                            <Card className="mb-3">
                                <Card.Header>컨빅션 팩터 가중치 (종합점수·AI 힌트에 반영 · ⛔전통 TA 아님)</Card.Header>
                                <Card.Body>
                                    <div className="text-muted small mb-2">각 판단 축의 중요도(0~5). 종합 컨빅션 가중합산에 쓰이고 AI 판단 힌트로도 주입됩니다.</div>
                                    {Object.entries(FACTOR_LABELS).map(([k, label]) => (
                                        <Form.Group className="mb-2 d-flex align-items-center" key={k}>
                                            <Form.Label className="mb-0 me-2" style={{width: 110, fontSize: 13}}>{label}</Form.Label>
                                            <Form.Control size="sm" type="number" min={0} max={5} step={0.5} style={{width: 90}}
                                                          value={factorWeights[k] ?? 1}
                                                          onChange={(e) => setFactorWeights({...factorWeights, [k]: e.target.value})}/>
                                        </Form.Group>
                                    ))}
                                    <Button size="sm" onClick={saveWeights}>가중치 저장</Button>
                                </Card.Body>
                            </Card>
                            <Card className="mb-3 border-info">
                                <Card.Header className="text-info">🧭 AI 주입 컨트롤 컨텍스트 (실제 LLM 에 전달되는 지침)</Card.Header>
                                <Card.Body style={{maxHeight: 180, overflowY: "auto"}}>
                                    <pre className="mb-0 small" style={{whiteSpace: "pre-wrap"}}>{controlContext || "관리자 설정(전략·제외·리스크)을 저장하면 여기에 AI 주입 지침이 조립됩니다."}</pre>
                                </Card.Body>
                            </Card>
                        </Col>
                    </Row>
                </Tab>

                {/* 최신 방법론 (트렌드) */}
                <Tab eventKey="trend" title="③ 최신 방법론">
                    <Card className="mb-3 border-warning">
                        <Card.Header className="d-flex justify-content-between align-items-center">
                            <span>최신 AI/LLM 매매 방법론 — ⛔전통 TA 배제 (판단 관점, VectorDB RAG)</span>
                            <Button size="sm" variant="outline-warning" onClick={seedTrends}>방법론 시드/보강</Button>
                        </Card.Header>
                        <Card.Body>
                            <div className="mb-2 p-2 rounded" style={{background: "rgba(255,193,7,.12)"}}>
                                <pre className="mb-0 small" style={{whiteSpace: "pre-wrap"}}>{trendContext}</pre>
                            </div>
                            <ListGroup>
                                {methodology.map((m, i) => (
                                    <ListGroup.Item key={i} className="py-2">
                                        <Badge bg="warning" text="dark" className="me-2">방법론</Badge>
                                        <small>{m.text}</small>
                                    </ListGroup.Item>
                                ))}
                            </ListGroup>
                        </Card.Body>
                    </Card>
                </Tab>

                {/* 자가개선·실적·학습 */}
                <Tab eventKey="learn" title="④ 자가개선·실적">
                    <Row>
                        <Col md={6}>
                            <Card className="mb-3">
                                <Card.Header className="d-flex justify-content-between align-items-center">
                                    <span>매매 실적 (trading_performance)</span>
                                    <Button size="sm" variant="outline-success" onClick={learnPerf}>실적 자가학습</Button>
                                </Card.Header>
                                <Card.Body className="p-0" style={{overflowX: "auto"}}>
                                    <Table bordered hover size="sm" className="mb-0 align-middle" style={{"--bs-table-border-color": "#cfd8e3"}}>
                                        <thead><tr style={{background: TH_BG}}>{["일자", "종목", "손익", "수익%"].map((h, k) => <th key={k} style={{background: TH_BG, borderBottom: "2px solid #b6c2d2"}}>{h}</th>)}</tr></thead>
                                        <tbody>
                                        {performance.length === 0 && <tr><td colSpan={4} className="text-center text-muted py-2">실적 없음</td></tr>}
                                        {performance.map((p, i) => (
                                            <tr key={i}><td>{p.trade_date}</td><td>{p.stock_name}</td>
                                                <td className={p.pnl >= 0 ? "text-success" : "text-danger"}>{num(p.pnl)}</td>
                                                <td>{p.return_pct ?? "-"}</td></tr>
                                        ))}
                                        </tbody>
                                    </Table>
                                </Card.Body>
                            </Card>
                            <Card className="mb-3">
                                <Card.Header>분석·판단 데이터 (AI 판단, VectorDB)</Card.Header>
                                <Card.Body style={{maxHeight: 220, overflowY: "auto"}}>
                                    {analysis.length === 0 && <div className="text-muted">분석·판단 데이터가 아직 없습니다.</div>}
                                    {analysis.map((a, i) => (
                                        <div key={i} className="border-bottom py-1">
                                            <Badge bg="info" className="me-2">{a.category || "일반"}</Badge><small>{a.text}</small>
                                        </div>
                                    ))}
                                </Card.Body>
                            </Card>
                        </Col>
                        <Col md={6}>
                            <Card className="mb-3">
                                <Card.Header>매일 매매 데이터 학습 (VectorDB 저장 → 다음 판단에 회상)</Card.Header>
                                <Card.Body>
                                    <Form.Control as="textarea" rows={2} value={learnText} onChange={(e) => setLearnText(e.target.value)}
                                                  placeholder="오늘 매매 교훈·판단을 기록하면 학습데이터로 저장되고, 다음 스캔에 자동 반영됩니다"/>
                                    <Button size="sm" className="mt-2 mb-2" onClick={saveLearn}>학습데이터 저장</Button>
                                    <div style={{maxHeight: 260, overflowY: "auto"}}>
                                        {learning.map((l, i) => (
                                            <div key={i} className="border-bottom py-1"><small className="text-muted">{l.date}</small> · <small>{l.text}</small></div>
                                        ))}
                                    </div>
                                </Card.Body>
                            </Card>
                        </Col>
                    </Row>
                </Tab>
            </Tabs>

            {/* 선정 사유 모달 — 구분 배지 클릭 시 추천/임의/불가 사유(thesis)·팩터·근거 표시 */}
            <Modal show={!!detailCand} onHide={() => setDetailCand(null)} centered size="lg">
                {detailCand && (() => {
                    const st = SEL_STYLE[detailCand.selection_type] || SEL_STYLE["임의"];
                    const reasonLabel = {"추천": "추천 사유", "임의": "임의(재량) 사유", "불가": "불가(제외) 사유"}[detailCand.selection_type] || "선정 사유";
                    const fs = detailCand.factor_scores || {};
                    const hasFs = Object.keys(FACTOR_LABELS).some((k) => fs[k] != null);
                    return (<>
                        <Modal.Header closeButton style={{background: st.bg, borderBottom: "2px solid " + st.bd}}>
                            <Modal.Title style={{fontSize: 18}}>
                                <Badge bg={st.badge} text={st.badge === "warning" ? "dark" : undefined} className="me-2">{detailCand.selection_type}</Badge>
                                {detailCand.stock_name} <span className="text-muted">({detailCand.stock_code})</span>
                            </Modal.Title>
                        </Modal.Header>
                        <Modal.Body>
                            <div className="mb-2"><strong>이벤트</strong>: {detailCand.event_type || "없음"} · <strong>섹터</strong>: {detailCand.sector || "-"} · <strong>컨빅션</strong>: <span style={{color: convColor(detailCand.conviction)}}>{detailCand.conviction ?? "-"}</span></div>
                            {/* ⭐ LLM 판단 근거(서술) — 사용자·관리자·트레이더가 읽고 매매 판단 */}
                            <Card className="mb-3" style={{...CARD, background: st.bg}}>
                                <Card.Header style={{fontWeight: 600, background: "transparent", borderBottom: "1px solid " + st.bd}}>💬 {reasonLabel} — LLM 판단 근거(읽고 판단)</Card.Header>
                                <Card.Body>
                                    {detailCand.thesis && <div className="mb-2"><Badge bg="light" text="dark" className="me-1">요약</Badge><strong>{detailCand.thesis}</strong></div>}
                                    <div style={{whiteSpace: "pre-wrap", fontSize: 15, lineHeight: 1.65}}>
                                        {detailCand.rationale
                                            || "LLM 판단 근거(서술)가 아직 기록되지 않았습니다. 다음 스캔부터 사건·근거·기대 시나리오·리스크를 사람이 읽는 글로 남깁니다."}
                                    </div>
                                </Card.Body>
                            </Card>
                            <div className="mb-2"><strong>판단 보조 지표(수치화)</strong> <span className="text-muted small">— 판단 근거는 위 <b>글</b>, 아래는 참고 수치(우리 이벤트드리븐 축, ⛔전통 TA 아님)</span></div>
                            {hasFs ? (
                                <Table bordered size="sm" className="mb-3 align-middle" style={{"--bs-table-border-color": "#cfd8e3"}}>
                                    <tbody>
                                    {Object.entries(FACTOR_LABELS).map(([k, lab]) => (
                                        <tr key={k}><td style={{width: 140, background: TH_BG}}>{lab}</td>
                                            <td>{fs[k] != null ? <strong style={{color: convColor(fs[k])}}>{fs[k]}</strong> : <span className="text-muted">판단 안 함</span>}</td></tr>
                                    ))}
                                    </tbody>
                                </Table>
                            ) : <div className="text-muted small mb-3">팩터별 판단이 기록되지 않았습니다(placeholder/근거 부족).</div>}
                            <div className="mb-1"><strong>근거 데이터 커버리지</strong></div>
                            <CoverageBadges cov={detailCand.coverage}/>
                            <div className="text-muted small mt-3">
                                ※ 구분 기준: <Badge bg="success">추천</Badge> 실제 호재 이벤트+근거 확인 · <Badge bg="warning" text="dark">임의</Badge> 호재 없어 재량 선정 · <Badge bg="secondary">불가</Badge> 스캔했으나 부적합. 근거 없는 추천은 자동으로 임의로 표시됩니다.
                            </div>
                        </Modal.Body>
                    </>);
                })()}
            </Modal>
        </Container>
    );
}
