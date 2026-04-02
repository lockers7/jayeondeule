import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Container, Button } from 'react-bootstrap';
import { ArrowLeft, PencilSquare, Trash, Eye, PersonFill, CalendarEvent } from 'react-bootstrap-icons';

function isVideo(url) {
  return /\.(mp4|webm|ogg|mov)$/i.test(url);
}
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import CommentSection from '../../components/board/CommentSection';

function formatDate(dt) {
  if (!dt) return '';
  const d = new Date(dt);
  return d.toLocaleDateString('ko-KR') + ' ' + d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
}

export default function StoryDetailPage() {
  const { postId } = useParams();
  const navigate = useNavigate();
  const { user, isAdmin } = useAuth();
  const [post, setPost] = useState(null);
  const [images, setImages] = useState([]);

  useEffect(() => {
    api.get(`/board/posts/${postId}`)
      .then(({ data }) => setPost(data.data))
      .catch(() => navigate('/story'));
    api.get(`/board/posts/${postId}/images`)
      .then(({ data }) => setImages(data.data || []))
      .catch(() => {});
  }, [postId, navigate]);

  const handleDelete = async () => {
    if (!window.confirm('게시글을 삭제하시겠습니까?')) return;
    try {
      await api.delete(`/board/posts/${postId}`);
      navigate('/story');
    } catch { /* ignore */ }
  };

  if (!post) return null;

  const canEdit = user && (isAdmin || user.shopUsrId === post.writerId);

  return (
    <>
      <div style={{ paddingTop: '80px' }} />
      <section className="shop-section" style={{ paddingTop: '20px' }}>
        <Container style={{ maxWidth: '860px' }}>
          <Button variant="link" className="mb-3 p-0 text-muted" onClick={() => navigate('/story')}>
            <ArrowLeft className="me-1" /> 목록으로
          </Button>

          <div className="efficacy-card">
            <h3 style={{ borderBottom: 'none', paddingBottom: 0, marginBottom: '12px' }}>{post.title}</h3>
            <div className="d-flex gap-3 mb-4" style={{ fontSize: '0.85rem', color: 'var(--shop-text-light)' }}>
              <span><PersonFill size={13} className="me-1" />{post.writerName}</span>
              <span><CalendarEvent size={13} className="me-1" />{formatDate(post.rgstDt)}</span>
              <span><Eye size={13} className="me-1" />{post.viewCount}</span>
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

            {canEdit && (
              <div className="d-flex gap-2 mt-4 pt-3" style={{ borderTop: '1px solid var(--shop-border)' }}>
                <Button size="sm" variant="outline-primary" style={{ borderRadius: '50px', padding: '6px 20px' }}
                  onClick={() => navigate(`/story/edit/${postId}`)}>
                  <PencilSquare size={13} className="me-1" /> 수정
                </Button>
                <Button size="sm" variant="outline-danger" style={{ borderRadius: '50px', padding: '6px 20px' }}
                  onClick={handleDelete}>
                  <Trash size={13} className="me-1" /> 삭제
                </Button>
              </div>
            )}
          </div>

          <CommentSection postId={parseInt(postId)} />
        </Container>
      </section>
    </>
  );
}
