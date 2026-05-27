import { useState, useEffect } from 'react';
import { Container, Table, Button, Badge } from 'react-bootstrap';
import { useNavigate } from 'react-router-dom';
import { PencilSquare, CheckCircleFill } from 'react-bootstrap-icons';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { formatDate } from '../../utils/format';

export default function InquiryListPage() {
  const navigate = useNavigate();
  const { user, isAdmin } = useAuth();
  const [posts, setPosts] = useState([]);

  const loadPosts = () => {
    if (!user) return;
    const endpoint = isAdmin ? '/board/posts' : '/board/posts/my';
    api.get(endpoint, { params: { boardType: 'INQUIRY' } })
      .then(({ data }) => setPosts(data.data || []))
      .catch(() => {});
  };

  useEffect(() => { loadPosts(); }, [user, isAdmin]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleResolve = async (e, postId, currentResolve) => {
    e.stopPropagation();
    try {
      await api.patch(`/board/posts/${postId}/resolve`, { resolve: currentResolve !== 'Y' });
      loadPosts();
    } catch { /* ignore */ }
  };

  if (!user) {
    return (
      <>
        <div className="page-header">
          <Container>
            <h1 className="page-header-title">문의 게시판</h1>
            <p className="page-header-desc">로그인 후 이용하실 수 있습니다</p>
          </Container>
        </div>
        <section className="shop-section text-center">
          <Container>
            <Button style={{ background: 'var(--shop-accent)', border: 'none', borderRadius: '50px', padding: '12px 36px' }}
              onClick={() => navigate('/login')}>
              로그인
            </Button>
          </Container>
        </section>
      </>
    );
  }

  return (
    <>
      <div className="page-header">
        <Container>
          <h1 className="page-header-title">문의 게시판</h1>
          <p className="page-header-desc">상품에 대한 궁금한 점을 문의하세요</p>
        </Container>
      </div>

      <section className="shop-section">
        <Container>
          {!isAdmin && (
            <div className="text-end mb-3">
              <Button style={{ background: 'var(--shop-accent)', border: 'none', borderRadius: '50px', padding: '10px 28px' }}
                onClick={() => navigate('/inquiry/write')}>
                <PencilSquare className="me-2" /> 문의하기
              </Button>
            </div>
          )}

          {posts.length === 0 ? (
            <p className="text-center text-muted py-5">등록된 문의가 없습니다.</p>
          ) : (
            <Table hover responsive style={{ borderRadius: '12px', overflow: 'hidden', border: '2px solid #90A4AE' }}>
              <thead style={{ background: 'var(--shop-bg-warm)' }}>
                <tr>
                  <th style={{ width: '6%' }}>번호</th>
                  <th>문의 제목</th>
                  <th style={{ width: '14%' }}>관련 상품</th>
                  <th style={{ width: '12%' }}>작성자</th>
                  <th style={{ width: '12%' }}>작성일</th>
                  <th style={{ width: '8%' }}>상태</th>
                  {isAdmin && <th style={{ width: '8%' }}>처리</th>}
                </tr>
              </thead>
              <tbody>
                {posts.map((post, idx) => (
                  <tr key={post.postId} style={{ cursor: 'pointer' }}
                    onClick={() => navigate(`/inquiry/${post.postId}`)}>
                    <td className="text-center">{posts.length - idx}</td>
                    <td>{post.title}</td>
                    <td className="text-center" style={{ fontSize: '0.85rem' }}>
                      {post.productName || '-'}
                    </td>
                    <td className="text-center">{post.writerName}</td>
                    <td className="text-center">{formatDate(post.rgstDt)}</td>
                    <td className="text-center">
                      {post.resolveYn === 'Y' ? (
                        <Badge bg="success" pill><CheckCircleFill size={10} className="me-1" />완료</Badge>
                      ) : post.commentCount > 0 ? (
                        <Badge bg="info" pill>답변완료</Badge>
                      ) : (
                        <Badge bg="warning" text="dark" pill>대기중</Badge>
                      )}
                    </td>
                    {isAdmin && (
                      <td className="text-center">
                        <Button size="sm"
                          variant={post.resolveYn === 'Y' ? 'outline-secondary' : 'outline-success'}
                          style={{ borderRadius: '50px', padding: '3px 14px', fontSize: '0.8rem' }}
                          onClick={(e) => toggleResolve(e, post.postId, post.resolveYn)}>
                          {post.resolveYn === 'Y' ? '미완료' : '완료'}
                        </Button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Container>
      </section>
    </>
  );
}
