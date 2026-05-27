import { useState, useEffect } from 'react';
import { Container, Row, Col, Form, Button, Badge, Alert, Spinner } from 'react-bootstrap';
import api from '../api/client';
import { LOTTO_ALGORITHM_INFO } from './lottoAlgorithmInfo';

const BALL_COLORS = {
  1: '#fbc400', 10: '#69c8f2', 20: '#ff7272', 30: '#aaa', 40: '#b0d840',
};

function getBallColor(n) {
  if (n <= 10) return BALL_COLORS[1];
  if (n <= 20) return BALL_COLORS[10];
  if (n <= 30) return BALL_COLORS[20];
  if (n <= 40) return BALL_COLORS[30];
  return BALL_COLORS[40];
}

function LottoBall({ number, size = 44, bonus = false }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      background: getBallColor(number),
      color: '#fff', fontWeight: 900, fontSize: size * 0.4,
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
      border: bonus ? '3px solid var(--shop-accent)' : 'none',
      marginRight: bonus ? 0 : 6,
    }}>
      {number}
    </div>
  );
}

export default function LottoPage() {
  const [tab, setTab] = useState('check');
  const [draws, setDraws] = useState([]);
  const [selectedDraw, setSelectedDraw] = useState('');
  const [result, setResult] = useState(null);
  const algorithm = LOTTO_ALGORITHM_INFO;
  const [prompt, setPrompt] = useState('');
  const [recommendation, setRecommendation] = useState(null);
  const [loading, setLoading] = useState(false);

  // 회차 목록 로드
  useEffect(() => {
    api.get('/lotto/draws')
      .then(({ data }) => {
        if (data.success) {
          setDraws(data.data || []);
          if (data.data?.length > 0) setSelectedDraw(String(data.data[0].draw_no));
        }
      }).catch(() => {});
  }, []);

  // 회차 선택 시 결과 로드
  useEffect(() => {
    if (!selectedDraw) return;
    api.get('/lotto/results', { params: { drawNo: selectedDraw } })
      .then(({ data }) => {
        if (data.success && data.data?.length > 0) setResult(data.data[0]);
      }).catch(() => {});
  }, [selectedDraw]);

  // 추천 번호 생성 (LLM 호출이라 ~20초 소요)
  const generateRecommendation = async () => {
    setLoading(true);
    try {
      const { data } = await api.post('/lotto/recommend', { prompt }, { timeout: 120000 });
      if (data.success) setRecommendation(data.data);
    } catch { /* ignore */ }
    setLoading(false);
  };

  return (
    <>
      <div className="page-header">
        <Container>
          <h1 className="page-header-title">🎱 로또놀이</h1>
          <p className="page-header-desc">AI가 분석한 재미있는 로또 번호 추천 (재미 목적)</p>
        </Container>
      </div>

      <section className="shop-section">
        <Container>
          <Row>
            <Col lg={3}>
              <div className="efficacy-nav">
                <div style={{ padding: '12px 16px', fontWeight: 700, color: 'var(--shop-primary)' }}>메뉴</div>
                {[
                  { key: 'check', label: '🔍 당첨번호 확인' },
                  { key: 'algorithm', label: '🧠 추천 알고리즘' },
                  { key: 'recommend', label: '🎯 번호 추천받기' },
                ].map(({ key, label }) => (
                  <button key={key} className={`efficacy-nav-item ${tab === key ? 'active' : ''}`}
                    onClick={() => setTab(key)}>{label}</button>
                ))}
              </div>
            </Col>

            <Col lg={9}>
              {/* 당첨번호 확인 */}
              {tab === 'check' && (
                <div className="efficacy-card">
                  <h3>당첨번호 확인</h3>
                  <Form.Group className="mb-4">
                    <Form.Label className="fw-bold">회차 선택</Form.Label>
                    <Form.Select value={selectedDraw} onChange={(e) => setSelectedDraw(e.target.value)}
                      style={{ maxWidth: '300px' }}>
                      {draws.map((d) => (
                        <option key={d.draw_no} value={d.draw_no}>
                          {d.draw_no}회 ({d.draw_date})
                        </option>
                      ))}
                    </Form.Select>
                  </Form.Group>

                  {result && (
                    <div className="text-center py-4" style={{ background: 'var(--shop-bg-warm)', borderRadius: '16px', padding: '30px' }}>
                      <div className="mb-2" style={{ fontSize: '0.9rem', color: 'var(--shop-text-light)' }}>
                        제 <strong>{result.draw_no}</strong>회 ({result.draw_date})
                      </div>
                      <div className="d-flex align-items-center justify-content-center gap-2 mb-3">
                        {[result.num1, result.num2, result.num3, result.num4, result.num5, result.num6].map((n, i) => (
                          <LottoBall key={i} number={n} size={52} />
                        ))}
                        <span style={{ fontSize: '1.5rem', fontWeight: 300, color: '#999', margin: '0 8px' }}>+</span>
                        <LottoBall number={result.bonus} size={52} bonus />
                      </div>
                      <div style={{ fontSize: '0.85rem', color: 'var(--shop-text-light)' }}>
                        합계: {result.num1 + result.num2 + result.num3 + result.num4 + result.num5 + result.num6}
                        {' | '}보너스: {result.bonus}
                      </div>
                    </div>
                  )}

                  {/* 추천 번호와 당첨 번호 차이 분석 (LLM 단일 추천) */}
                  {result && (() => {
                    const llmRecs = (result.recommendations || []).filter((r) => r.source === 'llm');
                    return (
                    <div className="mt-4">
                      <h4 style={{ color: 'var(--shop-primary-dark)', borderLeft: '4px solid var(--shop-accent)', paddingLeft: '12px' }}>
                        🤖 LLM 추천 vs 당첨 번호 비교
                      </h4>
                      {llmRecs.length > 0 ? (
                        <div className="mt-3">
                          {llmRecs.map((rec) => {
                            let nums = [];
                            let matched = [];
                            try { nums = JSON.parse(rec.numbers || '[]'); } catch { nums = []; }
                            try { matched = JSON.parse(rec.matched_nums || '[]'); } catch { matched = []; }
                            const matchedSet = new Set(matched);
                            return (
                              <div key={`llm-${rec.rec_no}`} className="mb-3" style={{ background: '#E8F5E9', borderRadius: '12px', padding: '20px', border: '2px solid #66BB6A' }}>
                                <div className="d-flex align-items-center flex-wrap gap-2 mb-2">
                                  <Badge bg="success" style={{ fontSize: '0.9rem', padding: '8px 12px' }}>🤖 LLM 직접 선정</Badge>
                                  <Badge bg={rec.match_count >= 3 ? 'success' : (rec.match_count >= 1 ? 'warning' : 'secondary')} style={{ fontSize: '0.85rem', padding: '8px 12px' }}>
                                    일치 {rec.match_count ?? 0} / 불일치 {rec.miss_count ?? 6}{rec.bonus_match ? ' + 보너스 ✓' : ''}
                                  </Badge>
                                </div>
                                <div className="d-flex align-items-center flex-wrap gap-2">
                                  {nums.map((n, i) => (
                                    <div key={i} style={{ position: 'relative' }}>
                                      <LottoBall number={n} size={44} />
                                      {matchedSet.has(n) && (
                                        <span style={{
                                          position: 'absolute', top: -4, right: 2,
                                          background: '#27ae60', color: '#fff',
                                          borderRadius: '50%', width: 18, height: 18,
                                          fontSize: 12, display: 'flex',
                                          alignItems: 'center', justifyContent: 'center',
                                          fontWeight: 700,
                                        }}>✓</span>
                                      )}
                                    </div>
                                  ))}
                                  <span style={{ fontSize: '1.2rem', fontWeight: 300, color: '#999', margin: '0 6px' }}>+</span>
                                  <LottoBall number={rec.bonus} size={44} bonus />
                                </div>
                              </div>
                            );
                          })}
                          {/* LLM 종합 분석 */}
                          {result.llm_analysis ? (
                            <div className="mt-3" style={{ background: '#F1F8E9', borderRadius: '12px', padding: '20px', border: '1px solid #C5E1A5' }}>
                              <div className="mb-2" style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--shop-primary-dark)' }}>
                                🤖 LLM 종합 분석
                              </div>
                              <div style={{ whiteSpace: 'pre-wrap', fontSize: '0.93rem', lineHeight: 1.7, color: '#444' }}>
                                {result.llm_analysis}
                              </div>
                              {result.analysis_dt && (
                                <div className="mt-2" style={{ fontSize: '0.75rem', color: 'var(--shop-text-light)', textAlign: 'right' }}>
                                  분석 시각: {String(result.analysis_dt).replace('T', ' ').substring(0, 19)}
                                </div>
                              )}
                            </div>
                          ) : (
                            <Alert variant="light" className="mt-3" style={{ border: '1px dashed var(--shop-border)', fontSize: '0.85rem' }}>
                              이 회차의 LLM 종합 분석은 아직 작성되지 않았습니다 (배치 재실행 필요).
                            </Alert>
                          )}
                        </div>
                      ) : (
                        <Alert variant="light" className="mt-3" style={{ border: '1px dashed var(--shop-border)' }}>
                          이 회차는 아직 LLM 분석이 진행되지 않았습니다 (501회부터 순차 분석).
                        </Alert>
                      )}
                    </div>
                    );
                  })()}
                </div>
              )}

              {/* 추천 알고리즘 설명 */}
              {tab === 'algorithm' && (
                <>
                  <div className="efficacy-card">
                    <h3>추천 알고리즘</h3>
                    <div>
                      <Badge bg="info" className="mb-3" style={{ fontSize: '0.85rem', padding: '8px 16px' }}>
                        {algorithm.name} v{algorithm.version}
                      </Badge>
                      <div style={{ fontSize: '0.95rem', lineHeight: 1.9, whiteSpace: 'pre-wrap' }}
                        dangerouslySetInnerHTML={{
                          __html: (algorithm.description || '')
                            .replace(/#### (.*)/g, '<h5 style="color:var(--shop-primary);margin-top:20px;font-size:1.05rem">$1</h5>')
                            .replace(/### (.*)/g, '<h4 style="color:var(--shop-primary-dark);margin-top:24px">$1</h4>')
                            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                            .replace(/> (.*)/g, '<div style="background:#FFF3E0;padding:12px 16px;border-radius:8px;border-left:4px solid var(--shop-accent);margin:16px 0">$1</div>')
                            .replace(/---/g, '<hr style="border-color:var(--shop-border);margin:20px 0"/>')
                            .replace(/\n\n/g, '<br/><br/>')
                        }} />
                    </div>
                  </div>
                  {algorithm?.funFacts && (
                    <div className="efficacy-card mt-3">
                      <h3>🎲 재미있는 알고리즘</h3>
                      <p className="text-muted mb-3">추천 번호 생성 시 아래 요소가 함께 반영됩니다</p>
                      <div style={{ fontSize: '0.95rem', lineHeight: 1.9, whiteSpace: 'pre-wrap' }}
                        dangerouslySetInnerHTML={{
                          __html: (algorithm.funFacts || '')
                            .replace(/### (.*)/g, '<h4 style="color:var(--shop-primary-dark);margin-top:24px">$1</h4>')
                            .replace(/#### (.*)/g, '<h5 style="color:var(--shop-primary);margin-top:20px;font-size:1.05rem">$1</h5>')
                            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                            .replace(/> (.*)/g, '<div style="background:#E8F5E9;padding:12px 16px;border-radius:8px;border-left:4px solid var(--shop-primary);margin:16px 0">$1</div>')
                            .replace(/---/g, '<hr style="border-color:var(--shop-border);margin:20px 0"/>')
                            .replace(/\n\n/g, '<br/><br/>')
                        }} />
                    </div>
                  )}
                </>
              )}

              {/* 번호 추천받기 */}
              {tab === 'recommend' && (
                <div className="efficacy-card">
                  <h3>🎯 번호 추천받기</h3>

                  <Form.Group className="mb-3">
                    <Form.Label className="fw-bold">
                      추가 조건 <span style={{ color: 'var(--shop-text-light)', fontWeight: 'normal', fontSize: '0.85rem' }}>(자유롭게 자연어로 입력 / 선택사항)</span>
                    </Form.Label>
                    <Form.Control
                      as="textarea" rows={4}
                      value={prompt}
                      onChange={(e) => setPrompt(e.target.value)}
                      placeholder={'LLM에게 어떤 조건으로 번호를 골라달라고 요청할지 자유롭게 적어주세요.\n\n예시:\n- 당첨 빈도가 높은 번호 위주로\n- 최근 안 나온 번호로 회귀 기대\n- 핫넘버 3개 이상, 짝수 위주\n- 7, 21, 33은 꼭 포함하고 1~5는 제외'}
                    />
                    <div className="mt-2 d-flex flex-wrap gap-1">
                      <span style={{ fontSize: '0.78rem', color: 'var(--shop-text-light)', alignSelf: 'center' }}>빠른 예시:</span>
                      {[
                        '당첨 빈도가 높은 번호 위주',
                        '최근 핫넘버 위주',
                        '오래 안 나온 번호 위주',
                        '소수 많이, 합계 130 근처',
                        '큰 번호(30 이상) 위주',
                        '홀수 4개 이상',
                      ].map((q) => (
                        <Button key={q} size="sm" variant="outline-secondary"
                          style={{ fontSize: '0.75rem', padding: '2px 8px' }}
                          onClick={() => setPrompt(q)}>
                          {q}
                        </Button>
                      ))}
                      {prompt && (
                        <Button size="sm" variant="outline-danger"
                          style={{ fontSize: '0.75rem', padding: '2px 8px' }}
                          onClick={() => setPrompt('')}>
                          ✕ 지우기
                        </Button>
                      )}
                    </div>
                  </Form.Group>

                  <div className="text-center mb-4">
                    <Button
                      className="btn-shop-primary px-5 py-3"
                      style={{ fontSize: '1.1rem' }}
                      onClick={generateRecommendation}
                      disabled={loading}>
                      {loading ? <Spinner animation="border" size="sm" className="me-2" /> : '🎱 '}
                      {loading ? 'LLM 분석 중... (약 20~40초)' : '추천 번호 생성'}
                    </Button>
                    <div className="mt-2" style={{ fontSize: '0.8rem', color: 'var(--shop-text-light)' }}>
                      ※ 로컬 LLM이 통계 데이터를 해석하여 번호를 선정합니다 (시간이 다소 걸립니다)
                    </div>
                  </div>

                  {recommendation && (
                    <div className="text-center py-4" style={{
                      background: 'linear-gradient(135deg, #00695C, #00897B)',
                      borderRadius: '16px', padding: '30px', color: '#fff',
                    }}>
                      <div className="mb-2" style={{ fontSize: '0.85rem', opacity: 0.8 }}>
                        {recommendation.algorithm} — {recommendation.totalDraws}회차 분석 결과
                      </div>
                      <h4 className="mb-3" style={{ fontWeight: 300 }}>이번 주 추천 번호</h4>
                      <div className="d-flex align-items-center justify-content-center gap-2 mb-3">
                        {recommendation.numbers?.map((n, i) => (
                          <LottoBall key={i} number={n} size={56} />
                        ))}
                        <span style={{ fontSize: '1.8rem', fontWeight: 300, margin: '0 10px', opacity: 0.6 }}>+</span>
                        <LottoBall number={recommendation.bonus} size={56} bonus />
                      </div>
                      <div style={{ fontSize: '0.85rem', opacity: 0.8 }}>
                        합계: {recommendation.sum} (평균: {recommendation.avgSum})
                        {' | '}홀짝: {recommendation.oddEven}
                      </div>
                    </div>
                  )}

                  {recommendation?.reasons && (
                    <Alert variant="light" className="mt-3" style={{ border: '2px solid var(--shop-border)' }}>
                      <strong>📊 분석 근거:</strong>
                      <ul className="mb-0 mt-2">
                        {recommendation.reasons.map((r, i) => (
                          <li key={i} style={{ fontSize: '0.9rem' }}>{r}</li>
                        ))}
                      </ul>
                    </Alert>
                  )}
                </div>
              )}
            </Col>
          </Row>
        </Container>
      </section>
    </>
  );
}
