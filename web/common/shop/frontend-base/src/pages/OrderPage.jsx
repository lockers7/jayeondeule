import { useState, useEffect } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { Container, Row, Col, Alert, Badge } from 'react-bootstrap';
import OrderForm from '../components/order/OrderForm';
import api from '../api/client';

export default function OrderPage() {
  const { productId } = useParams();
  const [searchParams] = useSearchParams();
  const quantity = parseInt(searchParams.get('qty') || '1', 10);
  const [product, setProduct] = useState(null);
  const [loading, setLoading] = useState(true);

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
      <section className="shop-section text-center" style={{ paddingTop: '120px' }}>
        <Container>
          <h3>상품을 찾을 수 없습니다</h3>
        </Container>
      </section>
    );
  }

  const isSoldOut = product.saleStatus === 'SOLD_OUT' || product.stockQty <= 0;
  const isStopped = product.saleStatus === 'STOPPED';
  const canOrder = !isSoldOut && !isStopped;

  return (
    <>
      <div className="page-header">
        <Container>
          <h1 className="page-header-title">주문서 작성</h1>
          <p className="page-header-desc">주문 정보를 입력해 주세요</p>
        </Container>
      </div>

      <section className="shop-section">
        <Container>
          <Row className="justify-content-center">
            <Col lg={8}>
              {!canOrder && (
                <Alert variant={isStopped ? 'secondary' : 'warning'} className="text-center mb-4">
                  <Badge bg={isStopped ? 'secondary' : 'warning'} text={isSoldOut && !isStopped ? 'dark' : undefined}
                    className="me-2">{isStopped ? '판매중지' : '품절'}</Badge>
                  현재 주문이 불가능한 상품입니다.
                </Alert>
              )}
              <OrderForm product={product} quantity={quantity} canOrder={canOrder} />
            </Col>
          </Row>
        </Container>
      </section>
    </>
  );
}
