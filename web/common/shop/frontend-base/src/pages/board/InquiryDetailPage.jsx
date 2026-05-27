import { useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Container, Button, Badge } from 'react-bootstrap';
import { ArrowLeft, Trash, PersonFill, CalendarEvent, Box, CheckCircleFill } from 'react-bootstrap-icons';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { usePostDetail } from '../../hooks/useBoard';
import { formatDateTime } from '../../utils/format';
import MediaGallery from '../../components/board/MediaGallery';
import CommentSection from '../../components/board/CommentSection';

export default function InquiryDetailPage() {
  const { postId } = useParams();
  const navigate = useNavigate();
  const { user, isAdmin } = useAuth();
  const { post, setPost, images, loading, load } = usePostDetail();

  useEffect(() => { load(postId); }, [postId, load]);

  if (loading || !post) return null;

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
              <span><CalendarEvent size={13} className="me-1" />{formatDateTime(post.rgstDt)}</span>
            </div>
            <MediaGallery images={images} />
            <div style={{ fontSize: '0.95rem', lineHeight: 1.9, whiteSpace: 'pre-wrap' }}>{post.content}</div>
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
                    onClick={async () => {
                      if (!window.confirm('문의를 삭제하시겠습니까?')) return;
                      await api.delete(`/board/posts/${postId}`);
                      navigate('/inquiry');
                    }}>
                    <Trash size={13} className="me-1" /> 삭제
                  </Button>
                )}
              </div>
            )}
          </div>
          <CommentSection postId={parseInt(postId)} />
        </Container>
      </section>
    </>
  );
}
