import { useState, useEffect, useCallback } from 'react';
import { Container, Row, Col, Table, Badge, Button, Form, Modal } from 'react-bootstrap';
import { CheckCircleFill, Eye, ChatDots, ArrowLeft, PersonFill, CalendarEvent, Trash, Reply, ImageFill } from 'react-bootstrap-icons';
import { useAuth } from '../../context/AuthContext';
import api from '../../api/client';
import { formatDate, formatDateTime, formatCurrency, isVideo } from '../../utils/format';

const statusMap = {
  ORDERED: { label: '주문접수', color: 'secondary', next: 'PAID', nextLabel: '입금확인' },
  PAID: { label: '입금확인', color: 'info', next: 'PREPARING', nextLabel: '상품준비' },
  PREPARING: { label: '상품준비', color: 'primary', next: 'SHIPPED', nextLabel: '발송' },
  SHIPPED: { label: '발송완료', color: 'success', next: 'DELIVERED', nextLabel: '배송완료' },
  DELIVERED: { label: '배송완료', color: 'dark' },
  RECEIVED: { label: '거래완료', color: 'secondary' },
  CANCELLED: { label: '취소', color: 'danger' },
};

function AdminCommentItem({ comment, depth, onReply, onDelete }) {
  const maxIndent = 4;
  return (
    <div style={{ marginLeft: Math.min(depth, maxIndent) * 20, marginTop: depth > 0 ? 6 : 12 }}>
      <div style={{
        padding: '10px 14px', borderRadius: '8px',
        background: depth > 0 ? '#f8fffe' : '#fff',
        border: '1px solid var(--shop-border)',
      }}>
        <div className="d-flex justify-content-between align-items-center mb-1">
          <div className="d-flex align-items-center gap-2">
            <PersonFill size={13} style={{ color: 'var(--shop-primary)' }} />
            <strong style={{ fontSize: '0.88rem' }}>{comment.writerName}</strong>
            <span style={{ fontSize: '0.76rem', color: 'var(--shop-text-light)' }}>
              {formatDateTime(comment.rgstDt)}
            </span>
          </div>
          <div className="d-flex gap-2">
            <Button variant="link" size="sm" className="p-0 text-muted" onClick={() => onReply(comment)} title="답글">
              <Reply size={14} />
            </Button>
            <Button variant="link" size="sm" className="p-0 text-danger" onClick={() => onDelete(comment.commentId)} title="삭제">
              <Trash size={12} />
            </Button>
          </div>
        </div>
        <p className="mb-0" style={{ fontSize: '0.9rem', whiteSpace: 'pre-wrap' }}>{comment.content}</p>
        {comment.images?.length > 0 && (
          <div className="d-flex gap-2 mt-2 flex-wrap">
            {comment.images.map((img, i) => (
              isVideo(img.imageUrl) ? (
                <video key={i} controls style={{ maxWidth: '200px', borderRadius: '6px' }}><source src={img.imageUrl} /></video>
              ) : (
                <img key={i} src={img.imageUrl} alt="" style={{ maxWidth: '200px', maxHeight: '120px', borderRadius: '6px', objectFit: 'cover' }} />
              )
            ))}
          </div>
        )}
      </div>
      {comment.children?.map(child => (
        <AdminCommentItem key={child.commentId} comment={child} depth={depth + 1}
          onReply={onReply} onDelete={onDelete} />
      ))}
    </div>
  );
}

