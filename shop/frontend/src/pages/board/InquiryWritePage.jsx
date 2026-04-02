import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Container, Form, Button, Alert } from 'react-bootstrap';
import { ArrowLeft, ImageFill, XCircleFill } from 'react-bootstrap-icons';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';

export default function InquiryWritePage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const fileRef = useRef(null);

  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [productId, setProductId] = useState('');
  const [products, setProducts] = useState([]);
  const [attachments, setAttachments] = useState([]); // { file, previewUrl, type }
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!user) { navigate('/login'); return; }
    api.get('/products', { params: { farmId: 1 } })
      .then(({ data }) => setProducts(data.data || []))
      .catch(() => {});
  }, [user, navigate]);

  const MAX_IMAGE_MB = 300;
  const MAX_VIDEO_MB = 700;

  const handleFileSelect = (e) => {
    const files = Array.from(e.target.files || []);
    for (const file of files) {
      const isVid = file.type.startsWith('video/');
      const maxMB = isVid ? MAX_VIDEO_MB : MAX_IMAGE_MB;
      if (file.size > maxMB * 1024 * 1024) {
        setError(`${isVid ? '동영상' : '이미지'} 최대 크기는 ${maxMB}MB입니다. (${file.name})`);
        e.target.value = '';
        return;
      }
    }
    setError('');
    const newAttachments = files.map(file => ({
      file,
      previewUrl: URL.createObjectURL(file),
      type: file.type.startsWith('video/') ? 'video' : 'image',
    }));
    setAttachments(prev => [...prev, ...newAttachments]);
    e.target.value = '';
  };

  const removeAttachment = (idx) => {
    setAttachments(prev => {
      URL.revokeObjectURL(prev[idx].previewUrl);
      return prev.filter((_, i) => i !== idx);
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!title.trim() || !content.trim()) { setError('제목과 내용을 입력하세요.'); return; }

    setSubmitting(true);
    setError('');
    try {
      // 1. 게시글 저장
      const { data } = await api.post('/board/posts', {
        boardType: 'INQUIRY',
        title,
        content,
        productId: productId || null,
      });
      const postId = data.data.postId;

      // 2. 첨부 파일 업로드 (있으면)
      if (attachments.length > 0) {
        const formData = new FormData();
        for (const att of attachments) formData.append('files', att.file);
        formData.append('postId', postId);
        await api.post('/board/images/upload', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });
      }

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
                <Form.Control value={title} onChange={(e) => setTitle(e.target.value)}
                  placeholder="문의 제목을 입력하세요" />
              </Form.Group>

              <Form.Group className="mb-3">
                <Form.Label className="fw-bold">문의 내용</Form.Label>
                <Form.Control as="textarea" rows={8} value={content}
                  onChange={(e) => setContent(e.target.value)}
                  placeholder="문의 내용을 상세히 입력하세요" />

                {/* 첨부된 이미지/동영상 미리보기 — 문의내용 칸 아래에 표시 */}
                {attachments.length > 0 && (
                  <div style={{
                    border: '2px solid #90A4AE', borderTop: 'none', borderRadius: '0 0 8px 8px',
                    padding: '12px', background: '#fafffe',
                  }}>
                    {attachments.map((att, i) => (
                      <div key={i} style={{ position: 'relative', marginBottom: i < attachments.length - 1 ? 12 : 0 }}>
                        {att.type === 'video' ? (
                          <video controls style={{ width: '100%', aspectRatio: '16/9', borderRadius: '8px', background: '#000', objectFit: 'contain' }}>
                            <source src={att.previewUrl} type={att.file.type} />
                          </video>
                        ) : (
                          <img src={att.previewUrl} alt=""
                            style={{ width: '100%', borderRadius: '8px', maxHeight: '400px', objectFit: 'contain' }} />
                        )}
                        <XCircleFill
                          size={24}
                          style={{
                            position: 'absolute', top: 8, right: 8, cursor: 'pointer',
                            color: '#dc3545', background: '#fff', borderRadius: '50%',
                          }}
                          onClick={() => removeAttachment(i)}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </Form.Group>

              <div className="mb-4">
                <input type="file" ref={fileRef} accept="image/*,video/mp4,video/webm,video/ogg,video/quicktime"
                  multiple style={{ display: 'none' }} onChange={handleFileSelect} />
                <Button size="sm" variant="outline-secondary" onClick={() => fileRef.current?.click()}>
                  <ImageFill className="me-1" /> 이미지/동영상 첨부
                </Button>
                {attachments.length > 0 && (
                  <span className="ms-2 text-muted" style={{ fontSize: '0.85rem' }}>
                    {attachments.length}개 첨부됨
                  </span>
                )}
              </div>

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
