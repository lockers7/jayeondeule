import { useParams, useSearchParams } from 'react-router-dom';
import { Container, Row, Col } from 'react-bootstrap';
import OrderForm from '../components/order/OrderForm';
import { products } from '../data/products';

export default function OrderPage() {
  const { productId } = useParams();
  const [searchParams] = useSearchParams();
  const quantity = parseInt(searchParams.get('qty') || '1', 10);
  const product = products.find((p) => p.id === productId);

  if (!product) {
    return (
      <section className="shop-section text-center" style={{ paddingTop: '120px' }}>
        <Container>
          <h3>상품을 찾을 수 없습니다</h3>
        </Container>
      </section>
    );
  }

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
              <OrderForm product={product} quantity={quantity} />
            </Col>
          </Row>
        </Container>
      </section>
    </>
  );
}
