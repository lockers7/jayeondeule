import { createContext, useContext, useState, useEffect } from 'react';
import api from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const saved = localStorage.getItem('shop_user');
    if (saved) setUser(JSON.parse(saved));
    setLoading(false);
  }, []);

  const login = async (shopUsrId, passwd) => {
    const { data } = await api.post('/auth/login', { shopUsrId, passwd });
    if (data.success) {
      localStorage.setItem('shop_token', data.data.token);
      localStorage.setItem('shop_user', JSON.stringify(data.data.userInfo));
      setUser(data.data.userInfo);
      return data.data.userInfo;
    }
    throw new Error(data.message);
  };

  const register = async (form) => {
    const { data } = await api.post('/auth/register', form);
    if (!data.success) throw new Error(data.message);
    return data;
  };

  const logout = () => {
    localStorage.removeItem('shop_token');
    localStorage.removeItem('shop_user');
    setUser(null);
    window.location.href = '/login';
  };

  const isAdmin = user && (user.usrGrade === 'SYSTEM_ADMIN' || user.usrGrade === 'SHOP_ADMIN');
  const isMonitor = user?.usrGrade === 'MONITOR';
  const canViewAdmin = isAdmin || isMonitor;
  const isSystemAdmin = user?.usrGrade === 'SYSTEM_ADMIN';

  return (
    <AuthContext.Provider value={{ user, login, register, logout, loading, isAdmin, isMonitor, canViewAdmin, isSystemAdmin }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
