import { useState, useEffect } from 'react';
import { Container, Row, Col, Table, Badge, Button, Form, Modal } from 'react-bootstrap';
import { useAuth } from '../../context/AuthContext';
import api from '../../api/client';

const statusMap = {
  ORDERED: { label: '주문접수', color: 'secondary', next: 'PAID', nextLabel: '입금확인' },
  PAID: { label: '입금확인', color: 'info', next: 'PREPARING', nextLabel: '상품준비' },
  PREPARING: { label: '상품준비', color: 'primary', next: 'SHIPPED', nextLabel: '발송' },
  SHIPPED: { label: '발송완료', color: 'success', next: 'DELIVERED', nextLabel: '배송완료' },
  DELIVERED: { label: '배송완료', color: 'dark' },
  CANCELLED: { label: '취소', color: 'danger' },
};

export default function AdminPage() {
  const { user, isAdmin, isMonitor } = useAuth();
  const [tab, setTab] = useState('dashboard');
  const [stats, setStats] = useState({});
  const [orders, setOrders] = useState([]);
  const [products, setProducts] = useState([]);
  const [members, setMembers] = useState([]);
  const [showProduct, setShowProduct] = useState(false);
  const [editProduct, setEditProduct] = useState(null);

  useEffect(() => {
    if (tab === 'dashboard') loadDashboard();
    if (tab === 'orders') loadOrders();
    if (tab === 'products') loadProducts();
    if (tab === 'members') loadMembers();
  }, [tab]);

  const loadDashboard = async () => { const { data } = await api.get('/admin/dashboard'); if (data.success) setStats(data.data); };
  const loadOrders = async () => { const { data } = await api.get('/admin/orders'); if (data.success) setOrders(data.data); };
  const loadProducts = async () => { const { data } = await api.get('/admin/products'); if (data.success) setProducts(data.data); };
  const loadMembers = async () => { const { data } = await api.get('/admin/members'); if (data.success) setMembers(data.data); };

  const updateStatus = async (orderId, status) => {
    await api.patch(`/admin/orders/${orderId}/status`, { status });
    loadOrders();
    loadDashboard();
  };

  const saveProduct = async () => {
    if (editProduct.productId) {
      await api.put(`/admin/products/${editProduct.productId}`, editProduct);
    } else {
      await api.post('/admin/products', { ...editProduct, farmId: 1 });
    }
    setShowProduct(false);
    loadProducts();
  };

  const fmt = (n) => (n || 0).toLocaleString() + '원';
  const fmtDate = (d) => d ? new Date(d).toLocaleDateString('ko-KR') : '-';

  return (
    <>
      <div className="page-header">
        <Container><h1 className="page-header-title">관리자</h1></Container>
      </div>
      <section className="shop-section">
        <Container>
          <Row>
            <Col lg={2}>
              <div className="efficacy-nav">
                <div style={{ padding: '12px 16px', fontWeight: 700, color: 'var(--shop-primary)' }}>관리메뉴</div>
                {['dashboard', 'orders', 'products', 'members'].map(t => (
                  <button key={t} className={`efficacy-nav-item ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
                    {{ dashboard: '대시보드', orders: '주문관리', products: '상품관리', members: '회원관리' }[t]}
                  </button>
                ))}
              </div>
            </Col>
            <Col lg={10}>
              {/* 대시보드 */}
              {tab === 'dashboard' && (
                <div className="efficacy-card">
                  <h3>대시보드</h3>
                  <div className="efficacy-stat-grid">
                    <div className="efficacy-stat-item"><div className="efficacy-stat-number">{stats.totalOrders || 0}</div><div className="efficacy-stat-label">신규 주문</div></div>
                    <div className="efficacy-stat-item"><div className="efficacy-stat-number">{stats.paidOrders || 0}</div><div className="efficacy-stat-label">입금확인</div></div>
                    <div className="efficacy-stat-item"><div className="efficacy-stat-number">{stats.preparingOrders || 0}</div><div className="efficacy-stat-label">상품준비</div></div>
                    <div className="efficacy-stat-item"><div className="efficacy-stat-number">{stats.shippedOrders || 0}</div><div className="efficacy-stat-label">발송완료</div></div>
                    <div className="efficacy-stat-item"><div className="efficacy-stat-number">{fmt(stats.totalRevenue)}</div><div className="efficacy-stat-label">총 매출</div></div>
                    <div className="efficacy-stat-item"><div className="efficacy-stat-number">{stats.totalMembers || 0}</div><div className="efficacy-stat-label">일반 회원수</div></div>
                  </div>
                </div>
              )}

              {/* 주문관리 */}
              {tab === 'orders' && (
                <div className="efficacy-card">
                  <h3>주문 관리</h3>
                  <Table responsive hover size="sm">
                    <thead><tr><th style={{whiteSpace:'nowrap'}}>주문번호</th><th style={{whiteSpace:'nowrap'}}>주문자</th><th>상품</th><th className="text-end" style={{whiteSpace:'nowrap'}}>금액</th><th style={{whiteSpace:'nowrap'}}>주문일</th><th style={{whiteSpace:'nowrap'}}>상태</th><th style={{whiteSpace:'nowrap'}}>관리</th></tr></thead>
                    <tbody>
                      {orders.map(o => (
                        <tr key={o.orderId}>
                          <td><small>{o.orderId}</small></td>
                          <td>{o.receiverName}<br/><small className="text-muted">{o.receiverPhone}</small></td>
                          <td>{o.items?.map(i => `${i.productName} x${i.quantity}`).join(', ')}</td>
                          <td className="text-end"><strong>{fmt(o.totalAmount)}</strong></td>
                          <td className="text-center" style={{whiteSpace:'nowrap'}}>{fmtDate(o.orderDt)}</td>
                          <td className="text-center"><Badge bg={statusMap[o.orderStatus]?.color}>{statusMap[o.orderStatus]?.label}</Badge></td>
                          <td className="text-center" style={{whiteSpace:'nowrap'}}>
                            {isAdmin && statusMap[o.orderStatus]?.next && (
                              <Button size="sm" variant="outline-primary"
                                onClick={() => updateStatus(o.orderId, statusMap[o.orderStatus].next)}>
                                {statusMap[o.orderStatus].nextLabel}
                              </Button>
                            )}
                            {isAdmin && o.orderStatus !== 'CANCELLED' && o.orderStatus !== 'DELIVERED' && (
                              <Button size="sm" variant="outline-danger" className="ms-1"
                                onClick={() => updateStatus(o.orderId, 'CANCELLED')}>취소</Button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                  {orders.length === 0 && <p className="text-center text-muted py-4">주문이 없습니다.</p>}
                </div>
              )}

              {/* 상품관리 */}
              {tab === 'products' && (
                <div className="efficacy-card">
                  <div className="d-flex justify-content-between align-items-center mb-3">
                    <h3 className="mb-0" style={{ border: 'none', padding: 0 }}>상품 관리</h3>
                    {isAdmin && (
                      <Button className="btn-shop-primary" onClick={() => { setEditProduct({ farmId: 1, price: 0, stockQty: 0, saleStatus: 'ON_SALE', unit: '100g', sortOrder: 0 }); setShowProduct(true); }}>
                        상품 추가
                      </Button>
                    )}
                  </div>
                  <Table responsive hover size="sm">
                    <thead><tr><th className="text-end" style={{whiteSpace:'nowrap'}}>ID</th><th>상품명</th><th className="text-end" style={{whiteSpace:'nowrap'}}>가격</th><th className="text-end" style={{whiteSpace:'nowrap'}}>재고</th><th style={{whiteSpace:'nowrap'}}>상태</th><th className="text-end" style={{whiteSpace:'nowrap'}}>조회수</th><th style={{whiteSpace:'nowrap'}}>관리</th></tr></thead>
                    <tbody>
                      {products.map(p => (
                        <tr key={p.productId}>
                          <td className="text-end">{p.productId}</td>
                          <td>{p.productName}</td>
                          <td className="text-end">{fmt(p.price)}</td>
                          <td className="text-end">{p.stockQty}</td>
                          <td className="text-center"><Badge bg={p.saleStatus === 'ON_SALE' ? 'success' : p.saleStatus === 'SOLD_OUT' ? 'warning' : 'secondary'}>
                            {p.saleStatus === 'ON_SALE' ? '판매중' : p.saleStatus === 'SOLD_OUT' ? '품절' : '중지'}
                          </Badge></td>
                          <td className="text-end">{p.viewCount}</td>
                          <td className="text-center">{isAdmin && <Button size="sm" variant="outline-primary" onClick={() => { setEditProduct({ ...p }); setShowProduct(true); }}>수정</Button>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </div>
              )}

              {/* 회원관리 */}
              {tab === 'members' && (
                <div className="efficacy-card">
                  <h3>회원 관리</h3>
                  <Table responsive hover size="sm">
                    <thead><tr><th style={{whiteSpace:'nowrap'}}>아이디</th><th style={{whiteSpace:'nowrap'}}>이름</th><th style={{whiteSpace:'nowrap'}}>등급</th><th style={{whiteSpace:'nowrap'}}>연락처</th><th>이메일</th><th style={{whiteSpace:'nowrap'}}>가입일</th></tr></thead>
                    <tbody>
                      {members.map(m => (
                        <tr key={m.shopUsrId}>
                          <td>{m.shopUsrId}</td>
                          <td>{m.usrName}</td>
                          <td className="text-center"><Badge bg={m.usrGrade === 'SYSTEM_ADMIN' ? 'danger' : m.usrGrade === 'SHOP_ADMIN' ? 'primary' : 'secondary'}>
                            {m.usrGrade === 'SYSTEM_ADMIN' ? '시스템관리자' : m.usrGrade === 'SHOP_ADMIN' ? '쇼핑몰관리자' : '일반회원'}
                          </Badge></td>
                          <td>{m.phone || '-'}</td>
                          <td>{m.email || '-'}</td>
                          <td className="text-center" style={{whiteSpace:'nowrap'}}>{fmtDate(m.rgstDt)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </div>
              )}
            </Col>
          </Row>
        </Container>
      </section>

      {/* 상품 편집 모달 */}
      <Modal show={showProduct} onHide={() => setShowProduct(false)} size="lg">
        <Modal.Header closeButton><Modal.Title>{editProduct?.productId ? '상품 수정' : '상품 추가'}</Modal.Title></Modal.Header>
        <Modal.Body>
          {editProduct && (
            <Form>
              <Row>
                <Col md={8}><Form.Group className="mb-3"><Form.Label>상품명</Form.Label>
                  <Form.Control value={editProduct.productName || ''} onChange={e => setEditProduct({ ...editProduct, productName: e.target.value })} /></Form.Group></Col>
                <Col md={4}><Form.Group className="mb-3"><Form.Label>단위</Form.Label>
                  <Form.Control value={editProduct.unit || ''} onChange={e => setEditProduct({ ...editProduct, unit: e.target.value })} /></Form.Group></Col>
              </Row>
              <Form.Group className="mb-3"><Form.Label>부제목</Form.Label>
                <Form.Control value={editProduct.subtitle || ''} onChange={e => setEditProduct({ ...editProduct, subtitle: e.target.value })} /></Form.Group>
              <Row>
                <Col md={4}><Form.Group className="mb-3"><Form.Label>가격</Form.Label>
                  <Form.Control type="number" value={editProduct.price || 0} onChange={e => setEditProduct({ ...editProduct, price: parseInt(e.target.value) })} /></Form.Group></Col>
                <Col md={4}><Form.Group className="mb-3"><Form.Label>재고수량</Form.Label>
                  <Form.Control type="number" value={editProduct.stockQty || 0} onChange={e => setEditProduct({ ...editProduct, stockQty: parseInt(e.target.value) })} /></Form.Group></Col>
                <Col md={4}><Form.Group className="mb-3"><Form.Label>판매상태</Form.Label>
                  <Form.Select value={editProduct.saleStatus} onChange={e => setEditProduct({ ...editProduct, saleStatus: e.target.value })}>
                    <option value="ON_SALE">판매중</option><option value="SOLD_OUT">품절</option><option value="STOPPED">판매중지</option>
                  </Form.Select></Form.Group></Col>
              </Row>
              <Form.Group className="mb-3"><Form.Label>상품설명</Form.Label>
                <Form.Control as="textarea" rows={3} value={editProduct.description || ''} onChange={e => setEditProduct({ ...editProduct, description: e.target.value })} /></Form.Group>
            </Form>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowProduct(false)}>닫기</Button>
          <Button className="btn-shop-primary" onClick={saveProduct}>저장</Button>
        </Modal.Footer>
      </Modal>
    </>
  );
}
