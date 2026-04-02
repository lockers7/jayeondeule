import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Container, Button, Badge } from 'react-bootstrap';
import { ArrowLeft, Trash, PersonFill, CalendarEvent, Box, CheckCircleFill } from 'react-bootstrap-icons';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import CommentSection from '../../components/board/CommentSection';

function formatDate(dt) {
  if (!dt) return '';
  const d = new Date(dt);
  return d.toLocaleDateString('ko-KR') + ' ' + d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
}

function isVideo(url) {
  return /\.(mp4|webm|ogg|mov)$/i.test(url);
}

export default function InquiryDetailPage() {
  const { postId } = useParams();
  const navigate = useNavigate();
  const { user, isAdmin } = useAuth();
  const [post, setPost] = useState(null);
  const [images, setImages] = useState([]);

  useEffect(() => {
    api.get(`/board/posts/${postId}`)
      .then(({ data }) => setPost(data.data))
      .catch(() => navigate('/inquiry'));
    api.get(`/board/posts/${postId}/images`)
      .then(({ data }) => setImages(data.data || []))
      .catch(() => {});
  }, [postId, navigate]);

  const handleDelete = async () => {
    if (!window.confirm('문의를 삭제하시겠습니까?')) return;
    try {
      await api.delete(`/board/posts/${postId}`);
      navigate('/inquiry');
    } catch { /* ignore */ }
  };

  if (!post) return null;

  const canDelete = user && (isAdmin || user.shopUsrId === post.writerId);

  return (
    <>
      <div style={{ paddingTop: '80px' }} />
      <section className="shop-section" style={{ paddingTop: '20px' }}>
        <Container style={{ maxWidth: '860px' }}>
          <Button variant="link" className="mb-3 p-0 text-muted" onClick={() => navigate('/inquiry')}>
            <ArrowLeft className="me-1" /> 목록으로
          </Button>

          <div className="efficacy-card">
            <div className="d-flex align-items-center gap-2 mb-2">
              <h3 style={{ borderBottom: 'none', paddingBottom: 0, marginBottom: 0, flex: 1 }}>{post.title}</h3>
              {post.productName && (
                <Badge bg="info" className="ms-2" style={{ fontSize: '0.8rem' }}>
                  <Box size={12} className="me-1" />{post.productName}
                </Badge>
              )}
            </div>
            <div className="d-flex gap-3 mb-4" style={{ fontSize: '0.85rem', color: 'var(--shop-text-light)' }}>
              <span><PersonFill size={13} className="me-1" />{post.writerName}</span>
              <span><CalendarEvent size={13} className="me-1" />{formatDate(post.rgstDt)}</span>
            </div>

            {images.length > 0 && (
              <div className="mb-4">
                {images.map((img, i) => (
                  isVideo(img.imageUrl) ? (
                    <video key={i} controls style={{ width: '100%', aspectRatio: '16/9', borderRadius: '12px', marginBottom: '12px', background: '#000', objectFit: 'contain' }}>
                      <source src={img.imageUrl} />
                    </video>
                  ) : (
                    <img key={i} src={img.imageUrl} alt=""
                      style={{ maxWidth: '100%', borderRadius: '12px', marginBottom: '12px' }} />
                  )
                ))}
              </div>
            )}

            <div style={{ fontSize: '0.95rem', lineHeight: 1.9, whiteSpace: 'pre-wrap' }}>
              {post.content}
            </div>

            {(canDelete || isAdmin) && (
              <div className="d-flex gap-2 mt-4 pt-3" style={{ borderTop: '1px solid var(--shop-border)' }}>
                {isAdmin && (
                  <Button size="sm"
                    variant={post.resolveYn === 'Y' ? 'outline-secondary' : 'success'}
                    style={{ borderRadius: '50px', padding: '6px 20px' }}
                    onClick={async () => {
                      await api.patch(`/board/posts/${postId}/resolve`, { resolve: post.resolveYn !== 'Y' });
                      setPost({ ...post, resolveYn: post.resolveYn === 'Y' ? 'N' : 'Y' });
                    }}>
                    <CheckCircleFill size={13} className="me-1" />
                    {post.resolveYn === 'Y' ? '완료 해제' : '완료 처리'}
                  </Button>
                )}
                {canDelete && (
                  <Button size="sm" variant="outline-danger" style={{ borderRadius: '50px', padding: '6px 20px' }}
                    onClick={handleDelete}>
                    <Trash size={13} className="me-1" /> 삭제
                  </Button>
                )}
              </div>
            )}
          </div>

          {/* 댓글 = 답변 */}
          <CommentSection postId={parseInt(postId)} />
        </Container>
      </section>
    </>
  );
}
