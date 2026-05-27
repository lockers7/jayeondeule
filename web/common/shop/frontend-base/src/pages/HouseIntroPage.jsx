import { useState } from 'react';
import { Container, Row, Col, Nav } from 'react-bootstrap';
import { Thermometer, Moisture, Wind, Lightbulb } from 'react-bootstrap-icons';
import CameraStream from '../components/camera/CameraStream';

const houses = [
  {
    id: 1, name: '1호 재배사', farmId: 1, houseId: 1,
    desc: '상황버섯 주력 재배동으로, 16채널 릴레이를 통해 흡입/배출 팬, 밸브, 가습기, 히터 등을 AI가 자동 제어합니다.',
    features: ['16채널 릴레이 자동제어', '실내외 온습도 센서', 'CO2 농도 모니터링', '수온 관리 시스템'],
  },
  {
    id: 2, name: '2호 재배사', farmId: 1, houseId: 2,
    desc: '독립적인 환경제어 시스템을 갖춘 재배동입니다. 라디에이터를 활용한 공기온도 관리가 특징입니다.',
    features: ['15채널 릴레이 제어', '라디에이터 온도관리', 'SHT4x 고정밀 센서', '독립 배수 시스템'],
  },
  {
    id: 3, name: '3호 재배사', farmId: 1, houseId: 3,
    desc: '최신 센서와 제어 장비를 갖춘 재배동으로, 1호 재배사와 동일한 사양의 환경제어 시스템을 운영합니다.',
    features: ['16채널 릴레이 자동제어', '실내외 온습도 센서', 'CO2 농도 모니터링', '실내히터 시스템'],
  },
];

const systemFeatures = [
  { icon: <Thermometer size={24} />, title: '온도 자동제어',
    desc: '실내외 온도를 실시간 측정하고, 히터/환풍기/밸브를 자동 조절하여 최적 온도를 유지합니다.' },
  { icon: <Moisture size={24} />, title: '습도 자동관리',
    desc: '가습기와 환기 시스템을 통해 상황버섯 생육에 적합한 습도 환경을 24시간 유지합니다.' },
  { icon: <Wind size={24} />, title: 'CO2 농도 관리',
    desc: 'MH-Z19B CO2 센서로 실시간 측정하고, 환기 시스템을 자동 제어하여 적정 CO2 농도를 유지합니다.' },
  { icon: <Lightbulb size={24} />, title: '조명/관수 자동화',
    desc: '생육 단계에 맞춰 조명 시간과 관수 스케줄을 AI가 자동으로 관리합니다.' },
];

// 재배사 내부 이미지 갤러리 데이터
const houseInteriorGallery = [
  {
    title: '재배사 전경',
    desc: '다단 선반에 원목 배지를 배치한 재배사 내부 전경',
    images: [
      { src: '/images/smartfarm/house/house-01.jpg', caption: '재배사 내부 전경 — 다단 선반에 원목 배지 배치' },
      { src: '/images/smartfarm/house/house-03.jpg', caption: '야간 조명 아래 재배사 — 생육 환경 유지 중' },
    ]
  },
  {
    title: '상황버섯 생육',
    desc: '원목 배지에서 자라는 상황버섯 근접 촬영',
    images: [
      { src: '/images/smartfarm/house/house-06.jpg', caption: '원목에서 자라는 상황버섯 — 두꺼운 갓 형성' },
      { src: '/images/smartfarm/house/house-07.jpg', caption: '상황버섯 근접 — 선명한 황금빛 갓' },
      { src: '/images/smartfarm/house/house-08.jpg', caption: '조명 아래 상황버섯 — 다단 선반 재배' },
      { src: '/images/smartfarm/house/house-09.jpg', caption: '풍성하게 자란 상황버섯 원목 배지' },
    ]
  },
  {
    title: '재배 환경',
    desc: '원목 배지 배치 및 환기 시스템 구성',
    images: [
      { src: '/images/smartfarm/house/house-05.jpg', caption: '원목 배지 클로즈업 — 균사 접종 후 생육' },
      { src: '/images/smartfarm/house/house-02.jpg', caption: '재배사 내부 통로 — 다단 선반 구조', portrait: true },
      { src: '/images/smartfarm/house/house-04.jpg', caption: '환기 덕트와 원목 배치 구조', portrait: true },
    ]
  },
];

