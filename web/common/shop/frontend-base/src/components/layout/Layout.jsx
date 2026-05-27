import { Outlet } from 'react-router-dom';
import ShopHeader from './ShopHeader';
import ShopFooter from './ShopFooter';

export default function Layout() {
  return (
    <>
      <ShopHeader />
      <main>
        <Outlet />
      </main>
      <ShopFooter />
    </>
  );
}
