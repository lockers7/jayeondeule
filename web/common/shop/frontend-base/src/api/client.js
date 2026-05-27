import axios from 'axios';

const api = axios.create({ baseURL: '/api/shop' });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('shop_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('shop_token');
      localStorage.removeItem('shop_user');
      window.location.href = '/login';
    }
    return Promise.reject(err);
  }
);

export default api;
