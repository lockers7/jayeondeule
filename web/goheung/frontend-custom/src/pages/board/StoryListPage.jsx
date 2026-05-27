import { useState, useEffect } from 'react';
import { Container, Table, Button } from 'react-bootstrap';
import { useNavigate } from 'react-router-dom';
import { PencilSquare, Eye, ChatDots } from 'react-bootstrap-icons';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { formatDate } from '../../utils/format';

export default function StoryListPage() {
  const navigate = useNavigate();
  const { isAdmin } = useAuth();
  const [posts, setPosts] = useState([]);

  useEffect(() => {
    api.get('/board/posts', { params: { boardType: 'STORY' } })
      .then(({ data }) => setPosts(data.data || []))
      .catch(() => {});
  }, []);

  return (
    <>
      <div className="page-header">
        <Container>
          <h1 className="page-header-title">농장 이야기</h1>
          <p className="page-header-desc">고흥뜰에 농장의 소식과 이야기를 전합니다</p>
        </Container>
      </div>
      <section className="shop-section">
        <Container>
          {isAdmin && (
            <div className="text-end mb-3">
              <Button style={{ background: 'var(--shop-primary)', border: 'none', borderRadius: '50px', padding: '10px 28px' }}
                onClick={() => navigate('/story/write')}>
                <PencilSquare className="me-2" /> 글쓰기
              </Button>
            </div>
          )}
          {posts.length === 0 ? (
            <p className="text-center text-muted py-5">등록된 글이 없습니다.</p>
          ) : (
            <Table hover responsive style={{ borderRadius: '12px', overflow: 'hidden', border: '2px solid #90A4AE' }}>
              <thead style={{ background: 'var(--shop-bg-warm)' }}>
                <tr>
                  <th style={{ width: '6%' }}>번호</th>
                  <th>제목</th>
                  <th style={{ width: '12%' }}>작성자</th>
                  <th style={{ width: '12%' }}>작성일</th>
                  <th style={{ width: '8%' }}>조회</th>
                </tr>
              </thead>
              <tbody>
                {posts.map((post, idx) => (
                  <tr key={post.postId} style={{ cursor: 'pointer' }}
                    onClick={() => navigate(`/story/${post.postId}`)}>
                    <td className="text-center">{posts.length - idx}</td>
                    <td>
                      {post.title}
                      {post.commentCount > 0 && (
                        <span className="ms-2" style={{ color: 'var(--shop-accent)', fontSize: '0.85rem' }}>
                          <ChatDots size={12} className="me-1" />{post.commentCount}
                        </span>
                      )}
                    </td>
                    <td className="text-center">{post.writerName}</td>
                    <td className="text-center">{formatDate(post.rgstDt)}</td>
                    <td className="text-center"><Eye size={13} className="me-1" />{post.viewCount}</td>
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
