import { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Container, Navbar, Nav } from 'react-bootstrap';
import { useAuth } from '../../context/AuthContext';

export default function ShopHeader() {
  const location = useLocation();
  const [scrolled, setScrolled] = useState(false);
  const { user, canViewAdmin, isSystemAdmin, logout } = useAuth();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 50);
    window.addEventListener('scroll', onScroll);
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const navItems = [
    { path: '/', label: '홈' },
    { path: '/farm', label: '농장 소개' },
    { path: '/house', label: '재배사 소개' },
    { path: '/efficacy', label: '효능효과' },
    { path: '/products', label: '상품' },
  ];

  return (
    <Navbar
      expand="lg"
      fixed="top"
      className={`shop-navbar ${scrolled ? 'scrolled' : ''}`}
    >
      <Container>
        <Navbar.Brand as={Link} to="/">
          자연들<span>에</span>
        </Navbar.Brand>
        {isSystemAdmin && (
          <a href="https://lockers7.iptime.org" target="_blank" rel="noreferrer"
            style={{ fontSize: '0.8rem', marginRight: '16px', color: 'var(--shop-accent)', textDecoration: 'none', fontWeight: 600 }}
            title="농장관리 시스템">
            🌾 농장관리
          </a>
        )}
        <Navbar.Toggle aria-controls="shop-nav" />
        <Navbar.Collapse id="shop-nav">
          <Nav className="ms-auto">
            {navItems.map(({ path, label }) => (
              <Nav.Link
                key={path}
                as={Link}
                to={path}
                className={location.pathname === path ? 'active' : ''}
              >
                {label}
              </Nav.Link>
            ))}
            {user ? (
              <>
                {canViewAdmin && (
                  <Nav.Link as={Link} to="/admin"
                    className={location.pathname === '/admin' ? 'active' : ''}
                    style={{ color: 'var(--shop-accent)' }}>
                    관리자
                  </Nav.Link>
                )}
                <Nav.Link as={Link} to="/mypage"
                  className={location.pathname === '/mypage' ? 'active' : ''}>
                  {user.usrName}님
                </Nav.Link>
                <Nav.Link onClick={logout} style={{ cursor: 'pointer' }}>로그아웃</Nav.Link>
              </>
            ) : (
              <Nav.Link as={Link} to="/login"
                className={location.pathname === '/login' ? 'active' : ''}
                style={{ color: 'var(--shop-accent)', fontWeight: 600 }}>
                로그인
              </Nav.Link>
            )}
          </Nav>
        </Navbar.Collapse>
      </Container>
    </Navbar>
  );
}
