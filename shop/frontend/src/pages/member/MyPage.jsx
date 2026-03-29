import { useState, useEffect } from 'react';
import { Container, Row, Col, Table, Badge, Button } from 'react-bootstrap';
import { useAuth } from '../../context/AuthContext';
import api from '../../api/client';

const statusMap = {
  ORDERED: { label: '주문접수', color: 'secondary' },
  PAID: { label: '입금확인', color: 'info' },
  PREPARING: { label: '상품준비', color: 'primary' },
  SHIPPED: { label: '발송완료', color: 'success' },
  DELIVERED: { label: '배송완료', color: 'dark' },
  CANCELLED: { label: '취소', color: 'danger' },
};

export default function MyPage() {
  const { user, logout } = useAuth();
  const [orders, setOrders] = useState([]);
  const [tab, setTab] = useState('orders');

  useEffect(() => { loadOrders(); }, []);

  const loadOrders = async () => {
    try {
      const { data } = await api.get('/orders');
      if (data.success) setOrders(data.data);
    } catch { /* ignore */ }
  };

  const cancelOrder = async (orderId) => {
    if (!confirm('주문을 취소하시겠습니까?')) return;
    await api.patch(`/orders/${orderId}/cancel`, { reason: '고객 요청 취소' });
    loadOrders();
  };

  const fmt = (n) => n?.toLocaleString() + '원';
  const fmtDate = (d) => d ? new Date(d).toLocaleDateString('ko-KR') : '-';

  return (
    <>
      <div className="page-header">
        <Container><h1 className="page-header-title">마이페이지</h1></Container>
      </div>
      <section className="shop-section">
        <Container>
          <Row>
            <Col lg={3}>
              <div className="efficacy-nav">
                <div style={{ padding: '16px', borderBottom: '1px solid var(--shop-border)', marginBottom: '12px' }}>
                  <strong>{user?.usrName}</strong>님 환영합니다
                </div>
                <button className={`efficacy-nav-item ${tab === 'orders' ? 'active' : ''}`}
                  onClick={() => setTab('orders')}>주문 내역</button>
                <button className={`efficacy-nav-item ${tab === 'info' ? 'active' : ''}`}
                  onClick={() => setTab('info')}>내 정보</button>
                <button className="efficacy-nav-item" onClick={logout} style={{ color: '#e53935' }}>로그아웃</button>
              </div>
            </Col>
            <Col lg={9}>
              {tab === 'orders' && (
                <div className="efficacy-card">
                  <h3>주문 내역</h3>
                  {orders.length === 0 ? (
                    <p className="text-center text-muted py-5">주문 내역이 없습니다.</p>
                  ) : (
                    <Table responsive hover>
                      <thead>
                        <tr><th style={{whiteSpace:'nowrap'}}>주문번호</th><th style={{whiteSpace:'nowrap'}}>주문일</th><th>상품</th><th className="text-end" style={{whiteSpace:'nowrap'}}>금액</th><th style={{whiteSpace:'nowrap'}}>상태</th><th style={{whiteSpace:'nowrap'}}></th></tr>
                      </thead>
                      <tbody>
                        {orders.map(o => (
                          <tr key={o.orderId}>
                            <td><small>{o.orderId}</small></td>
                            <td className="text-center" style={{whiteSpace:'nowrap'}}>{fmtDate(o.orderDt)}</td>
                            <td>{o.items?.map(i => i.productName).join(', ') || '-'}</td>
                            <td className="text-end"><strong>{fmt(o.totalAmount)}</strong></td>
                            <td className="text-center"><Badge bg={statusMap[o.orderStatus]?.color}>{statusMap[o.orderStatus]?.label}</Badge></td>
                            <td className="text-center">
                              {o.orderStatus === 'ORDERED' && (
                                <Button size="sm" variant="outline-danger" onClick={() => cancelOrder(o.orderId)}>취소</Button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  )}
                </div>
              )}
              {tab === 'info' && (
                <div className="efficacy-card">
                  <h3>내 정보</h3>
                  <Table borderless>
                    <tbody>
                      <tr><td width="120"><strong>아이디</strong></td><td>{user?.shopUsrId}</td></tr>
                      <tr><td><strong>이름</strong></td><td>{user?.usrName}</td></tr>
                      <tr><td><strong>연락처</strong></td><td>{user?.phone || '-'}</td></tr>
                      <tr><td><strong>이메일</strong></td><td>{user?.email || '-'}</td></tr>
                      <tr><td><strong>회원등급</strong></td><td>{user?.usrGrade === 'MEMBER' ? '일반회원' : user?.usrGrade}</td></tr>
                    </tbody>
                  </Table>
                </div>
              )}
            </Col>
          </Row>
        </Container>
      </section>
    </>
  );
}
