import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import Layout from './components/layout/Layout';
import HomePage from './pages/HomePage';
import FarmIntroPage from './pages/FarmIntroPage';
import HouseIntroPage from './pages/HouseIntroPage';
import EfficacyPage from './pages/EfficacyPage';
import ProductListPage from './pages/ProductListPage';
import ProductDetailPage from './pages/ProductDetailPage';
import OrderPage from './pages/OrderPage';
import OrderCompletePage from './pages/OrderCompletePage';
import LoginPage from './pages/auth/LoginPage';
import RegisterPage from './pages/auth/RegisterPage';
import MyPage from './pages/member/MyPage';
import AdminPage from './pages/admin/AdminPage';
import StoryListPage from './pages/board/StoryListPage';
import StoryDetailPage from './pages/board/StoryDetailPage';
import StoryWritePage from './pages/board/StoryWritePage';
import InquiryListPage from './pages/board/InquiryListPage';
import InquiryDetailPage from './pages/board/InquiryDetailPage';
import InquiryWritePage from './pages/board/InquiryWritePage';
import LottoPage from './pages/LottoPage';

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<HomePage />} />
            <Route path="/farm" element={<FarmIntroPage />} />
            <Route path="/story" element={<StoryListPage />} />
            <Route path="/story/write" element={<StoryWritePage />} />
            <Route path="/story/edit/:postId" element={<StoryWritePage />} />
            <Route path="/story/:postId" element={<StoryDetailPage />} />
            <Route path="/house" element={<HouseIntroPage />} />
            <Route path="/efficacy" element={<EfficacyPage />} />
            <Route path="/products" element={<ProductListPage />} />
            <Route path="/products/:productId" element={<ProductDetailPage />} />
            <Route path="/order/:productId" element={<OrderPage />} />
            <Route path="/order-complete" element={<OrderCompletePage />} />
            <Route path="/inquiry" element={<InquiryListPage />} />
            <Route path="/inquiry/write" element={<InquiryWritePage />} />
            <Route path="/inquiry/:postId" element={<InquiryDetailPage />} />
            <Route path="/lotto" element={<LottoPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/mypage" element={<MyPage />} />
            <Route path="/admin" element={<AdminPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
