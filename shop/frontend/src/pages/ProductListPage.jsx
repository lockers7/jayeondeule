import { useState, useEffect } from 'react';
import { Container, Row, Col } from 'react-bootstrap';
import ProductCard from '../components/product/ProductCard';
import api from '../api/client';

export default function ProductListPage() {
  const [products, setProducts] = useState([]);

  useEffect(() => {
    api.get('/products', { params: { farmId: 1 } })
      .then(({ data }) => {
        if (data.success) setProducts(data.data || []);
      })
      .catch(() => {});
  }, []);

  return (
    <>
      <div className="page-header">
        <Container>
          <h1 className="page-header-title">상품</h1>
          <p className="page-header-desc">AI 스마트팜에서 재배한 프리미엄 상황버섯</p>
        </Container>
      </div>

      <section className="shop-section">
        <Container>
          <Row className="g-4">
            {products.map((product) => (
              <Col lg={3} md={6} key={product.productId}>
                <ProductCard product={product} />
              </Col>
            ))}
          </Row>
        </Container>
      </section>
    </>
  );
}
