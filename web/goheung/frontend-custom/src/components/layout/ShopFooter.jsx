import { Container, Row, Col } from 'react-bootstrap';
import { Link } from 'react-router-dom';
import { companyInfo } from '../../data/products';

export default function ShopFooter() {
  return (
    <footer className="shop-footer">
      <Container>
        <Row>
          <Col md={4} className="mb-4 mb-md-0">
            <h5>고흥뜰에</h5>
            <p className="small">
              AI 스마트팜 기술로 최적의 환경에서<br />
              프리미엄 상황버섯을 재배합니다.
            </p>
          </Col>
          <Col md={4} className="mb-4 mb-md-0">
            <h5>바로가기</h5>
            <div className="d-flex flex-column gap-2">
              <Link to="/farm">농장 소개</Link>
              <Link to="/story">농장 이야기</Link>
              <Link to="/house">재배사 소개</Link>
              <Link to="/efficacy">효능효과</Link>
              <Link to="/products">상품 보기</Link>
              <Link to="/inquiry">문의 게시판</Link>
            </div>
          </Col>
          <Col md={4}>
            <h5>연락처</h5>
            <p className="small mb-1">전화: {companyInfo.phone}</p>
            <p className="small mb-1">이메일: {companyInfo.email}</p>
            <p className="small">{companyInfo.address}</p>
          </Col>
        </Row>
        <div className="footer-divider" />
        <Row>
          <Col>
            <p className="small text-center mb-0" style={{ opacity: 0.5 }}>
              상호: {companyInfo.name} | 대표: {companyInfo.ceo} | 사업자등록번호: {companyInfo.bizNumber}
              <br />
              &copy; {new Date().getFullYear()} {companyInfo.name}. All rights reserved.
            </p>
          </Col>
        </Row>
      </Container>
    </footer>
  );
}
