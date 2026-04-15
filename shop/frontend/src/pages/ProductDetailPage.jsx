import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { Container, Row, Col, Button, Badge } from 'react-bootstrap';
import { CartPlus, Truck, ShieldCheck, Award } from 'react-bootstrap-icons';
import api from '../api/client';

export default function ProductDetailPage() {
  const { productId } = useParams();
  const navigate = useNavigate();
  const [product, setProduct] = useState(null);
  const [loading, setLoading] = useState(true);
  const [quantity, setQuantity] = useState(1);

  useEffect(() => {
    const numId = productId?.replace(/\D/g, '') || productId;
    api.get(`/products/${numId}`)
      .then(({ data }) => { if (data.success) setProduct(data.data); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [productId]);

  if (loading) return null;

  if (!product) {
    return (
      <section className="shop-section text-center">
        <Container>
          <h3>상품을 찾을 수 없습니다</h3>
          <Link to="/products" className="btn-shop-primary mt-3 d-inline-block">
            상품 목록으로
          </Link>
        </Container>
      </section>
    );
  }

  const formatPrice = (price) => price.toLocaleString('ko-KR');
  const totalPrice = formatPrice(product.price * quantity);

  const isSoldOut = product.saleStatus === 'SOLD_OUT' || product.stockQty <= 0;
  const isStopped = product.saleStatus === 'STOPPED';
  const canBuy = !isSoldOut && !isStopped;

  const image = product.imageUrl || null;
  const features = product.features ? (typeof product.features === 'string' ? JSON.parse(product.features) : product.features) : [];

  return (
    <>
      <div style={{ paddingTop: '80px' }} />
      <section className="shop-section" style={{ paddingTop: '40px' }}>
        <Container>
          <Row className="g-5">
            {/* 이미지 */}
            <Col md={6}>
              <div style={{ position: 'relative' }}>
                <div
                  style={{
                    background: image
                      ? `url(${image}) center/cover`
                      : 'linear-gradient(135deg, #D7CCC8, #BCAAA4)',
                    borderRadius: '16px',
                    height: '500px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#fff',
                    fontSize: '1.1rem',
                  }}
                >
                  {!image && '상품 이미지 영역'}
                </div>
                {isSoldOut && (
                  <Badge bg="warning" text="dark" style={{
                    position: 'absolute', top: 16, right: 16, fontSize: '1rem', padding: '8px 16px',
                  }}>품절</Badge>
                )}
                {isStopped && (
                  <Badge bg="secondary" style={{
                    position: 'absolute', top: 16, right: 16, fontSize: '1rem', padding: '8px 16px',
                  }}>판매중지</Badge>
                )}
              </div>
            </Col>

            {/* 상품 정보 */}
            <Col md={6}>
              {product.category && <span className="product-badge mb-3">{product.category}</span>}
              <h2 className="fw-bold mb-2" style={{ color: 'var(--shop-primary-dark)' }}>
                {product.productName}
              </h2>
              <p className="text-muted mb-4">{product.subtitle}</p>

              {/* 판매상태 표시 */}
              {(isSoldOut || isStopped) && (
                <div className="mb-3">
                  <Badge bg={isStopped ? 'secondary' : 'warning'} text={isSoldOut && !isStopped ? 'dark' : undefined}
                    style={{ fontSize: '0.9rem', padding: '8px 16px' }}>
                    {isStopped ? '판매중지' : '품절'}
                  </Badge>
                </div>
              )}

              <div className="mb-4">
                <span className="product-price" style={{ fontSize: '2rem' }}>
                  {formatPrice(product.price)}원
                </span>
                <span className="product-unit"> / {product.unit}</span>
              </div>

              <p className="mb-4" style={{ lineHeight: 1.8 }}>{product.description}</p>

              {/* 특징 뱃지 */}
              {features.length > 0 && (
                <div className="d-flex flex-wrap gap-2 mb-4">
                  {features.map((f, i) => (
                    <span
                      key={i}
                      style={{
                        background: 'var(--shop-bg-warm)',
                        padding: '6px 16px',
                        borderRadius: '20px',
                        fontSize: '0.85rem',
                        color: 'var(--shop-primary)',
                        fontWeight: 500,
                      }}
                    >
                      {f}
                    </span>
                  ))}
                </div>
              )}

              {/* 수량 선택 */}
              <div className="d-flex align-items-center gap-3 mb-4">
                <span className="fw-semibold">수량</span>
                <div className="d-flex align-items-center gap-2">
                  <Button
                    variant="outline-secondary"
                    size="sm"
                    onClick={() => setQuantity(Math.max(1, quantity - 1))}
                  >
                    -
                  </Button>
                  <span className="fw-bold px-3">{quantity}</span>
                  <Button
                    variant="outline-secondary"
                    size="sm"
                    onClick={() => setQuantity(canBuy ? Math.min(product.stockQty, quantity + 1) : quantity + 1)}
                  >
                    +
                  </Button>
                </div>
                <span className="text-muted">
                  합계: <strong style={{ color: 'var(--shop-accent)' }}>{totalPrice}원</strong>
                </span>
              </div>

              {/* 주문 버튼 */}
              <div className="text-center">
                <Button
                  className={canBuy ? 'btn-shop-primary py-3 px-5 fs-5' : 'py-3 px-5 fs-5'}
                  variant={canBuy ? undefined : 'secondary'}
                  style={canBuy ? {} : { borderRadius: '50px' }}
                  disabled={!canBuy}
                  onClick={canBuy ? () => navigate(`/order/${product.productId}?qty=${quantity}`) : undefined}
                >
                  <CartPlus className="me-2" /> 주문하기
                </Button>
              </div>

              {/* 안내 */}
              <div className="mt-4 d-flex flex-column gap-2">
                <div className="d-flex align-items-center gap-2 small text-muted">
                  <Truck /> 주문 확인 후 2~3일 이내 출고
                </div>
                <div className="d-flex align-items-center gap-2 small text-muted">
                  <ShieldCheck /> 무농약 / 국내산 100%
                </div>
                <div className="d-flex align-items-center gap-2 small text-muted">
                  <Award /> AI 스마트팜 환경제어 재배
                </div>
              </div>
            </Col>
          </Row>
        </Container>
      </section>
    </>
  );
}
