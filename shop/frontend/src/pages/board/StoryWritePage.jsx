import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Container, Form, Button, Alert } from 'react-bootstrap';
import { ArrowLeft, ImageFill, XCircleFill } from 'react-bootstrap-icons';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';

function isVideo(url) {
  return /\.(mp4|webm|ogg|mov)$/i.test(url);
}

export default function StoryWritePage() {
  const { postId } = useParams();
  const navigate = useNavigate();
  const { isAdmin } = useAuth();
  const isEdit = !!postId;
  const fileRef = useRef(null);

  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [attachments, setAttachments] = useState([]); // { file?, previewUrl, type, existing? }
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!isAdmin) { navigate('/story'); return; }
    if (isEdit) {
      api.get(`/board/posts/${postId}`)
        .then(({ data }) => {
          setTitle(data.data.title);
          setContent(data.data.content);
        }).catch(() => navigate('/story'));
      api.get(`/board/posts/${postId}/images`)
        .then(({ data }) => {
          setAttachments((data.data || []).map(img => ({
            previewUrl: img.imageUrl,
            type: isVideo(img.imageUrl) ? 'video' : 'image',
            existing: true,
          })));
        }).catch(() => {});
    }
  }, [postId, isAdmin, isEdit, navigate]);

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
      if (!prev[idx].existing) URL.revokeObjectURL(prev[idx].previewUrl);
      return prev.filter((_, i) => i !== idx);
    });
  };

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

      // 새 파일 업로드
      const newFiles = attachments.filter(a => !a.existing && a.file);
      if (newFiles.length > 0) {
        const formData = new FormData();
        for (const att of newFiles) formData.append('files', att.file);
        formData.append('postId', targetPostId);
        await api.post('/board/images/upload', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });
      }

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
                <Form.Control value={title} onChange={(e) => setTitle(e.target.value)}
                  placeholder="제목을 입력하세요" />
              </Form.Group>

              <Form.Group className="mb-3">
                <Form.Label className="fw-bold">내용</Form.Label>
                <Form.Control as="textarea" rows={12} value={content}
                  onChange={(e) => setContent(e.target.value)}
                  placeholder="내용을 입력하세요" />

                {attachments.length > 0 && (
                  <div style={{
                    border: '2px solid #90A4AE', borderTop: 'none', borderRadius: '0 0 8px 8px',
                    padding: '12px', background: '#fafffe',
                  }}>
                    {attachments.map((att, i) => (
                      <div key={i} style={{ position: 'relative', marginBottom: i < attachments.length - 1 ? 12 : 0 }}>
                        {att.type === 'video' ? (
                          <video controls style={{ width: '100%', aspectRatio: '16/9', borderRadius: '8px', background: '#000', objectFit: 'contain' }}>
                            <source src={att.previewUrl} />
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
