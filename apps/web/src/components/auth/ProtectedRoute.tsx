/**
 * Route guard for authenticated pages (FRA-17).
 *
 * Rendered as a layout route element (renders `<Outlet/>`) so it can wrap a
 * group of protected routes in `main.tsx`. Behavior is driven entirely by the
 * auth store's `status`:
 *
 *  - `'loading'`         → full-screen spinner (refresh recovery in flight;
 *                           avoids a login-page flash for a valid token).
 *  - `'unauthenticated'` → `<Navigate to="/login">` carrying `state.from` so
 *                           LoginPage can return the user where they came from.
 *  - `'authenticated'`   → render the child route via `<Outlet/>`.
 */
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { Spin } from 'antd';
import { useTranslation } from 'react-i18next';

import { useAuthStore } from '@/store/auth';

export function ProtectedRoute() {
  const status = useAuthStore((s) => s.status);
  const location = useLocation();
  const { t } = useTranslation();

  if (status === 'loading') {
    return (
      <div
        style={{
          minHeight: '60vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Spin tip={t('auth:loading')} size="large">
          <div style={{ height: 48 }} />
        </Spin>
      </div>
    );
  }

  if (status === 'unauthenticated') {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}

export default ProtectedRoute;
