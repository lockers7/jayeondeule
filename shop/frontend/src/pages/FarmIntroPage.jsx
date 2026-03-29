import { Container, Row, Col } from 'react-bootstrap';
import { GeoAlt, Thermometer, Moisture, Activity } from 'react-bootstrap-icons';
import CameraStream from '../components/camera/CameraStream';

export default function FarmIntroPage() {
  return (
    <>
      <div className="page-header">
        <Container>
          <h1 className="page-header-title">농장 소개</h1>
          <p className="page-header-desc">자연들에 스마트팜을 소개합니다</p>
        </Container>
      </div>

      {/* 실시간 농장 전경 */}
      <section className="shop-section">
        <Container>
          <div className="text-center mb-5">
            <span className="section-label">Live Camera</span>
            <h2 className="section-title">실시간 농장 전경</h2>
            <p className="section-desc">
              지금 이 순간, 자연들에 농장의 모습을 실시간으로 확인하세요
            </p>
          </div>
          <Row className="justify-content-center">
            <Col lg={10}>
              <CameraStream farmId={0} houseId={1} label="농장 전경 LIVE" />
            </Col>
          </Row>
        </Container>
      </section>

      {/* 농장 소개 */}
      <section className="shop-section shop-section-warm">
        <Container>
          <Row className="align-items-center">
            <Col md={6} className="mb-4 mb-md-0">
              <span className="section-label">About Us</span>
              <h2 className="section-title">자연과 기술의 조화</h2>
              <p className="mb-4" style={{ color: 'var(--shop-text-light)' }}>
                자연들에는 전통 농업의 정성과 첨단 AI 기술을 결합하여
                최상의 상황버섯을 재배하고 있습니다.
              </p>
              <p className="mb-4" style={{ color: 'var(--shop-text-light)' }}>
                3개의 재배사에서 온도, 습도, CO2 농도, 수온 등
                6가지 환경 요소를 AI가 24시간 자동 관리하며,
                상황버섯이 가장 잘 자랄 수 있는 최적의 환경을 유지합니다.
              </p>
              <p style={{ color: 'var(--shop-text-light)' }}>
                무농약 원목재배 방식을 고수하며,
                데이터에 기반한 과학적 재배 관리로
                균일하고 우수한 품질의 상황버섯을 생산합니다.
              </p>
            </Col>
            <Col md={6}>
              <div
                style={{
                  background: 'linear-gradient(135deg, #D7CCC8, #BCAAA4)',
                  borderRadius: '16px',
                  height: '400px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#fff',
                  fontSize: '1.2rem',
                }}
              >
                농장 이미지 영역
              </div>
            </Col>
          </Row>
        </Container>
      </section>

      {/* 핵심 수치 */}
      <section className="shop-section">
        <Container>
          <Row className="g-4">
            {[
              { icon: <GeoAlt size={28} />, number: '3개', label: '재배사 운영', desc: '독립적으로 환경이 관리되는 3개의 재배사' },
              { icon: <Thermometer size={28} />, number: '6종', label: '환경 센서', desc: '온도, 습도, CO2, 수온, 조도, 수위' },
              { icon: <Activity size={28} />, number: '24시간', label: 'AI 자동제어', desc: '쉬지 않는 AI 환경 모니터링 및 제어' },
              { icon: <Moisture size={28} />, number: '100%', label: '무농약', desc: '화학 약품 없는 안전한 원목재배' },
            ].map((item, i) => (
              <Col md={3} sm={6} key={i}>
                <div className="feature-card">
                  <div className="feature-icon feature-icon-green">{item.icon}</div>
                  <div className="intro-stat-number" style={{ fontSize: '2rem', marginBottom: '4px' }}>{item.number}</div>
                  <h6 className="fw-bold mb-2">{item.label}</h6>
                  <p className="text-muted small mb-0">{item.desc}</p>
                </div>
              </Col>
            ))}
          </Row>
        </Container>
      </section>
    </>
  );
}