export default function AdminPage() {
  const { isAdmin } = useAuth();
  const [tab, setTab] = useState('dashboard');
  const [stats, setStats] = useState({});
  const [orders, setOrders] = useState([]);
  const [orderFilter, setOrderFilter] = useState('ALL');
  const [products, setProducts] = useState([]);
  const [members, setMembers] = useState([]);
  const [showProduct, setShowProduct] = useState(false);
  const [editProduct, setEditProduct] = useState(null);
  // 문의관리
  const [inquiryFilter, setInquiryFilter] = useState('ALL');
  const [inquiries, setInquiries] = useState([]);
  const [selectedInquiry, setSelectedInquiry] = useState(null);
  const [inquiryComments, setInquiryComments] = useState([]);
  const [inquiryImages, setInquiryImages] = useState([]);
  const [replyContent, setReplyContent] = useState('');
  const [replyTarget, setReplyTarget] = useState(null);

  const loadDashboard = async () => { const { data } = await api.get('/admin/dashboard'); if (data.success) setStats(data.data); };
  const loadOrders = async () => { const { data } = await api.get('/admin/orders'); if (data.success) setOrders(data.data); };
  const loadProducts = async () => { const { data } = await api.get('/admin/products'); if (data.success) setProducts(data.data); };
  const loadMembers = async () => { const { data } = await api.get('/admin/members'); if (data.success) setMembers(data.data); };
  const loadInquiries = useCallback(async () => {
    const { data } = await api.get('/board/posts', { params: { boardType: 'INQUIRY' } });
    if (data.success) setInquiries(data.data || []);
  }, []);

  const loadInquiryDetail = useCallback(async (postId) => {
    const [postRes, commentsRes, imagesRes] = await Promise.all([
      api.get(`/board/posts/${postId}`),
      api.get(`/board/posts/${postId}/comments`),
      api.get(`/board/posts/${postId}/images`),
    ]);
    setSelectedInquiry(postRes.data.data);
    setInquiryComments(commentsRes.data.data || []);
    setInquiryImages(imagesRes.data.data || []);
  }, []);

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect */
    if (tab === 'dashboard') loadDashboard();
    if (tab === 'orders') loadOrders();
    if (tab === 'products') loadProducts();
    if (tab === 'members') loadMembers();
    if (tab === 'inquiries') { loadInquiries(); setSelectedInquiry(null); }
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [tab, loadInquiries]);

  const updateStatus = async (orderId, status) => {
    await api.patch(`/admin/orders/${orderId}/status`, { status });
    loadOrders();
    loadDashboard();
  };

  const [productImageFile, setProductImageFile] = useState(null);

  const saveProduct = async () => {
    let pid = editProduct.productId;
    if (pid) {
      await api.put(`/admin/products/${pid}`, editProduct);
    } else {
      const { data } = await api.post('/admin/products', { ...editProduct, farmId: 1 });
      pid = data.data?.productId;
    }
    // 이미지 업로드
    if (productImageFile && pid) {
      const formData = new FormData();
      formData.append('file', productImageFile);
      await api.post(`/admin/products/${pid}/image`, formData, { headers: { 'Content-Type': 'multipart/form-data' } });
    }
    setShowProduct(false);
    setProductImageFile(null);
    loadProducts();
  };

  const fmt = formatCurrency;
  const fmtDate = formatDate;

  return (
    <>
      <div className="page-header">
        <Container><h1 className="page-header-title">관리자</h1></Container>
      </div>
      <section className="shop-section">
        <Container>
          <Row>
            <Col lg={2}>
              <div className="efficacy-nav">
                <div style={{ padding: '12px 16px', fontWeight: 700, color: 'var(--shop-primary)' }}>관리메뉴</div>
                {['dashboard', 'orders', 'products', 'inquiries', 'members'].map(t => (
                  <button key={t} className={`efficacy-nav-item ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
                    {{ dashboard: '대시보드', orders: '주문관리', products: '상품관리', inquiries: '문의관리', members: '회원관리' }[t]}
                  </button>
                ))}
              </div>
            </Col>
            <Col lg={10}>
              {/* 대시보드 */}
              {tab === 'dashboard' && (
                <div className="efficacy-card">
                  <h3>대시보드</h3>
                  <div className="efficacy-stat-grid">
                    <div className="efficacy-stat-item" style={{cursor:'pointer'}} onClick={() => { setOrderFilter('PAID'); setTab('orders'); }}><div className="efficacy-stat-number">{stats.paidOrders || 0}</div><div className="efficacy-stat-label">입금확인</div></div>
                    <div className="efficacy-stat-item" style={{cursor:'pointer'}} onClick={() => { setOrderFilter('PREPARING'); setTab('orders'); }}><div className="efficacy-stat-number">{stats.preparingOrders || 0}</div><div className="efficacy-stat-label">상품준비</div></div>
                    <div className="efficacy-stat-item" style={{cursor:'pointer'}} onClick={() => { setOrderFilter('SHIPPED'); setTab('orders'); }}><div className="efficacy-stat-number">{stats.shippedOrders || 0}</div><div className="efficacy-stat-label">발송완료</div></div>
                    <div className="efficacy-stat-item" style={{cursor:'pointer'}} onClick={() => { setOrderFilter('RECEIVED'); setTab('orders'); }}><div className="efficacy-stat-number">{stats.receivedOrders || 0}</div><div className="efficacy-stat-label">거래완료</div></div>
                    <div className="efficacy-stat-item" style={{cursor:'pointer'}} onClick={() => { setOrderFilter('CANCELLED'); setTab('orders'); }}><div className="efficacy-stat-number">{stats.cancelledOrders || 0}</div><div className="efficacy-stat-label">취소/반품</div></div>
                    <div className="efficacy-stat-item" style={{cursor:'pointer'}} onClick={() => { setOrderFilter('ALL'); setTab('orders'); }}><div className="efficacy-stat-number">{fmt(stats.totalRevenue)}</div><div className="efficacy-stat-label">총 매출</div></div>
                    <div className="efficacy-stat-item" style={{cursor:'pointer'}} onClick={() => setTab('members')}><div className="efficacy-stat-number">{stats.totalMembers || 0}</div><div className="efficacy-stat-label">일반 회원수</div></div>
                    <div className="efficacy-stat-item" style={{ cursor:'pointer', border: (stats.pendingInquiries || 0) > 0 ? '2px solid var(--shop-accent)' : undefined }} onClick={() => setTab('inquiries')}>
                      <div className="efficacy-stat-number" style={{ color: (stats.pendingInquiries || 0) > 0 ? 'var(--shop-accent)' : undefined }}>
                        {stats.pendingInquiries || 0}/{stats.totalInquiries || 0}
                      </div>
                      <div className="efficacy-stat-label">문의 (미완료/전체)</div>
                    </div>
                  </div>
                </div>
              )}

              {/* 주문관리 */}
              {tab === 'orders' && (() => {
                const filtered = orderFilter === 'ALL' ? orders : orders.filter(o => o.orderStatus === orderFilter);
                return (
                <div className="efficacy-card">
                  <h3>주문 관리</h3>
                  <Table responsive hover size="sm">
                    <thead><tr>
                      <th style={{whiteSpace:'nowrap'}}>주문번호</th>
                      <th style={{whiteSpace:'nowrap'}}>주문자</th>
                      <th>상품</th>
                      <th className="text-end" style={{whiteSpace:'nowrap'}}>금액</th>
                      <th style={{whiteSpace:'nowrap'}}>주문일</th>
                      <th style={{whiteSpace:'nowrap'}}>
                        <Form.Select size="sm" value={orderFilter} onChange={(e) => setOrderFilter(e.target.value)}
                          style={{width:'auto', display:'inline-block', fontSize:'0.82rem', padding:'2px 28px 2px 8px', fontWeight:600}}>
                          <option value="ALL">전체</option>
                          <option value="ORDERED">주문접수</option>
                          <option value="PAID">입금확인</option>
                          <option value="PREPARING">상품준비</option>
                          <option value="SHIPPED">발송완료</option>
                          <option value="DELIVERED">배송완료</option>
                          <option value="RECEIVED">거래완료</option>
                          <option value="CANCELLED">취소</option>
                        </Form.Select>
                      </th>
                      <th style={{whiteSpace:'nowrap'}}>관리</th>
                    </tr></thead>
                    <tbody>
                      {filtered.map(o => (
                        <tr key={o.orderId}>
                          <td><small>{o.orderId}</small></td>
                          <td>{o.receiverName}<br/><small className="text-muted">{o.receiverPhone}</small></td>
                          <td>{o.items?.map(i => `${i.productName} x${i.quantity}`).join(', ')}</td>
                          <td className="text-end"><strong>{fmt(o.totalAmount)}</strong></td>
                          <td className="text-center" style={{whiteSpace:'nowrap'}}>{fmtDate(o.orderDt)}</td>
                          <td className="text-center"><Badge bg={statusMap[o.orderStatus]?.color}>{statusMap[o.orderStatus]?.label}</Badge></td>
                          <td className="text-center" style={{whiteSpace:'nowrap'}}>
                            {isAdmin && statusMap[o.orderStatus]?.next && (
                              <Button size="sm" variant="outline-primary"
                                onClick={() => updateStatus(o.orderId, statusMap[o.orderStatus].next)}>
                                {statusMap[o.orderStatus].nextLabel}
                              </Button>
                            )}
                            {isAdmin && o.orderStatus !== 'CANCELLED' && o.orderStatus !== 'RECEIVED' && o.orderStatus !== 'DELIVERED' && (
                              <Button size="sm" variant="outline-danger" className="ms-1"
                                onClick={() => updateStatus(o.orderId, 'CANCELLED')}>취소</Button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                  {filtered.length === 0 && <p className="text-center text-muted py-4">해당 상태의 주문이 없습니다.</p>}
                </div>
                );
              })()}

              {/* 상품관리 */}
              {tab === 'products' && (
                <div className="efficacy-card">
                  <div className="d-flex justify-content-between align-items-center mb-3">
                    <h3 className="mb-0" style={{ border: 'none', padding: 0 }}>상품 관리</h3>
                    {isAdmin && (
                      <Button className="btn-shop-primary" onClick={() => { setEditProduct({ farmId: 1, price: 0, stockQty: 0, saleStatus: 'ON_SALE', unit: '100g', sortOrder: 0 }); setShowProduct(true); }}>
                        상품 추가
                      </Button>
                    )}
                  </div>
                  <Table responsive hover size="sm">
                    <thead><tr><th className="text-end" style={{whiteSpace:'nowrap'}}>ID</th><th>상품명</th><th className="text-end" style={{whiteSpace:'nowrap'}}>가격</th><th className="text-end" style={{whiteSpace:'nowrap'}}>판매중</th><th className="text-end" style={{whiteSpace:'nowrap'}}>판매완료</th><th className="text-end" style={{whiteSpace:'nowrap'}}>현재재고</th><th style={{whiteSpace:'nowrap'}}>상태</th><th className="text-end" style={{whiteSpace:'nowrap'}}>조회수</th><th style={{whiteSpace:'nowrap'}}>관리</th></tr></thead>
                    <tbody>
                      {products.map(p => (
                        <tr key={p.productId}>
                          <td className="text-end">{p.productId}</td>
                          <td>{p.productName}</td>
                          <td className="text-end">{fmt(p.price)}</td>
                          <td className="text-end" style={{color:'var(--shop-accent)', fontWeight:600}}>{p.sellingQty || 0}</td>
                          <td className="text-end" style={{color:'var(--shop-primary)', fontWeight:600}}>{p.soldQty || 0}</td>
                          <td className="text-end">{p.stockQty}</td>
                          <td className="text-center"><Badge bg={p.saleStatus === 'ON_SALE' ? 'success' : p.saleStatus === 'SOLD_OUT' ? 'warning' : 'secondary'}>
                            {p.saleStatus === 'ON_SALE' ? '판매중' : p.saleStatus === 'SOLD_OUT' ? '품절' : '중지'}
                          </Badge></td>
                          <td className="text-end">{p.viewCount}</td>
                          <td className="text-center">{isAdmin && <Button size="sm" variant="outline-primary" onClick={() => { setEditProduct({ ...p }); setShowProduct(true); }}>수정</Button>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </div>
              )}

              {/* 회원관리 */}
              {tab === 'members' && (
                <div className="efficacy-card">
                  <h3>회원 관리</h3>
                  <Table responsive hover size="sm">
                    <thead><tr><th style={{whiteSpace:'nowrap'}}>아이디</th><th style={{whiteSpace:'nowrap'}}>이름</th><th style={{whiteSpace:'nowrap'}}>등급</th><th style={{whiteSpace:'nowrap'}}>연락처</th><th>이메일</th><th style={{whiteSpace:'nowrap'}}>가입일</th></tr></thead>
                    <tbody>
                      {members.map(m => (
                        <tr key={m.shopUsrId}>
                          <td>{m.shopUsrId}</td>
                          <td>{m.usrName}</td>
                          <td className="text-center"><Badge bg={m.usrGrade === 'SYSTEM_ADMIN' ? 'danger' : m.usrGrade === 'SHOP_ADMIN' ? 'primary' : 'secondary'}>
                            {m.usrGrade === 'SYSTEM_ADMIN' ? '시스템관리자' : m.usrGrade === 'SHOP_ADMIN' ? '쇼핑몰관리자' : '일반회원'}
                          </Badge></td>
                          <td>{m.phone || '-'}</td>
                          <td>{m.email || '-'}</td>
                          <td className="text-center" style={{whiteSpace:'nowrap'}}>{fmtDate(m.rgstDt)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </div>
              )}
              {/* 문의관리 */}
              {tab === 'inquiries' && !selectedInquiry && (() => {
                const filteredInq = inquiryFilter === 'ALL' ? inquiries
                  : inquiryFilter === 'PENDING' ? inquiries.filter(i => i.resolveYn !== 'Y')
                  : inquiries.filter(i => i.resolveYn === 'Y');
                return (
                <div className="efficacy-card">
                  <h3>문의 관리</h3>
                  {inquiries.length === 0 ? (
                    <p className="text-center text-muted py-4">등록된 문의가 없습니다.</p>
                  ) : (
                    <Table responsive hover size="sm">
                      <thead>
                        <tr style={{whiteSpace:'nowrap'}}>
                          <th style={{width:'4%'}}>번호</th>
                          <th style={{width:'30%'}}>제목</th>
                          <th style={{width:'13%'}}>상품</th>
                          <th style={{width:'8%'}}>작성자</th>
                          <th style={{width:'10%'}}>작성일</th>
                          <th style={{width:'5%'}}>조회</th>
                          <th style={{width:'10%'}}>
                            <Form.Select size="sm" value={inquiryFilter} onChange={(e) => setInquiryFilter(e.target.value)}
                              style={{width:'auto', display:'inline-block', fontSize:'0.82rem', padding:'2px 28px 2px 8px', fontWeight:600}}>
                              <option value="ALL">전체</option>
                              <option value="PENDING">미완료</option>
                              <option value="DONE">완료</option>
                            </Form.Select>
                          </th>
                          <th style={{width:'7%'}}>처리</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredInq.map((inq, idx) => (
                          <tr key={inq.postId}>
                            <td className="text-center">{filteredInq.length - idx}</td>
                            <td style={{cursor:'pointer'}} onClick={() => loadInquiryDetail(inq.postId)}>
                              <div style={{color:'var(--shop-primary)', fontWeight:500,
                                overflow:'hidden', textOverflow:'ellipsis', display:'-webkit-box', WebkitLineClamp:2, WebkitBoxOrient:'vertical'}}>
                                {inq.title}
                                {inq.commentCount > 0 && (
                                  <span className="ms-2" style={{color:'var(--shop-accent)', fontSize:'0.82rem'}}>
                                    <ChatDots size={11} className="me-1"/>{inq.commentCount}
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className="text-center">
                              <div style={{fontSize:'0.83rem', overflow:'hidden', textOverflow:'ellipsis',
                                display:'-webkit-box', WebkitLineClamp:2, WebkitBoxOrient:'vertical'}}>{inq.productName || '-'}</div>
                            </td>
                            <td className="text-center">{inq.writerName}</td>
                            <td className="text-center" style={{whiteSpace:'nowrap'}}>{fmtDate(inq.rgstDt)}</td>
                            <td className="text-center"><Eye size={12}/> {inq.viewCount}</td>
                            <td className="text-center">
                              {inq.resolveYn === 'Y' ? (
                                <Badge bg="success" pill><CheckCircleFill size={9} className="me-1"/>완료</Badge>
                              ) : inq.commentCount > 0 ? (
                                <Badge bg="info" pill>답변완료</Badge>
                              ) : (
                                <Badge bg="warning" text="dark" pill>대기중</Badge>
                              )}
                            </td>
                            <td className="text-center">
                              <Button size="sm"
                                variant={inq.resolveYn === 'Y' ? 'outline-secondary' : 'outline-success'}
                                style={{borderRadius:'6px', padding:'3px 12px', fontSize:'0.78rem', whiteSpace:'nowrap'}}
                                onClick={async () => {
                                  await api.patch(`/board/posts/${inq.postId}/resolve`, { resolve: inq.resolveYn !== 'Y' });
                                  loadInquiries();
                                  loadDashboard();
                                }}>
                                {inq.resolveYn === 'Y' ? '미완료' : '완료'}
                              </Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  )}
                </div>
                );
              })()}

              {/* 문의 상세 */}
              {tab === 'inquiries' && selectedInquiry && (
                <div>
                  <Button variant="link" className="mb-2 p-0 text-muted" onClick={() => setSelectedInquiry(null)}>
                    <ArrowLeft className="me-1"/> 목록으로
                  </Button>
                  <div className="efficacy-card">
                    <div className="d-flex justify-content-between align-items-start mb-2">
                      <h3 style={{borderBottom:'none', paddingBottom:0, marginBottom:0, flex:1}}>
                        {selectedInquiry.title}
                      </h3>
                      <div className="d-flex gap-2">
                        <Button size="sm"
                          variant={selectedInquiry.resolveYn === 'Y' ? 'outline-secondary' : 'success'}
                          style={{borderRadius:'50px', padding:'5px 16px', fontSize:'0.85rem'}}
                          onClick={async () => {
                            await api.patch(`/board/posts/${selectedInquiry.postId}/resolve`, { resolve: selectedInquiry.resolveYn !== 'Y' });
                            loadInquiryDetail(selectedInquiry.postId);
                            loadInquiries();
                            loadDashboard();
                          }}>
                          <CheckCircleFill size={12} className="me-1"/>
                          {selectedInquiry.resolveYn === 'Y' ? '완료 해제' : '완료 처리'}
                        </Button>
                        <Button size="sm" variant="outline-danger"
                          style={{borderRadius:'50px', padding:'5px 16px', fontSize:'0.85rem'}}
                          onClick={async () => {
                            if (!window.confirm('문의를 삭제하시겠습니까?')) return;
                            await api.delete(`/board/posts/${selectedInquiry.postId}`);
                            setSelectedInquiry(null);
                            loadInquiries();
                            loadDashboard();
                          }}>
                          <Trash size={12} className="me-1"/> 삭제
                        </Button>
                      </div>
                    </div>
                    <div className="d-flex gap-3 mb-3" style={{fontSize:'0.85rem', color:'var(--shop-text-light)'}}>
                      <span><PersonFill size={13} className="me-1"/>{selectedInquiry.writerName}</span>
                      <span><CalendarEvent size={13} className="me-1"/>{fmtDate(selectedInquiry.rgstDt)}</span>
                      <span><Eye size={13} className="me-1"/>{selectedInquiry.viewCount}</span>
                      {selectedInquiry.productName && <Badge bg="info">{selectedInquiry.productName}</Badge>}
                    </div>
                    {inquiryImages.length > 0 && (
                      <div className="mb-3">
                        {inquiryImages.map((img, i) => (
                          isVideo(img.imageUrl) ? (
                            <video key={i} controls style={{width:'100%', aspectRatio:'16/9', borderRadius:'10px', marginBottom:'8px', background:'#000', objectFit:'contain'}}>
                              <source src={img.imageUrl}/></video>
                          ) : (
                            <img key={i} src={img.imageUrl} alt="" style={{maxWidth:'100%', borderRadius:'10px', marginBottom:'8px'}}/>
                          )
                        ))}
                      </div>
                    )}
                    <div style={{fontSize:'0.95rem', lineHeight:1.9, whiteSpace:'pre-wrap'}}>{selectedInquiry.content}</div>
                  </div>

                  {/* 답변/댓글 */}
                  <div className="efficacy-card mt-3">
                    <h4 style={{fontSize:'1.1rem', fontWeight:600, marginBottom:'16px'}}>
                      <ChatDots className="me-2"/>답변/댓글 ({inquiryComments.length})
                    </h4>

                    {/* 답변 작성 */}
                    <div className="mb-3 p-3" style={{background:'var(--shop-bg-warm)', borderRadius:'10px'}}>
                      <Form.Control as="textarea" rows={3} value={replyContent}
                        onChange={(e) => setReplyContent(e.target.value)}
                        placeholder={replyTarget ? '대댓글을 입력하세요' : '답변을 입력하세요'}/>
                      <div className="d-flex justify-content-between align-items-center mt-2">
                        <span style={{fontSize:'0.82rem', color:'var(--shop-text-light)'}}>
                          {replyTarget ? `↳ ${replyTarget.writerName}님에게 답글` : ''}
                        </span>
                        <div className="d-flex gap-2">
                          {replyTarget && (
                            <Button size="sm" variant="outline-secondary" style={{borderRadius:'50px', padding:'4px 16px'}}
                              onClick={() => setReplyTarget(null)}>취소</Button>
                          )}
                          <Button size="sm" style={{background:'var(--shop-primary)', border:'none', color:'#fff', borderRadius:'50px', padding:'4px 20px'}}
                            disabled={!replyContent.trim()}
                            onClick={async () => {
                              await api.post(`/board/posts/${selectedInquiry.postId}/comments`, {
                                content: replyContent.trim(),
                                parentId: replyTarget?.commentId || null,
                              });
                              setReplyContent('');
                              setReplyTarget(null);
                              loadInquiryDetail(selectedInquiry.postId);
                              loadInquiries();
                            }}>
                            등록
                          </Button>
                        </div>
                      </div>
                    </div>

                    {inquiryComments.length === 0 && (
                      <p className="text-muted text-center py-3">등록된 답변이 없습니다.</p>
                    )}

                    {/* 댓글 트리 렌더링 */}
                    {inquiryComments.map(c => (
                      <AdminCommentItem key={c.commentId} comment={c} depth={0}
                        onReply={(c) => setReplyTarget(c)}
                        onDelete={async (id) => {
                          if (!window.confirm('댓글을 삭제하시겠습니까?')) return;
                          await api.delete(`/board/comments/${id}`);
                          loadInquiryDetail(selectedInquiry.postId);
                          loadInquiries();
                        }}/>
                    ))}
                  </div>
                </div>
              )}
            </Col>
          </Row>
        </Container>
      </section>

      {/* 상품 편집 모달 */}
      <Modal show={showProduct} onHide={() => setShowProduct(false)} size="lg">
        <Modal.Header closeButton><Modal.Title>{editProduct?.productId ? '상품 수정' : '상품 추가'}</Modal.Title></Modal.Header>
        <Modal.Body>
          {editProduct && (
            <Form>
              <Row>
                <Col md={8}><Form.Group className="mb-3"><Form.Label>상품명</Form.Label>
                  <Form.Control value={editProduct.productName || ''} onChange={e => setEditProduct({ ...editProduct, productName: e.target.value })} /></Form.Group></Col>
                <Col md={4}><Form.Group className="mb-3"><Form.Label>단위</Form.Label>
                  <Form.Control value={editProduct.unit || ''} onChange={e => setEditProduct({ ...editProduct, unit: e.target.value })} /></Form.Group></Col>
              </Row>
              <Form.Group className="mb-3"><Form.Label>부제목</Form.Label>
                <Form.Control value={editProduct.subtitle || ''} onChange={e => setEditProduct({ ...editProduct, subtitle: e.target.value })} /></Form.Group>
              <Row>
                <Col md={4}><Form.Group className="mb-3"><Form.Label>가격</Form.Label>
                  <Form.Control type="number" value={editProduct.price || 0} onChange={e => setEditProduct({ ...editProduct, price: parseInt(e.target.value) })} /></Form.Group></Col>
                <Col md={4}><Form.Group className="mb-3"><Form.Label>재고수량</Form.Label>
                  <Form.Control type="number" value={editProduct.stockQty || 0} onChange={e => setEditProduct({ ...editProduct, stockQty: parseInt(e.target.value) })} /></Form.Group></Col>
                <Col md={4}><Form.Group className="mb-3"><Form.Label>판매상태</Form.Label>
                  <Form.Select value={editProduct.saleStatus} onChange={e => setEditProduct({ ...editProduct, saleStatus: e.target.value })}>
                    <option value="ON_SALE">판매중</option><option value="SOLD_OUT">품절</option><option value="STOPPED">판매중지</option>
                  </Form.Select></Form.Group></Col>
              </Row>
              <Form.Group className="mb-3"><Form.Label>상품설명</Form.Label>
                <Form.Control as="textarea" rows={3} value={editProduct.description || ''} onChange={e => setEditProduct({ ...editProduct, description: e.target.value })} /></Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>상품 이미지</Form.Label>
                <div className="d-flex align-items-start gap-3">
                  {(productImageFile || editProduct.imageUrl) && (
                    <img src={productImageFile ? URL.createObjectURL(productImageFile) : editProduct.imageUrl}
                      alt="상품 미리보기" style={{ width: '120px', height: '120px', objectFit: 'cover', borderRadius: '10px', border: '2px solid #90A4AE' }} />
                  )}
                  <div>
                    <Form.Control type="file" accept="image/*" onChange={e => setProductImageFile(e.target.files?.[0] || null)} />
                    <small className="text-muted">이미지 변경 시 새 파일을 선택하세요</small>
                  </div>
                </div>
              </Form.Group>
            </Form>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowProduct(false)}>닫기</Button>
          <Button className="btn-shop-primary" onClick={saveProduct}>저장</Button>
        </Modal.Footer>
      </Modal>
    </>
  );
}
