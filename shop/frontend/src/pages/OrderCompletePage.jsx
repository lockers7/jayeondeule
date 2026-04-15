import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Container, Row, Col } from 'react-bootstrap';
import { CheckCircleFill } from 'react-bootstrap-icons';
import { bankInfo } from '../data/products';

export default function OrderCompletePage() {
  const [order] = useState(() => {
    const saved = localStorage.getItem('lastOrder');
    return saved ? JSON.parse(saved) : null;
  });

  return (
    <>
      <div style={{ paddingTop: '80px' }} />
      <section className="shop-section">
        <Container>
          <Row className="justify-content-center">
            <Col lg={6} className="text-center">
              <CheckCircleFill size={64} color="var(--shop-accent)" className="mb-4" />
              <h2 className="fw-bold mb-3">주문이 완료되었습니다</h2>
              <p className="text-muted mb-4">
                아래 계좌로 입금해 주시면 확인 후 발송해 드립니다.
              </p>

              <div className="bank-info mb-4 text-start">
                <p className="fw-semibold mb-2">입금 계좌 안내</p>
                <p className="bank-info-number mb-1">
                  {bankInfo.bankName} {bankInfo.accountNumber}
                </p>
                <p className="small text-muted mb-0">예금주: {bankInfo.accountHolder}</p>
              </div>

              {order && (
                <div className="order-summary text-start mb-4">
                  <h6 className="fw-bold mb-3">주문 내역</h6>
                  <div className="d-flex justify-content-between mb-2">
                    <span className="text-muted">주문번호</span>
                    <span className="fw-semibold small">{order.orderId}</span>
                  </div>
                  <div className="d-flex justify-content-between mb-2">
                    <span className="text-muted">상품</span>
                    <span>{order.product.name}</span>
                  </div>
                  <div className="d-flex justify-content-between mb-2">
                    <span className="text-muted">수량</span>
                    <span>{order.quantity}개</span>
                  </div>
                  <div className="d-flex justify-content-between mb-2">
                    <span className="text-muted">주문자</span>
                    <span>{order.buyer.name}</span>
                  </div>
                  <hr />
                  <div className="d-flex justify-content-between">
                    <span className="fw-bold">결제 금액</span>
                    <span className="fw-bold" style={{ color: 'var(--shop-accent)', fontSize: '1.2rem' }}>
                      {order.totalPrice.toLocaleString('ko-KR')}원
                    </span>
                  </div>
                </div>
              )}

              <div className="d-flex gap-3 justify-content-center">
                <Link to="/" className="btn-shop-primary">홈으로</Link>
                <Link to="/products" className="btn-shop-outline" style={{ color: 'var(--shop-text)', borderColor: 'var(--shop-border)' }}>
                  쇼핑 계속하기
                </Link>
              </div>
            </Col>
          </Row>
        </Container>
      </section>
    </>
  );
}
