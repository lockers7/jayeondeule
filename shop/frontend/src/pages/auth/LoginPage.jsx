import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Container, Row, Col, Form, Button, Alert } from 'react-bootstrap';
import { useAuth } from '../../context/AuthContext';

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ shopUsrId: '', passwd: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const userInfo = await login(form.shopUsrId, form.passwd);
      if (userInfo.usrGrade === 'SYSTEM_ADMIN' || userInfo.usrGrade === 'SHOP_ADMIN') {
        navigate('/admin');
      } else {
        navigate('/mypage');
      }
    } catch (err) {
      setError(err.response?.data?.message || err.message || '로그인에 실패했습니다.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <Container><h1 className="page-header-title">로그인</h1></Container>
      </div>
      <section className="shop-section">
        <Container>
          <Row className="justify-content-center">
            <Col md={4} sm={8} xs={10}>
              <div className="efficacy-card" style={{ padding: '32px 28px', border: '2px solid var(--shop-primary-light)' }}>
                <h3 style={{ textAlign: 'center', borderBottom: 'none', marginBottom: '24px' }}>회원 로그인</h3>
                {error && <Alert variant="danger">{error}</Alert>}
                <Form onSubmit={handleSubmit}>
                  <Form.Group className="mb-3">
                    <Form.Label>아이디</Form.Label>
                    <Form.Control type="text" value={form.shopUsrId} required
                      onChange={(e) => setForm({ ...form, shopUsrId: e.target.value })} />
                  </Form.Group>
                  <Form.Group className="mb-4">
                    <Form.Label>비밀번호</Form.Label>
                    <Form.Control type="password" value={form.passwd} required
                      onChange={(e) => setForm({ ...form, passwd: e.target.value })} />
                  </Form.Group>
                  <Button type="submit" className="btn-shop-primary w-100" disabled={loading}
                    style={{ justifyContent: 'center' }}>
                    {loading ? '로그인 중...' : '로그인'}
                  </Button>
                </Form>
                <div className="text-center mt-3">
                  <span className="text-muted">아직 회원이 아니신가요? </span>
                  <Link to="/register" style={{ color: 'var(--shop-primary)' }}>회원가입</Link>
                </div>
              </div>
            </Col>
          </Row>
        </Container>
      </section>
    </>
  );
}
