import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Container, Form, Button, Alert } from 'react-bootstrap';
import { ArrowLeft } from 'react-bootstrap-icons';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { useAttachments } from '../../hooks/useBoard';
import AttachmentPreview from '../../components/board/AttachmentPreview';

export default function StoryWritePage() {
  const { postId } = useParams();
  const navigate = useNavigate();
  const { isAdmin } = useAuth();
  const isEdit = !!postId;

  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const { attachments, error, setError, addFiles, remove, setCaption, loadExisting, uploadNew } = useAttachments();

  useEffect(() => {
    if (!isAdmin) { navigate('/story'); return; }
    if (isEdit) {
      api.get(`/board/posts/${postId}`)
        .then(({ data }) => { setTitle(data.data.title); setContent(data.data.content); })
        .catch(() => navigate('/story'));
      api.get(`/board/posts/${postId}/images`)
        .then(({ data }) => loadExisting(data.data || []))
        .catch(() => {});
    }
  }, [postId, isAdmin, isEdit, navigate]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!title.trim() || !content.trim()) { setError('제목과 내용을 입력하세요.'); return; }
    setSubmitting(true);
    setError('');
    try {
      let targetPostId = postId;
      if (isEdit) {
        await api.put(`/board/posts/${postId}`, { title, content });
      } else {
        const { data } = await api.post('/board/posts', { boardType: 'STORY', title, content });
        targetPostId = data.data.postId;
      }
      await uploadNew(targetPostId);
      navigate(`/story/${targetPostId}`);
    } catch (err) {
      setError(err.response?.data?.message || '저장에 실패했습니다.');
    }
    setSubmitting(false);
  };

  return (
    <>
      <div style={{ paddingTop: '80px' }} />
      <section className="shop-section" style={{ paddingTop: '20px' }}>
        <Container style={{ maxWidth: '860px' }}>
          <Button variant="link" className="mb-3 p-0 text-muted" onClick={() => navigate('/story')}>
            <ArrowLeft className="me-1" /> 목록으로
          </Button>
          <div className="efficacy-card">
            <h3 style={{ borderBottom: 'none' }}>{isEdit ? '글 수정' : '글 작성'}</h3>
            {error && <Alert variant="danger">{error}</Alert>}
            <Form onSubmit={handleSubmit}>
              <Form.Group className="mb-3">
                <Form.Label className="fw-bold">제목</Form.Label>
                <Form.Control value={title} onChange={(e) => setTitle(e.target.value)} placeholder="제목을 입력하세요" />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label className="fw-bold">내용</Form.Label>
                <Form.Control as="textarea" rows={12} value={content}
                  onChange={(e) => setContent(e.target.value)} placeholder="내용을 입력하세요" />
                <AttachmentPreview attachments={attachments} onAdd={addFiles} onRemove={remove} onCaptionChange={setCaption} />
              </Form.Group>
              <div className="text-center">
                <Button type="submit" disabled={submitting}
                  style={{ background: 'var(--shop-primary)', border: 'none', borderRadius: '50px', padding: '12px 48px', fontWeight: 500 }}>
                  {submitting ? '저장 중...' : (isEdit ? '수정 완료' : '등록')}
                </Button>
              </div>
            </Form>
          </div>
        </Container>
      </section>
    </>
  );
}