// 스마트팜 이미지 갤러리 데이터
const smartfarmGallery = {
  controller: {
    title: 'IoT 컨트롤러',
    desc: '라즈베리파이 기반 환경 제어 시스템',
    images: [
      { src: '/images/smartfarm/sf-01.jpg', caption: '라즈베리파이 + 16채널 릴레이 제어 보드' },
      { src: '/images/smartfarm/sf-02.jpg', caption: 'SSR 릴레이 패널 — 고전압 장치 안전 제어' },
      { src: '/images/smartfarm/sf-03.jpg', caption: '센서 연결 제어 보드 — 온습도/CO2/수온 통합' },
      { src: '/images/smartfarm/sf-04.jpg', caption: '완성된 IoT 컨트롤러 — 재배사 현장 설치형' },
    ]
  },
  indoor: {
    title: '실내 환경 장치',
    desc: '재배사 내부 온습도/환기/조명 제어 시스템',
    images: [
      { src: '/images/smartfarm/sf-05.jpg', caption: '흡배기 밸브 시스템 — 외부 공기 유입/배출 제어' },
      { src: '/images/smartfarm/sf-06.jpg', caption: '열풍기 + 환기 덕트 — 실내 온도 상승 및 공기 순환' },
      { src: '/images/smartfarm/sf-07.jpg', caption: '흡기/배기 덕트 배관 — 재배사 내부 공기 흐름 설계' },
      { src: '/images/smartfarm/sf-08.jpg', caption: '재배사 내부 — 원목 배지, 조명, 분사 시스템 가동 중' },
    ]
  },
  management: {
    title: 'AI 관리 화면',
    desc: 'AI 대화형 제어 및 실시간 모니터링',
    images: [
      { src: '/images/smartfarm/sf-09.jpg', caption: 'AI 채팅으로 재배사 장치를 음성/텍스트로 제어' },
      { src: '/images/smartfarm/sf-10.jpg', caption: '실시간 센서 모니터링 + 릴레이 원격 조작 화면' },
      { src: '/images/smartfarm/sf-11.jpg', caption: '센서 데이터 그래프 — 온습도/CO2 추이 분석' },
      { src: '/images/smartfarm/sf-12.jpg', caption: '시스템 현황 + 재배사 실시간 카메라 스트리밍' },
    ]
  },
};

const imgStyle = {
  width: '100%', height: '280px', objectFit: 'cover',
  borderRadius: '12px', marginBottom: '8px',
};

