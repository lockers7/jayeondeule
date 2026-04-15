import { useState, useEffect, useCallback } from 'react';
import { Form, Button } from 'react-bootstrap';
import { PersonFill, ChatDots, Trash, Reply } from 'react-bootstrap-icons';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { formatDateTime } from '../../utils/format';

function CommentItem({ comment, postId, onRefresh, depth = 0 }) {
  const { user, isAdmin } = useAuth();
  const [showReply, setShowReply] = useState(false);
  const [replyContent, setReplyContent] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleReply = async () => {
    if (!replyContent.trim()) return;
    setSubmitting(true);
    try {
      await api.post(`/board/posts/${postId}/comments`, {
        parentId: comment.commentId,
        content: replyContent.trim(),
      });
      setReplyContent('');
      setShowReply(false);
      onRefresh();
    } catch { /* ignore */ }
    setSubmitting(false);
  };

  const handleDelete = async () => {
    if (!window.confirm('댓글을 삭제하시겠습니까?')) return;
    try {
      await api.delete(`/board/comments/${comment.commentId}`);
      onRefresh();
    } catch { /* ignore */ }
  };

  const canDelete = user && (isAdmin || user.shopUsrId === comment.writerId);
  const maxDepth = 5;

  return (
    <div style={{ marginLeft: Math.min(depth, maxDepth) * 24, marginTop: depth > 0 ? 8 : 16 }}>
      <div style={{
        padding: '12px 16px',
        background: depth > 0 ? '#f8fffe' : '#fff',
        border: '1px solid var(--shop-border)',
        borderRadius: '10px',
      }}>
        <div className="d-flex justify-content-between align-items-center mb-1">
          <div className="d-flex align-items-center gap-2">
            <PersonFill size={14} style={{ color: 'var(--shop-primary)' }} />
            <strong style={{ fontSize: '0.9rem' }}>{comment.writerName}</strong>
            <span style={{ fontSize: '0.78rem', color: 'var(--shop-text-light)' }}>
              {formatDateTime(comment.rgstDt)}
            </span>
          </div>
          <div className="d-flex gap-2">
            {user && (
              <Button variant="link" size="sm" className="p-0 text-muted"
                onClick={() => setShowReply(!showReply)} title="답글">
                <Reply size={14} />
              </Button>
            )}
            {canDelete && (
              <Button variant="link" size="sm" className="p-0 text-danger"
                onClick={handleDelete} title="삭제">
                <Trash size={13} />
              </Button>
            )}
          </div>
        </div>
        <p className="mb-0" style={{ fontSize: '0.92rem', whiteSpace: 'pre-wrap' }}>
          {comment.content}
        </p>
        {comment.images?.length > 0 && (
          <div className="d-flex gap-2 mt-2 flex-wrap">
            {comment.images.map((img, i) => (
              <img key={i} src={img.imageUrl} alt="" style={{
                maxWidth: '200px', maxHeight: '150px', borderRadius: '8px', objectFit: 'cover',
                border: '1px solid var(--shop-border)',
              }} />
            ))}
          </div>
        )}
      </div>

      {showReply && (
        <div className="mt-2" style={{ marginLeft: 24 }}>
          <Form.Control as="textarea" rows={2} value={replyContent}
            onChange={(e) => setReplyContent(e.target.value)}
            placeholder="답글을 입력하세요" style={{ fontSize: '0.9rem' }} />
          <div className="d-flex gap-2 mt-1">
            <Button size="sm" variant="outline-secondary" onClick={() => setShowReply(false)}>취소</Button>
            <Button size="sm" style={{ background: 'var(--shop-primary)', border: 'none', color: '#fff' }}
              onClick={handleReply} disabled={submitting || !replyContent.trim()}>등록</Button>
          </div>
        </div>
      )}

      {comment.children?.map((child) => (
        <CommentItem key={child.commentId} comment={child} postId={postId}
          onRefresh={onRefresh} depth={depth + 1} />
      ))}
    </div>
  );
}

export default function CommentSection({ postId }) {
  const { user } = useAuth();
  const [comments, setComments] = useState([]);
  const [newComment, setNewComment] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const fetchComments = useCallback(() => {
    api.get(`/board/posts/${postId}/comments`)
      .then(({ data }) => setComments(data.data || []))
      .catch(() => {});
  }, [postId]);

  useEffect(() => { fetchComments(); }, [fetchComments]);

  const handleSubmit = async () => {
    if (!newComment.trim()) return;
    setSubmitting(true);
    try {
      await api.post(`/board/posts/${postId}/comments`, { content: newComment.trim() });
      setNewComment('');
      fetchComments();
    } catch { /* ignore */ }
    setSubmitting(false);
  };

  return (
    <div className="mt-4">
      <h6 className="fw-bold mb-3 d-flex align-items-center gap-2">
        <ChatDots /> 댓글 ({comments.length})
      </h6>

      {user && (
        <div className="mb-3">
          <Form.Control as="textarea" rows={3} value={newComment}
            onChange={(e) => setNewComment(e.target.value)}
            placeholder="댓글을 입력하세요" />
          <div className="text-end mt-2">
            <Button style={{ background: 'var(--shop-primary)', border: 'none', color: '#fff', borderRadius: '50px', padding: '8px 24px' }}
              onClick={handleSubmit} disabled={submitting || !newComment.trim()}>
              댓글 등록
            </Button>
          </div>
        </div>
      )}

      {comments.length === 0 && (
        <p className="text-muted text-center py-4">등록된 댓글이 없습니다.</p>
      )}

      {comments.map((c) => (
        <CommentItem key={c.commentId} comment={c} postId={postId} onRefresh={fetchComments} />
      ))}
    </div>
  );
}
