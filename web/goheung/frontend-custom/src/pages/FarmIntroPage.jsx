import { useState } from 'react';
import { Container, Row, Col } from 'react-bootstrap';
import { GeoAlt, Thermometer, Moisture, Activity, ChevronLeft, ChevronRight } from 'react-bootstrap-icons';
import CameraStream from '../components/camera/CameraStream';
import IpCamView from '../components/camera/IpCamView';

const farmPhotos = [
  { src: '/images/farm/farm-1.jpg', caption: '고흥뜰에 스마트팜 전경' },
  { src: '/images/farm/farm-2.jpg', caption: '재배사와 주변 농경지' },
  { src: '/images/farm/farm-3.jpg', caption: '스마트팜 단지 전경' },
  { src: '/images/farm/farm-4.jpg', caption: '재배사 근경' },
  { src: '/images/farm/farm-5.jpg', caption: '농장 뒤편 전경' },
  { src: '/images/farm/farm-6.jpg', caption: '재배사 건물 상세' },
];

export default function FarmIntroPage() {
  const [currentPhoto, setCurrentPhoto] = useState(0);

  const prevPhoto = () => setCurrentPhoto((prev) => (prev === 0 ? farmPhotos.length - 1 : prev - 1));
  const nextPhoto = () => setCurrentPhoto((prev) => (prev === farmPhotos.length - 1 ? 0 : prev + 1));

  return (
    <>
      <div className="page-header">
        <Container>
          <h1 className="page-header-title">농장 소개</h1>
          <p className="page-header-desc">고흥뜰에 스마트팜을 소개합니다</p>
        </Container>
      </div>

      {/* 농장 전경 갤러리 */}
      <section className="shop-section">
        <Container>
          <div className="text-center mb-5">
            <span className="section-label">Farm Gallery</span>
            <h2 className="section-title">농장 전경</h2>
            <p className="section-desc">
              전북 정읍시 영원면에 위치한 고흥뜰에 스마트팜의 모습입니다
            </p>
          </div>

          {/* 메인 슬라이더 */}
          <Row className="justify-content-center mb-4">
            <Col lg={10}>
              <div style={{ position: 'relative', borderRadius: '16px', overflow: 'hidden' }}>
                <img
                  src={farmPhotos[currentPhoto].src}
                  alt={farmPhotos[currentPhoto].caption}
                  style={{ width: '100%', height: '480px', objectFit: 'cover', display: 'block' }}
                />
                <div style={{
                  position: 'absolute', bottom: 0, left: 0, right: 0,
                  background: 'linear-gradient(transparent, rgba(0,0,0,0.6))',
                  padding: '40px 24px 16px', color: '#fff', textAlign: 'center',
                }}>
                  {farmPhotos[currentPhoto].caption}
                </div>
                <button onClick={prevPhoto} style={{
                  position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)',
                  background: 'rgba(0,0,0,0.4)', border: 'none', borderRadius: '50%',
                  width: '44px', height: '44px', color: '#fff', cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  <ChevronLeft size={20} />
                </button>
                <button onClick={nextPhoto} style={{
                  position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)',
                  background: 'rgba(0,0,0,0.4)', border: 'none', borderRadius: '50%',
                  width: '44px', height: '44px', color: '#fff', cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  <ChevronRight size={20} />
                </button>
              </div>
            </Col>
          </Row>

          {/* 썸네일 */}
          <Row className="justify-content-center">
            <Col lg={10}>
              <div style={{ display: 'flex', gap: '8px', justifyContent: 'center', flexWrap: 'wrap' }}>
                {farmPhotos.map((photo, i) => (
                  <img
                    key={i}
                    src={photo.src}
                    alt={photo.caption}
                    onClick={() => setCurrentPhoto(i)}
                    style={{
                      width: '120px', height: '80px', objectFit: 'cover',
                      borderRadius: '8px', cursor: 'pointer',
                      border: currentPhoto === i ? '3px solid #00897B' : '3px solid transparent',
                      opacity: currentPhoto === i ? 1 : 0.6,
                      transition: 'all 0.2s',
                    }}
                  />
                ))}
              </div>
            </Col>
          </Row>
        </Container>
      </section>

      {/* 실시간 카메라 */}
      <section className="shop-section shop-section-warm">
        <Container>
          <div className="text-center mb-5">
            <span className="section-label">Live Camera</span>
            <h2 className="section-title">실시간 농장 모습</h2>
            <p className="section-desc">
              지금 이 순간, 고흥뜰에 농장의 모습을 실시간으로 확인하세요
            </p>
          </div>
          <Row className="justify-content-center">
            <Col lg={10}>
              {/* [2026-05-01] 메인 IP 카메라 (ZY-CAMHIPTZ-A-2M) — PTZ + 오디오 제어
                  nginx /camera/main/ → jayeondeule.iptime.org:5040(HTTP) + :5540(RTSP) */}
              <IpCamView base="/camera/main" label="농장 전경 LIVE (PTZ)" />
            </Col>
          </Row>
        </Container>
      </section>

      {/* 농장 소개 */}
      <section className="shop-section">
        <Container>
          <Row className="align-items-center">
            <Col md={6} className="mb-4 mb-md-0">
              <span className="section-label">About Us</span>
              <h2 className="section-title">자연과 기술의 조화</h2>
              <p className="mb-4" style={{ color: 'var(--shop-text-light)' }}>
                고흥뜰에는 전통 농업의 정성과 첨단 AI 기술을 결합하여
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
              <img
                src="/images/farm/farm-2.jpg"
                alt="고흥뜰에 농장"
                style={{
                  width: '100%', height: '400px', objectFit: 'cover',
                  borderRadius: '16px',
                }}
              />
            </Col>
          </Row>
        </Container>
      </section>

      {/* 핵심 수치 */}
      <section className="shop-section shop-section-warm">
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
