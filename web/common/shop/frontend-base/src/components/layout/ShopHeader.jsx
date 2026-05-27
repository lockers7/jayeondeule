import { useState, useEffect, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Container, Navbar, Nav } from 'react-bootstrap';
import { useAuth } from '../../context/AuthContext';

export default function ShopHeader() {
  const location = useLocation();
  const [scrolled, setScrolled] = useState(false);
  const { user, canViewAdmin, isSystemAdmin, logout } = useAuth();
  const scrollRef = useRef(null);
  const [showLeft, setShowLeft] = useState(false);
  const [showRight, setShowRight] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 50);
    window.addEventListener('scroll', onScroll);
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // 모바일 메뉴 스크롤 화살표 표시 여부 감지
  const checkArrows = () => {
    const el = scrollRef.current;
    if (!el) return;
    setShowLeft(el.scrollLeft > 10);
    setShowRight(el.scrollLeft < el.scrollWidth - el.clientWidth - 10);
  };

  useEffect(() => {
    checkArrows();
    window.addEventListener('resize', checkArrows);
    return () => window.removeEventListener('resize', checkArrows);
  }, []);

  const scrollMenu = (dir) => {
    const el = scrollRef.current;
    if (el) el.scrollBy({ left: dir * 150, behavior: 'smooth' });
  };

  const navItems = [
    { path: '/', label: '홈' },
    { path: '/farm', label: '농장 소개(실시간)' },
    { path: '/house', label: '재배사 소개(실시간)' },
    { path: '/story', label: '농장 이야기' },
    { path: '/efficacy', label: '효능효과' },
    { path: '/products', label: '상품' },
    { path: '/inquiry', label: '문의 게시판' },
    { path: '/lotto', label: '로또놀이' },
  ];

  const authItems = user ? [
    ...(canViewAdmin ? [{ path: '/admin', label: '관리자', accent: true }] : []),
    { path: '/mypage', label: `${user.usrName}님` },
  ] : [
    { path: '/login', label: '로그인', accent: true },
  ];

  return (
    <>
      {/* 데스크톱 헤더 (lg 이상) */}
      <Navbar
        expand="lg"
        fixed="top"
        className={`shop-navbar d-none d-lg-block ${scrolled ? 'scrolled' : ''}`}
      >
        <Container>
          <div className="d-flex align-items-center w-100">
            <Navbar.Brand as={Link} to="/">
              자연들<span>에</span>
            </Navbar.Brand>
            {isSystemAdmin && (
              <a href="#" onClick={(e) => { e.preventDefault(); window.open('https://lockers7.iptime.org', 'farm_window'); }}
                style={{ fontSize: '0.8rem', marginRight: '16px', color: 'var(--shop-accent)', textDecoration: 'none', fontWeight: 600, cursor: 'pointer' }}
                title="농장관리 시스템">
                🌾 농장관리
              </a>
            )}
            <Nav className="ms-auto">
              {navItems.map(({ path, label }) => (
                <Nav.Link key={path} as={Link} to={path}
                  className={location.pathname === path ? 'active' : ''}>
                  {label}
                </Nav.Link>
              ))}
              {authItems.map(({ path, label, accent }) => (
                <Nav.Link key={path} as={Link} to={path}
                  className={location.pathname === path ? 'active' : ''}
                  style={accent ? { color: 'var(--shop-accent)', fontWeight: 600 } : undefined}>
                  {label}
                </Nav.Link>
              ))}
              {user && (
                <Nav.Link onClick={logout} style={{ cursor: 'pointer' }}>로그아웃</Nav.Link>
              )}
            </Nav>
          </div>
        </Container>
      </Navbar>

      {/* 모바일 헤더 (lg 미만) */}
      <div className={`mobile-header d-lg-none ${scrolled ? 'scrolled' : ''}`}>
        {/* 상단: 브랜드 + 인증 */}
        <div className="mobile-header-top">
          <Link to="/" className="mobile-brand">자연들<span>에</span></Link>
          <div className="mobile-auth">
            {isSystemAdmin && (
              <a href="#" onClick={(e) => { e.preventDefault(); window.open('https://lockers7.iptime.org', 'farm_window'); }}
                className="mobile-auth-link" title="농장관리">🌾</a>
            )}
            {authItems.map(({ path, label, accent }) => (
              <Link key={path} to={path}
                className={`mobile-auth-link ${accent ? 'accent' : ''} ${location.pathname === path ? 'active' : ''}`}>
                {label}
              </Link>
            ))}
            {user && (
              <span onClick={logout} className="mobile-auth-link" style={{ cursor: 'pointer' }}>로그아웃</span>
            )}
          </div>
        </div>

        {/* 하단: 좌우 스크롤 메뉴 */}
        <div className="mobile-menu-wrap">
          {showLeft && (
            <button className="mobile-menu-arrow left" onClick={() => scrollMenu(-1)} aria-label="왼쪽 스크롤">‹</button>
          )}
          <div className="mobile-menu-scroll" ref={scrollRef} onScroll={checkArrows}>
            {navItems.map(({ path, label }) => (
              <Link key={path} to={path}
                className={`mobile-menu-item ${location.pathname === path || (path !== '/' && location.pathname.startsWith(path)) ? 'active' : ''}`}>
                {label}
              </Link>
            ))}
          </div>
          {showRight && (
            <button className="mobile-menu-arrow right" onClick={() => scrollMenu(1)} aria-label="오른쪽 스크롤">›</button>
          )}
        </div>
      </div>
    </>
  );
}
