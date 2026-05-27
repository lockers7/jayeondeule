import { Link } from 'react-router-dom';
import { Container, Row, Col } from 'react-bootstrap';
import { Cpu, Droplet, Award, ArrowRight } from 'react-bootstrap-icons';
import ProductCard from '../components/product/ProductCard';
import { products } from '../data/products';

export default function HomePage() {
  const featured = products.filter((p) => p.inStock).slice(0, 3);

  return (
    <>
      {/* Hero */}
      <section className="hero-section">
        <div className="hero-content">
          <div className="hero-badge">AI Smart Farm</div>
          <h1 className="hero-title">
            AI 스마트팜이 키운<br />
            프리미엄 상황버섯
          </h1>
          <p className="hero-subtitle">
            24시간 AI가 온도, 습도, CO2를 자동 관리하는 최적의 환경에서<br />
            정성껏 재배한 국내산 상황버섯을 만나보세요
          </p>
          <div className="hero-cta">
            <Link to="/products" className="btn-shop-primary">
              상품 보러가기 <ArrowRight />
            </Link>
            <Link to="/farm" className="btn-shop-outline">
              농장 둘러보기
            </Link>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="shop-section">
        <Container>
          <div className="text-center">
            <span className="section-label">Why Choose Us</span>
            <h2 className="section-title">고흥뜰에만의 특별함</h2>
            <p className="section-desc">
              첨단 AI 기술과 자연의 조화로 최상의 상황버섯을 재배합니다
            </p>
          </div>
          <Row className="g-4">
            <Col md={4}>
              <div className="feature-card">
                <div className="feature-icon feature-icon-green">
                  <Cpu />
                </div>
                <h5 className="fw-bold mb-3">AI 환경제어 시스템</h5>
                <p className="text-muted small">
                  온도, 습도, CO2 농도를 AI가 24시간 실시간으로 모니터링하고
                  자동 제어하여 최적의 생육 환경을 유지합니다.
                </p>
              </div>
            </Col>
            <Col md={4}>
              <div className="feature-card">
                <div className="feature-icon feature-icon-brown">
                  <Droplet />
                </div>
                <h5 className="fw-bold mb-3">무농약 원목재배</h5>
                <p className="text-muted small">
                  화학 약품 없이 천연 원목 배지에서 자연 그대로의 방식으로
                  재배하여 안심하고 드실 수 있습니다.
                </p>
              </div>
            </Col>
            <Col md={4}>
              <div className="feature-card">
                <div className="feature-icon feature-icon-gold">
                  <Award />
                </div>
                <h5 className="fw-bold mb-3">엄선된 품질</h5>
                <p className="text-muted small">
                  데이터 기반의 과학적 재배 관리로 균일하고 우수한 품질의
                  상황버섯만을 엄선하여 제공합니다.
                </p>
              </div>
            </Col>
          </Row>
        </Container>
      </section>

      {/* Featured Products */}
      <section className="shop-section shop-section-warm">
        <Container>
          <div className="text-center">
            <span className="section-label">Products</span>
            <h2 className="section-title">추천 상품</h2>
            <p className="section-desc">
              AI 스마트팜에서 재배한 프리미엄 상황버섯을 만나보세요
            </p>
          </div>
          <Row className="g-4">
            {featured.map((product) => (
              <Col md={4} key={product.id}>
                <ProductCard product={product} />
              </Col>
            ))}
          </Row>
          <div className="text-center mt-5">
            <Link to="/products" className="btn-shop-primary">
              전체 상품 보기 <ArrowRight />
            </Link>
          </div>
        </Container>
      </section>

      {/* Farm Highlight */}
      <section className="shop-section shop-section-dark">
        <Container>
          <Row className="align-items-center">
            <Col md={6} className="mb-4 mb-md-0">
              <span className="section-label" style={{ color: 'var(--shop-gold)' }}>Smart Farm</span>
              <h2 className="section-title section-title-light">
                실시간으로 확인하는<br />우리 농장
              </h2>
              <p style={{ color: 'rgba(255,255,255,0.7)', marginBottom: '30px' }}>
                고흥뜰에 농장은 실시간 카메라와 센서 데이터를 통해
                재배 과정을 투명하게 공개합니다.
                AI가 관리하는 3개의 재배사에서 상황버섯이 자라는 모습을
                직접 확인해 보세요.
              </p>
              <div className="d-flex gap-3 flex-wrap">
                <Link to="/farm" className="btn-shop-primary">농장 보기</Link>
                <Link to="/house" className="btn-shop-outline">재배사 보기</Link>
              </div>
            </Col>
            <Col md={6}>
              <Row className="g-3">
                <Col xs={6}>
                  <div className="intro-stat" style={{ background: 'rgba(255,255,255,0.05)', borderRadius: '16px' }}>
                    <div className="intro-stat-number">3</div>
                    <div className="intro-stat-label" style={{ color: 'rgba(255,255,255,0.6)' }}>재배사 운영</div>
                  </div>
                </Col>
                <Col xs={6}>
                  <div className="intro-stat" style={{ background: 'rgba(255,255,255,0.05)', borderRadius: '16px' }}>
                    <div className="intro-stat-number">24h</div>
                    <div className="intro-stat-label" style={{ color: 'rgba(255,255,255,0.6)' }}>AI 환경관리</div>
                  </div>
                </Col>
                <Col xs={6}>
                  <div className="intro-stat" style={{ background: 'rgba(255,255,255,0.05)', borderRadius: '16px' }}>
                    <div className="intro-stat-number">6</div>
                    <div className="intro-stat-label" style={{ color: 'rgba(255,255,255,0.6)' }}>센서 항목</div>
                  </div>
                </Col>
                <Col xs={6}>
                  <div className="intro-stat" style={{ background: 'rgba(255,255,255,0.05)', borderRadius: '16px' }}>
                    <div className="intro-stat-number">100%</div>
                    <div className="intro-stat-label" style={{ color: 'rgba(255,255,255,0.6)' }}>국내산</div>
                  </div>
                </Col>
              </Row>
            </Col>
          </Row>
        </Container>
      </section>
    </>
  );
}
