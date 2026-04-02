import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Form, Button, Row, Col, Alert, Dropdown } from 'react-bootstrap';
import { ClockHistory } from 'react-bootstrap-icons';
import { bankInfo } from '../../data/products';
import { useAuth } from '../../context/AuthContext';
import api from '../../api/client';
import AddressSearch from '../common/AddressSearch';
import PhoneInput from '../common/PhoneInput';

export default function OrderForm({ product, quantity, canOrder = true }) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [addressHistory, setAddressHistory] = useState([]);
  const [form, setForm] = useState({
    name: user?.usrName || '',
    phone: user?.phone || '',
    zipCode: '',
    address: '',
    addressDetail: '',
    memo: '',
    payMethod: 'bank',
  });

  // 배송지 정보 로딩: 최종 배송지 → 없으면 회원 기본 주소
  useEffect(() => {
    if (!user) return;
    api.get('/orders/shipping-info')
      .then(({ data }) => {
        if (!data.success) return;
        const { defaultAddress, history } = data.data;
        setAddressHistory(history || []);

        // 최종 배송지 (이력이 있으면 첫 번째) → 없으면 회원 기본 주소
        const addr = (history && history.length > 0) ? history[0] : defaultAddress;
        if (addr) {
          setForm(prev => ({
            ...prev,
            name: addr.receiverName || prev.name,
            phone: addr.receiverPhone || prev.phone,
            zipCode: addr.zipcode || '',
            address: addr.address || '',
            addressDetail: addr.addressDetail || '',
            memo: addr.memo || '',
          }));
        }
      })
      .catch(() => {});
  }, [user]);

  const handleChange = (e) => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  const applyAddress = (addr) => {
    setForm(prev => ({
      ...prev,
      name: addr.receiverName || prev.name,
      phone: addr.receiverPhone || prev.phone,
      zipCode: addr.zipcode || '',
      address: addr.address || '',
      addressDetail: addr.addressDetail || '',
      memo: addr.memo || '',
    }));
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

      <div className="d-flex align-items-center gap-2 mb-3">
        <h5 className="mb-0 fw-bold">배송지 정보</h5>
        {addressHistory.length > 0 && (
          <Dropdown>
            <Dropdown.Toggle variant="outline-secondary" size="sm"
              style={{ borderRadius: '50px', padding: '4px 14px', fontSize: '0.82rem' }}>
              <ClockHistory size={12} className="me-1" /> 최근 배송지
            </Dropdown.Toggle>
            <Dropdown.Menu style={{ minWidth: '340px', padding: '8px' }}>
              {addressHistory.map((addr, i) => (
                <Dropdown.Item key={i} onClick={() => applyAddress(addr)}
                  style={{ whiteSpace: 'normal', padding: '8px 12px', borderBottom: i < addressHistory.length - 1 ? '1px solid #eee' : 'none' }}>
                  <div style={{ fontSize: '0.88rem', fontWeight: 500 }}>{addr.receiverName} / {addr.receiverPhone}</div>
                  <div style={{ fontSize: '0.82rem', color: 'var(--shop-text-light)' }}>
                    [{addr.zipcode}] {addr.address} {addr.addressDetail}
                  </div>
                </Dropdown.Item>
              ))}
            </Dropdown.Menu>
          </Dropdown>
        )}
      </div>
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
      <div className="text-center">
        <Button type="submit" className={canOrder ? 'btn-shop-primary py-3 px-5 fs-5' : 'py-3 px-5 fs-5'}
          variant={canOrder ? undefined : 'secondary'}
          style={canOrder ? {} : { borderRadius: '50px' }}
          disabled={loading || !canOrder}>
          {loading ? '주문 처리 중...' : !canOrder ? '주문 불가' : '주문하기'}
        </Button>
      </div>
    </Form>
  );
}
