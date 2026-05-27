import { Link } from 'react-router-dom';
import { Card, Badge } from 'react-bootstrap';

export default function ProductCard({ product }) {
  const formatPrice = (price) => price.toLocaleString('ko-KR');

  const id = product.productId || product.id;
  const name = product.productName || product.name;
  const subtitle = product.subtitle || '';
  const category = product.category || '';
  const image = product.imageUrl || product.images?.[0] || null;
  const isSoldOut = product.saleStatus === 'SOLD_OUT' || (product.stockQty != null && product.stockQty <= 0);
  const isStopped = product.saleStatus === 'STOPPED';

  return (
    <Card className="product-card">
      <div style={{ position: 'relative' }}>
        <div
          className="product-card-img"
          style={{
            background: image
              ? `url(${image}) center/cover`
              : 'linear-gradient(135deg, #D7CCC8, #BCAAA4)',
          }}
        />
        {isSoldOut && (
          <Badge bg="warning" text="dark" style={{
            position: 'absolute', top: 12, right: 12, fontSize: '0.8rem', padding: '6px 12px',
          }}>품절</Badge>
        )}
        {isStopped && (
          <Badge bg="secondary" style={{
            position: 'absolute', top: 12, right: 12, fontSize: '0.8rem', padding: '6px 12px',
          }}>판매중지</Badge>
        )}
      </div>
      <div className="product-card-body">
        {category && <span className="product-badge">{category}</span>}
        <h5 className="product-name">{name}</h5>
        <p className="product-desc">{subtitle}</p>
        <div className="d-flex justify-content-between align-items-end">
          <div>
            <span className="product-price">{formatPrice(product.price)}원</span>
            <span className="product-unit"> / {product.unit}</span>
          </div>
          <Link
            to={`/products/${id}`}
            className="btn btn-sm btn-shop-primary"
            style={{ padding: '8px 20px', fontSize: '0.85rem' }}
          >
            상세보기
          </Link>
        </div>
      </div>
    </Card>
  );
}
