import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Container, Row, Col, Form, Button, Alert } from 'react-bootstrap';
import { useAuth } from '../../context/AuthContext';
import api from '../../api/client';
import AddressSearch from '../../components/common/AddressSearch';
import PhoneInput from '../../components/common/PhoneInput';

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    shopUsrId: '', passwd: '', passwdConfirm: '', usrName: '',
    phone: '', email: '', zipcode: '', address: '', addressDetail: ''
  });
  const [error, setError] = useState('');
  const [idChecked, setIdChecked] = useState(false);
  const [loading, setLoading] = useState(false);

  const set = (key, val) => {
    setForm({ ...form, [key]: val });
    if (key === 'shopUsrId') setIdChecked(false);
  };

  const checkId = async () => {
    if (!form.shopUsrId.trim()) return;
    const { data } = await api.get('/auth/check-id', { params: { id: form.shopUsrId } });
    if (data.data) { setIdChecked(true); alert('사용 가능한 아이디입니다.'); }
    else alert('이미 사용 중인 아이디입니다.');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!idChecked) { setError('아이디 중복확인을 해주세요.'); return; }
    if (form.passwd !== form.passwdConfirm) { setError('비밀번호가 일치하지 않습니다.'); return; }
    if (form.passwd.length < 6) { setError('비밀번호는 6자 이상이어야 합니다.'); return; }
    setLoading(true);
    try {
      await register(form);
      alert('회원가입이 완료되었습니다. 로그인해주세요.');
      navigate('/login');
    } catch (err) {
      setError(err.response?.data?.message || err.message || '회원가입에 실패했습니다.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <Container><h1 className="page-header-title">회원가입</h1></Container>
      </div>
      <section className="shop-section">
        <Container>
          <Row className="justify-content-center">
            <Col md={6}>
              <div className="efficacy-card">
                <h3 style={{ textAlign: 'center', borderBottom: 'none' }}>회원 정보 입력</h3>
                {error && <Alert variant="danger">{error}</Alert>}
                <Form onSubmit={handleSubmit}>
                  <Form.Group className="mb-3">
                    <Form.Label>아이디 *</Form.Label>
                    <div className="d-flex gap-2">
                      <Form.Control type="text" value={form.shopUsrId} required
                        onChange={(e) => set('shopUsrId', e.target.value)} />
                      <Button variant="outline-secondary" onClick={checkId} style={{ whiteSpace: 'nowrap' }}>중복확인</Button>
                    </div>
                  </Form.Group>
                  <Form.Group className="mb-3">
                    <Form.Label>비밀번호 *</Form.Label>
                    <Form.Control type="password" value={form.passwd} required
                      onChange={(e) => set('passwd', e.target.value)} />
                  </Form.Group>
                  <Form.Group className="mb-3">
                    <Form.Label>비밀번호 확인 *</Form.Label>
                    <Form.Control type="password" value={form.passwdConfirm} required
                      onChange={(e) => set('passwdConfirm', e.target.value)} />
                  </Form.Group>
                  <Form.Group className="mb-3">
                    <Form.Label>이름 *</Form.Label>
                    <Form.Control type="text" value={form.usrName} required
                      onChange={(e) => set('usrName', e.target.value)} />
                  </Form.Group>
                  <Form.Group className="mb-3">
                    <Form.Label>연락처</Form.Label>
                    <PhoneInput value={form.phone} onChange={(v) => set('phone', v)} />
                  </Form.Group>
                  <Form.Group className="mb-3">
                    <Form.Label>이메일</Form.Label>
                    <Form.Control type="email" value={form.email}
                      onChange={(e) => set('email', e.target.value)} />
                  </Form.Group>
                  <Form.Group className="mb-3">
                    <Form.Label>주소</Form.Label>
                    <AddressSearch
                      zipcode={form.zipcode}
                      address={form.address}
                      addressDetail={form.addressDetail}
                      onChange={(v) => setForm(prev => ({ ...prev, ...v }))}
                    />
                  </Form.Group>
                  <Button type="submit" className="btn-shop-primary w-100" disabled={loading}
                    style={{ justifyContent: 'center' }}>
                    {loading ? '가입 중...' : '회원가입'}
                  </Button>
                </Form>
                <div className="text-center mt-3">
                  <span className="text-muted">이미 회원이신가요? </span>
                  <Link to="/login" style={{ color: 'var(--shop-primary)' }}>로그인</Link>
                </div>
              </div>
            </Col>
          </Row>
        </Container>
      </section>
    </>
  );
}
