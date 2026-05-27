import { useState, useEffect } from 'react';
import { Container, Row, Col, Table, Badge, Button, Form, Alert } from 'react-bootstrap';
import { PencilSquare, CheckLg, XLg, KeyFill, BoxSeam } from 'react-bootstrap-icons';
import { useAuth } from '../../context/AuthContext';
import api from '../../api/client';
import { formatDate, formatCurrency, displayOrDash } from '../../utils/format';
import AddressSearch from '../../components/common/AddressSearch';
import PhoneInput from '../../components/common/PhoneInput';

const statusMap = {
  ORDERED: { label: '주문접수', color: 'secondary' },
  PAID: { label: '입금확인', color: 'info' },
  PREPARING: { label: '상품준비', color: 'primary' },
  SHIPPED: { label: '발송완료', color: 'success' },
  DELIVERED: { label: '배송완료', color: 'dark' },
  RECEIVED: { label: '거래완료', color: 'secondary' },
  CANCELLED: { label: '취소', color: 'danger' },
};

const display = displayOrDash;

export default function MyPage() {
  const { user, logout } = useAuth();
  const [orders, setOrders] = useState([]);
  const [tab, setTab] = useState('orders');
  const [profile, setProfile] = useState(null);
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState({});
  const [saveMsg, setSaveMsg] = useState('');
  // 비밀번호 변경
  const [showPwChange, setShowPwChange] = useState(false);
  const [pwForm, setPwForm] = useState({ currentPw: '', newPw: '', confirmPw: '' });
  const [pwMsg, setPwMsg] = useState('');

  // profile과 user(localStorage) 병합 — 어느 쪽이든 데이터가 있으면 표시
  const p = { ...user, ...profile };

  const loadOrders = async () => {
    try {
      const { data } = await api.get('/orders');
      if (data.success) setOrders(data.data);
    } catch { /* ignore */ }
  };

  const loadProfile = async () => {
    try {
      const { data } = await api.get('/auth/me');
      if (data.success && typeof data.data === 'object') {
        setProfile(data.data);
        // localStorage도 갱신 (주소 등 새 필드 동기화)
        const stored = JSON.parse(localStorage.getItem('shop_user') || '{}');
        localStorage.setItem('shop_user', JSON.stringify({ ...stored, ...data.data }));
      }
    } catch { /* ignore */ }
  };

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect */
    loadOrders();
    loadProfile();
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  const startEdit = () => {
    setEditForm({
      usrName: p.usrName || '',
      phone: p.phone || '',
      email: p.email || '',
      zipcode: p.zipcode || '',
      address: p.address || '',
      addressDetail: p.addressDetail || '',
    });
    setEditing(true);
    setSaveMsg('');
  };

  const cancelEdit = () => {
    setEditing(false);
    setSaveMsg('');
  };

  const saveProfile = async () => {
    try {
      const { data } = await api.put('/auth/me', editForm);
      if (data.success) {
        setProfile(data.data);
        const stored = JSON.parse(localStorage.getItem('shop_user') || '{}');
        localStorage.setItem('shop_user', JSON.stringify({ ...stored, ...data.data }));
        setEditing(false);
        setSaveMsg('회원정보가 수정되었습니다.');
        setTimeout(() => setSaveMsg(''), 3000);
      }
    } catch (err) {
      setSaveMsg(err.response?.data?.message || '수정에 실패했습니다.');
    }
  };

  const changePassword = async () => {
    setPwMsg('');
    if (!pwForm.currentPw || !pwForm.newPw) { setPwMsg('현재 비밀번호와 새 비밀번호를 입력하세요.'); return; }
    if (pwForm.newPw.length < 4) { setPwMsg('새 비밀번호는 4자 이상이어야 합니다.'); return; }
    if (pwForm.newPw !== pwForm.confirmPw) { setPwMsg('새 비밀번호가 일치하지 않습니다.'); return; }
    try {
      const { data } = await api.patch('/auth/password', {
        currentPassword: pwForm.currentPw,
        newPassword: pwForm.newPw,
      });
      if (data.success) {
        setPwMsg('비밀번호가 변경되었습니다.');
        setPwForm({ currentPw: '', newPw: '', confirmPw: '' });
        setTimeout(() => { setPwMsg(''); setShowPwChange(false); }, 2000);
      } else {
        setPwMsg(data.message);
      }
    } catch (err) {
      setPwMsg(err.response?.data?.message || '비밀번호 변경에 실패했습니다.');
    }
  };

  const receiveOrder = async (orderId) => {
    if (!confirm('제품을 수령하셨습니까? 거래가 종료됩니다.')) return;
    try {
      await api.patch(`/orders/${orderId}/receive`);
      loadOrders();
    } catch { /* ignore */ }
  };

  const cancelOrder = async (orderId) => {
    if (!confirm('주문을 취소하시겠습니까?')) return;
    await api.patch(`/orders/${orderId}/cancel`, { reason: '고객 요청 취소' });
    loadOrders();
  };

  const fmt = formatCurrency;
  const fmtDate = formatDate;

  const gradeLabel = (g) =>
    g === 'MEMBER' ? '일반회원' : g === 'SHOP_ADMIN' ? '쇼핑몰관리자' : g === 'SYSTEM_ADMIN' ? '시스템관리자' : g;

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
                  <strong>{p.usrName}</strong>님 환영합니다
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
                        <tr><th style={{whiteSpace:'nowrap'}}>주문번호</th><th style={{whiteSpace:'nowrap'}}>주문일</th><th>상품</th><th className="text-end" style={{whiteSpace:'nowrap'}}>금액</th><th style={{whiteSpace:'nowrap'}}>상태</th><th style={{whiteSpace:'nowrap'}}>제품수령</th><th style={{whiteSpace:'nowrap'}}></th></tr>
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
                              {o.orderStatus === 'DELIVERED' && (
                                <Button size="sm" variant="outline-success" style={{borderRadius:'50px', padding:'4px 14px', fontSize:'0.82rem'}}
                                  onClick={() => receiveOrder(o.orderId)}>
                                  <BoxSeam size={12} className="me-1"/> 수령확인
                                </Button>
                              )}
                              {o.orderStatus === 'RECEIVED' && (
                                <span className="text-muted" style={{fontSize:'0.82rem'}}>수령완료</span>
                              )}
                            </td>
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
                <>
                  <div className="efficacy-card">
                    <div className="d-flex justify-content-between align-items-center mb-3">
                      <h3 className="mb-0" style={{ border: 'none', padding: 0 }}>내 정보</h3>
                      {!editing && (
                        <div className="d-flex gap-2">
                          <Button size="sm" variant="outline-secondary" style={{ borderRadius: '50px', padding: '6px 20px' }}
                            onClick={() => { setShowPwChange(!showPwChange); setPwMsg(''); }}>
                            <KeyFill size={13} className="me-1" /> 비밀번호 변경
                          </Button>
                          <Button size="sm" variant="outline-primary" style={{ borderRadius: '50px', padding: '6px 20px' }}
                            onClick={startEdit}>
                            <PencilSquare size={13} className="me-1" /> 수정
                          </Button>
                        </div>
                      )}
                    </div>

                    {saveMsg && <Alert variant={saveMsg.includes('실패') ? 'danger' : 'success'} className="py-2">{saveMsg}</Alert>}

                    {!editing ? (
                      <Table borderless>
                        <tbody>
                          <tr><td width="120"><strong>아이디</strong></td><td>{display(p.shopUsrId)}</td></tr>
                          <tr><td><strong>이름</strong></td><td>{display(p.usrName)}</td></tr>
                          <tr><td><strong>연락처</strong></td><td>{display(p.phone)}</td></tr>
                          <tr><td><strong>이메일</strong></td><td>{display(p.email)}</td></tr>
                          <tr><td><strong>주소</strong></td><td>
                            {p.zipcode && p.zipcode.trim() ? (
                              <>
                                [{p.zipcode}] {p.address}
                                {p.addressDetail && p.addressDetail.trim() && <><br/>{p.addressDetail}</>}
                              </>
                            ) : '-'}
                          </td></tr>
                          <tr><td><strong>회원등급</strong></td><td>{gradeLabel(p.usrGrade)}</td></tr>
                        </tbody>
                      </Table>
                    ) : (
                      <Form>
                        <Row className="mb-3">
                          <Col md={6}>
                            <Form.Group>
                              <Form.Label className="fw-bold">이름</Form.Label>
                              <Form.Control value={editForm.usrName}
                                onChange={(e) => setEditForm({ ...editForm, usrName: e.target.value })} />
                            </Form.Group>
                          </Col>
                          <Col md={6}>
                            <Form.Group>
                              <Form.Label className="fw-bold">연락처</Form.Label>
                              <PhoneInput value={editForm.phone}
                                onChange={(v) => setEditForm({ ...editForm, phone: v })} />
                            </Form.Group>
                          </Col>
                        </Row>
                        <Form.Group className="mb-3">
                          <Form.Label className="fw-bold">이메일</Form.Label>
                          <Form.Control type="email" value={editForm.email}
                            onChange={(e) => setEditForm({ ...editForm, email: e.target.value })} />
                        </Form.Group>
                        <Form.Group className="mb-3">
                          <Form.Label className="fw-bold">주소</Form.Label>
                          <AddressSearch
                            zipcode={editForm.zipcode}
                            address={editForm.address}
                            addressDetail={editForm.addressDetail}
                            onChange={(v) => setEditForm(prev => ({
                              ...prev,
                              ...(v.zipcode !== undefined ? { zipcode: v.zipcode } : {}),
                              ...(v.address !== undefined ? { address: v.address } : {}),
                              ...(v.addressDetail !== undefined ? { addressDetail: v.addressDetail } : {}),
                            }))}
                          />
                        </Form.Group>
                        <div className="d-flex gap-2 justify-content-center mt-4">
                          <Button variant="outline-secondary" style={{ borderRadius: '50px', padding: '8px 28px' }}
                            onClick={cancelEdit}>
                            <XLg size={13} className="me-1" /> 취소
                          </Button>
                          <Button style={{ background: 'var(--shop-primary)', border: 'none', borderRadius: '50px', padding: '8px 28px', color: '#fff' }}
                            onClick={saveProfile}>
                            <CheckLg size={14} className="me-1" /> 저장
                          </Button>
                        </div>
                      </Form>
                    )}
                  </div>

                  {/* 비밀번호 변경 */}
                  {showPwChange && !editing && (
                    <div className="efficacy-card mt-3">
                      <h3 style={{ fontSize: '1.2rem' }}>비밀번호 변경</h3>
                      {pwMsg && <Alert variant={pwMsg.includes('변경되었') ? 'success' : 'danger'} className="py-2">{pwMsg}</Alert>}
                      <Form style={{ maxWidth: '400px' }}>
                        <Form.Group className="mb-3">
                          <Form.Label className="fw-bold">현재 비밀번호</Form.Label>
                          <Form.Control type="password" value={pwForm.currentPw}
                            onChange={(e) => setPwForm({ ...pwForm, currentPw: e.target.value })}
                            placeholder="현재 비밀번호 입력" />
                        </Form.Group>
                        <Form.Group className="mb-3">
                          <Form.Label className="fw-bold">새 비밀번호</Form.Label>
                          <Form.Control type="password" value={pwForm.newPw}
                            onChange={(e) => setPwForm({ ...pwForm, newPw: e.target.value })}
                            placeholder="새 비밀번호 입력" />
                        </Form.Group>
                        <Form.Group className="mb-3">
                          <Form.Label className="fw-bold">새 비밀번호 확인</Form.Label>
                          <Form.Control type="password" value={pwForm.confirmPw}
                            onChange={(e) => setPwForm({ ...pwForm, confirmPw: e.target.value })}
                            placeholder="새 비밀번호 재입력" />
                        </Form.Group>
                        <div className="d-flex gap-2 justify-content-center mt-4">
                          <Button variant="outline-secondary" style={{ borderRadius: '50px', padding: '8px 28px' }}
                            onClick={() => { setShowPwChange(false); setPwMsg(''); setPwForm({ currentPw: '', newPw: '', confirmPw: '' }); }}>
                            <XLg size={13} className="me-1" /> 취소
                          </Button>
                          <Button style={{ background: 'var(--shop-accent)', border: 'none', borderRadius: '50px', padding: '8px 28px', color: '#fff' }}
                            onClick={changePassword}>
                            <KeyFill size={14} className="me-1" /> 변경
                          </Button>
                        </div>
                      </Form>
                    </div>
                  )}
                </>
              )}
            </Col>
          </Row>
        </Container>
      </section>
    </>
  );
}
