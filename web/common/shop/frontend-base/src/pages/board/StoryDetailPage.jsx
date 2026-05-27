import { useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Container, Button } from 'react-bootstrap';
import { ArrowLeft, PencilSquare, Trash, Eye, PersonFill, CalendarEvent } from 'react-bootstrap-icons';
import { useAuth } from '../../context/AuthContext';
import { usePostDetail } from '../../hooks/useBoard';
import { formatDateTime } from '../../utils/format';
import MediaGallery from '../../components/board/MediaGallery';
import CommentSection from '../../components/board/CommentSection';
import api from '../../api/client';

export default function StoryDetailPage() {
  const { postId } = useParams();
  const navigate = useNavigate();
  const { user, isAdmin } = useAuth();
  const { post, images, loading, load } = usePostDetail();

  useEffect(() => { load(postId); }, [postId, load]);

  if (loading || !post) return null;

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
              <span><CalendarEvent size={13} className="me-1" />{formatDateTime(post.rgstDt)}</span>
              <span><Eye size={13} className="me-1" />{post.viewCount}</span>
            </div>
            <MediaGallery images={images} />
            <div style={{ fontSize: '0.95rem', lineHeight: 1.9, whiteSpace: 'pre-wrap' }}>{post.content}</div>
            {canEdit && (
              <div className="d-flex gap-2 mt-4 pt-3" style={{ borderTop: '1px solid var(--shop-border)' }}>
                <Button size="sm" variant="outline-primary" style={{ borderRadius: '50px', padding: '6px 20px' }}
                  onClick={() => navigate(`/story/edit/${postId}`)}>
                  <PencilSquare size={13} className="me-1" /> 수정
                </Button>
                <Button size="sm" variant="outline-danger" style={{ borderRadius: '50px', padding: '6px 20px' }}
                  onClick={async () => {
                    if (!window.confirm('게시글을 삭제하시겠습니까?')) return;
                    await api.delete(`/board/posts/${postId}`);
                    navigate('/story');
                  }}>
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