export default function HouseIntroPage() {
  const [activeHouse, setActiveHouse] = useState(0);
  const house = houses[activeHouse];

  return (
    <>
      <div className="page-header">
        <Container>
          <h1 className="page-header-title">재배사 소개</h1>
          <p className="page-header-desc">AI가 24시간 관리하는 스마트 재배사</p>
        </Container>
      </div>

      {/* AI 시스템 강조 */}
      <section className="shop-section">
        <Container>
          <div className="text-center mb-5">
            <span className="section-label">AI Smart System</span>
            <h2 className="section-title">시스템이 만드는 최적의 환경</h2>
            <p className="section-desc">
              모든 재배사는 AI 환경제어 시스템으로 운영됩니다.
              센서가 측정하고, AI가 판단하며, 장비가 실행합니다.
            </p>
          </div>
          <Row className="g-4">
            {systemFeatures.map((feat, i) => (
              <Col md={3} sm={6} key={i}>
                <div className="feature-card">
                  <div className="feature-icon feature-icon-green">{feat.icon}</div>
                  <h6 className="fw-bold mb-2">{feat.title}</h6>
                  <p className="text-muted small mb-0">{feat.desc}</p>
                </div>
              </Col>
            ))}
          </Row>
        </Container>
      </section>

      {/* 재배사별 실시간 스트리밍 */}
      <section className="shop-section">
        <Container>
          <div className="text-center mb-4">
            <span className="section-label">Live Streaming</span>
            <h2 className="section-title">재배사 실시간 영상</h2>
            <p className="section-desc">
              각 재배사의 상황버섯 생육 모습을 실시간으로 확인하세요
            </p>
          </div>

          <Nav variant="pills" className="justify-content-center mb-4 gap-2">
            {houses.map((h, i) => (
              <Nav.Item key={h.id}>
                <Nav.Link
                  active={activeHouse === i}
                  onClick={() => setActiveHouse(i)}
                  style={{
                    background: activeHouse === i ? 'var(--shop-accent)' : 'transparent',
                    color: activeHouse === i ? '#fff' : 'var(--shop-text)',
                    border: activeHouse === i ? 'none' : '1px solid var(--shop-border)',
                    borderRadius: '50px', padding: '10px 28px', fontWeight: 500, cursor: 'pointer',
                  }}
                >
                  {h.name}
                </Nav.Link>
              </Nav.Item>
            ))}
          </Nav>

          <Row className="align-items-start g-4">
            <Col lg={7}>
              <CameraStream
                key={`${house.farmId}-${house.houseId}`}
                farmId={house.farmId} houseId={house.houseId}
                label={`${house.name} LIVE`}
              />
            </Col>
            <Col lg={5}>
              <div className="p-4" style={{ background: '#fff', borderRadius: '16px', border: '1px solid var(--shop-border)' }}>
                <h4 className="fw-bold mb-3">{house.name}</h4>
                <p className="text-muted mb-4">{house.desc}</p>
                <h6 className="fw-bold mb-3">주요 장비 및 기능</h6>
                <ul className="list-unstyled">
                  {house.features.map((f, i) => (
                    <li key={i} className="d-flex align-items-center gap-2 mb-2">
                      <span style={{
                        width: '8px', height: '8px', borderRadius: '50%',
                        background: 'var(--shop-accent)', flexShrink: 0
                      }} />
                      <span className="small">{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </Col>
          </Row>
        </Container>
      </section>

      {/* 스마트팜 시스템 갤러리 */}
      <section className="shop-section shop-section-warm">
        <Container>
          <div className="text-center mb-5">
            <span className="section-label">Smart Farm System</span>
            <h2 className="section-title">스마트팜 시스템 구성</h2>
            <p className="section-desc">
              IoT 컨트롤러부터 재배사 내부 장치, AI 관리 화면까지 — 자연들에 스마트팜의 핵심 시스템
            </p>
          </div>

          {Object.entries(smartfarmGallery).map(([key, section]) => (
            <div key={key} className="mb-5">
              <h4 className="fw-bold mb-1">{section.title}</h4>
              <p className="text-muted mb-3">{section.desc}</p>
              <Row className="g-3">
                {section.images.map((img, i) => (
                  <Col md={3} sm={6} key={i}>
                    <img src={img.src} alt={img.caption} style={imgStyle} />
                    <p className="text-muted small text-center mb-0">{img.caption}</p>
                  </Col>
                ))}
              </Row>
            </div>
          ))}
        </Container>
      </section>

      {/* 재배사 내부 모습 */}
      <section className="shop-section">
        <Container>
          <div className="text-center mb-5">
            <span className="section-label">Inside the House</span>
            <h2 className="section-title">재배사 내부 모습</h2>
            <p className="section-desc">
              원목 배지에서 정성껏 키워낸 상황버섯 — 재배사 내부의 실제 모습입니다
            </p>
          </div>

          {houseInteriorGallery.map((section, idx) => (
            <div key={idx} className="mb-5">
              <h4 className="fw-bold mb-1">{section.title}</h4>
              <p className="text-muted mb-3">{section.desc}</p>
              <Row className="g-3">
                {section.images.map((img, i) => (
                  <Col md={img.portrait ? 3 : (section.images.length <= 2 ? 6 : 3)} sm={6} key={i}>
                    <img src={img.src} alt={img.caption} style={{
                      ...imgStyle,
                      height: img.portrait ? '360px' : '280px',
                    }} />
                    <p className="text-muted small text-center mb-0">{img.caption}</p>
                  </Col>
                ))}
              </Row>
            </div>
          ))}
        </Container>
      </section>
    </>
  );
}
