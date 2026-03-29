import { Link } from 'react-router-dom';
import { Card } from 'react-bootstrap';

export default function ProductCard({ product }) {
  const formatPrice = (price) => price.toLocaleString('ko-KR');

  return (
    <Card className="product-card">
      <div
        className="product-card-img"
        style={{
          background: product.images?.[0]
            ? `url(${product.images[0]}) center/cover`
            : 'linear-gradient(135deg, #D7CCC8, #BCAAA4)',
        }}
      />
      <div className="product-card-body">
        <span className="product-badge">{product.category}</span>
        <h5 className="product-name">{product.name}</h5>
        <p className="product-desc">{product.subtitle}</p>
        <div className="d-flex justify-content-between align-items-end">
          <div>
            <span className="product-price">{formatPrice(product.price)}원</span>
            <span className="product-unit"> / {product.unit}</span>
          </div>
          <Link
            to={`/products/${product.id}`}
            className="btn btn-sm btn-shop-primary"
            style={{ padding: '8px 20px', fontSize: '0.85rem' }}
          >
            {product.inStock ? '상세보기' : '준비중'}
          </Link>
        </div>
      </div>
    </Card>
  );
}
