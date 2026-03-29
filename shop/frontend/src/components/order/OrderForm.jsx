import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Form, Button, Row, Col, Alert } from 'react-bootstrap';
import { bankInfo } from '../../data/products';
import { useAuth } from '../../context/AuthContext';
import api from '../../api/client';
import AddressSearch from '../common/AddressSearch';
import PhoneInput from '../common/PhoneInput';

export default function OrderForm({ product, quantity }) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    name: user?.usrName || '',
    phone: user?.phone || '',
    zipCode: '',
    address: '',
    addressDetail: '',
    memo: '',
    payMethod: 'bank',
  });

  const handleChange = (e) => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!user) {
      navigate('/login');
      return;
    }

    setLoading(true);
    try {
      const productId = typeof product.id === 'string' ? parseInt(product.id.replace(/\D/g, '')) : product.productId || product.id;
      const { data } = await api.post('/orders', {
        receiverName: form.name,
        receiverPhone: form.phone,
        zipcode: form.zipCode,
        address: form.address,
        addressDetail: form.addressDetail,
        shippingMemo: form.memo,
        items: [{ productId, quantity }]
      });
      if (data.success) {
        localStorage.setItem('lastOrder', JSON.stringify({
          orderId: data.data.orderId,
          product: { name: product.productName || product.name, price: product.price, unit: product.unit },
          quantity,
          totalPrice: product.price * quantity,
          buyer: form,
        }));
        navigate('/order-complete');
      } else {
        setError(data.message);
      }
    } catch (err) {
      setError(err.response?.data?.message || '주문 처리 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  const totalPrice = (product.price * quantity).toLocaleString('ko-KR');

  return (
    <Form onSubmit={handleSubmit}>
      <h5 className="mb-3 fw-bold">주문자 정보</h5>
      <Row className="mb-3">
        <Col md={6}>
          <Form.Group className="mb-3">
            <Form.Label>이름 *</Form.Label>
            <Form.Control name="name" value={form.name} onChange={handleChange} required placeholder="주문자 이름" />
          </Form.Group>
        </Col>
        <Col md={6}>
          <Form.Group className="mb-3">
            <Form.Label>연락처 *</Form.Label>
            <PhoneInput value={form.phone} onChange={(v) => setForm(prev => ({ ...prev, phone: v }))} required />
          </Form.Group>
        </Col>
      </Row>

      <h5 className="mb-3 fw-bold">배송지 정보</h5>
      <AddressSearch
        zipcode={form.zipCode}
        address={form.address}
        addressDetail={form.addressDetail}
        onChange={(v) => setForm(prev => ({
          ...prev,
          ...(v.zipcode !== undefined ? { zipCode: v.zipcode } : {}),
          ...(v.address !== undefined ? { address: v.address } : {}),
          ...(v.addressDetail !== undefined ? { addressDetail: v.addressDetail } : {}),
        }))}
      />
      <Form.Group className="mb-3">
        <Form.Label>배송 메모</Form.Label>
        <Form.Control name="memo" value={form.memo} onChange={handleChange} placeholder="배송 시 요청사항" />
      </Form.Group>

      <h5 className="mb-3 fw-bold">결제 방법</h5>
      <div className="bank-info mb-4">
        <p className="mb-2 fw-semibold">무통장 입금 / 계좌이체</p>
        <p className="bank-info-number mb-1">{bankInfo.bankName} {bankInfo.accountNumber}</p>
        <p className="small text-muted mb-0">예금주: {bankInfo.accountHolder}</p>
      </div>

      <div className="order-summary mb-4">
        <div className="d-flex justify-content-between mb-2">
          <span>상품명</span>
          <span className="fw-semibold">{product.name}</span>
        </div>
        <div className="d-flex justify-content-between mb-2">
          <span>수량</span>
          <span>{quantity}개</span>
        </div>
        <hr />
        <div className="d-flex justify-content-between">
          <span className="fw-bold fs-5">총 결제금액</span>
          <span className="fw-bold fs-5" style={{ color: 'var(--shop-accent)' }}>{totalPrice}원</span>
        </div>
      </div>

      {error && <Alert variant="danger" className="mb-3">{error}</Alert>}
      {!user && <Alert variant="warning" className="mb-3">주문하려면 <a href="/login">로그인</a>이 필요합니다.</Alert>}
      <Button type="submit" className="btn-shop-primary w-100 py-3 fs-5" disabled={loading}>
        {loading ? '주문 처리 중...' : '주문하기'}
      </Button>
    </Form>
  );
}
