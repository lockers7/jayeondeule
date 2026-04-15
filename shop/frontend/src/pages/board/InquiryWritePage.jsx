import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Container, Form, Button, Alert } from 'react-bootstrap';
import { ArrowLeft } from 'react-bootstrap-icons';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { useAttachments } from '../../hooks/useBoard';
import AttachmentPreview from '../../components/board/AttachmentPreview';

export default function InquiryWritePage() {
  const navigate = useNavigate();
  const { user } = useAuth();

  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [productId, setProductId] = useState('');
  const [products, setProducts] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const { attachments, error, setError, addFiles, remove, setCaption, uploadNew } = useAttachments();

  useEffect(() => {
    if (!user) { navigate('/login'); return; }
    api.get('/products', { params: { farmId: 1 } })
      .then(({ data }) => setProducts(data.data || []))
      .catch(() => {});
  }, [user, navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!title.trim() || !content.trim()) { setError('제목과 내용을 입력하세요.'); return; }
    setSubmitting(true);
    setError('');
    try {
      const { data } = await api.post('/board/posts', {
        boardType: 'INQUIRY', title, content, productId: productId || null,
      });
      const postId = data.data.postId;
      await uploadNew(postId);
      navigate(`/inquiry/${postId}`);
    } catch (err) {
      setError(err.response?.data?.message || '등록에 실패했습니다.');
    }
    setSubmitting(false);
  };

  return (
    <>
      <div style={{ paddingTop: '80px' }} />
      <section className="shop-section" style={{ paddingTop: '20px' }}>
        <Container style={{ maxWidth: '860px' }}>
          <Button variant="link" className="mb-3 p-0 text-muted" onClick={() => navigate('/inquiry')}>
            <ArrowLeft className="me-1" /> 목록으로
          </Button>
          <div className="efficacy-card">
            <h3 style={{ borderBottom: 'none' }}>문의 작성</h3>
            {error && <Alert variant="danger">{error}</Alert>}
            <Form onSubmit={handleSubmit}>
              <Form.Group className="mb-3">
                <Form.Label className="fw-bold">문의 제품</Form.Label>
                <Form.Select value={productId} onChange={(e) => setProductId(e.target.value)}>
                  <option value="">제품을 선택하세요 (선택사항)</option>
                  {products.map((p) => (
                    <option key={p.productId} value={p.productId}>{p.productName}</option>
                  ))}
                </Form.Select>
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label className="fw-bold">제목</Form.Label>
                <Form.Control value={title} onChange={(e) => setTitle(e.target.value)} placeholder="문의 제목을 입력하세요" />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label className="fw-bold">문의 내용</Form.Label>
                <Form.Control as="textarea" rows={8} value={content}
                  onChange={(e) => setContent(e.target.value)} placeholder="문의 내용을 상세히 입력하세요" />
                <AttachmentPreview attachments={attachments} onAdd={addFiles} onRemove={remove} onCaptionChange={setCaption} />
              </Form.Group>
              <div className="text-center">
                <Button type="submit" disabled={submitting}
                  style={{ background: 'var(--shop-accent)', border: 'none', borderRadius: '50px', padding: '12px 48px', fontWeight: 500 }}>
                  {submitting ? '등록 중...' : '문의 등록'}
                </Button>
              </div>
            </Form>
          </div>
        </Container>
      </section>
    </>
  );
}
