/**
 * Root app layout.
 *
 * App is a pure layout component rendered as the parent of a React Router
 * `<Route>` tree: it renders the Header (brand + language switcher + user menu)
 * and a Content area whose body is `<Outlet/>` (the matched child route). The
 * project-wide risk disclaimer is pinned inside the Footer so it always sits at
 * the bottom of the viewport. Page-specific content is supplied by routes in
 * `main.tsx`.
 *
 * Ant Design `ConfigProvider.locale` is bound to the active i18n language so
 * antd's built-in copy (pagination, date pickers, Empty, …) follows the user's
 * language, and `dayjs` locale is switched in lockstep so locale-aware date
 * rendering stays consistent.
 *
 * FRA-17 responsibilities wired here:
 *  - On mount, kick off session refresh recovery (`initialize()` is idempotent).
 *  - Register the global 401 side-effect: when `apiClient` clears an invalid
 *    token it invokes our handler, which logs the user out and redirects to
 *    /login. This avoids a circular import (client → store → client).
 *  - Render the Header user area: authenticated → email dropdown with sign-out;
 *    unauthenticated → "Sign in" button; loading → small spinner placeholder.
 *
 * FRA-24 layout fixes:
 *  - Layout is a flex column (min-height 100vh) with Content flex:1, so the
 *    Footer (with the disclaimer) always sticks to the bottom no matter how
 *    little page content there is.
 *  - Header is position:sticky so it stays visible while scrolling.
 *  - Content no longer caps width at 1100px — the dashboard fills the viewport.
 *  - The body margin reset lives in src/index.css (antd 5's resetCss only
 *    injects when wrapped in its <App> component, which we don't use).
 */
import { useEffect } from 'react';
import {
  ConfigProvider,
  Layout,
  Typography,
  Tag,
  theme,
  Alert,
  Button,
  Dropdown,
  Menu,
  Spin,
} from 'antd';
import { UserOutlined } from '@ant-design/icons';
import zhCN from 'antd/locale/zh_CN';
import enUS from 'antd/locale/en_US';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import { useTranslation } from 'react-i18next';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import type { MenuProps } from 'antd';

import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { useLanguage } from '@/i18n/useLanguage';
import { setUnauthorizedHandler } from '@/api/client';
import { useAuthStore } from '@/store/auth';

const { Header, Content, Footer } = Layout;
const { Title } = Typography;

function App() {
  const { t } = useTranslation();
  const { language } = useLanguage();
  const navigate = useNavigate();
  const location = useLocation();
  const status = useAuthStore((s) => s.status);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  const isZh = language === 'zh-CN';

  // Keep antd + dayjs locales in sync with the active language.
  const antdLocale = isZh ? zhCN : enUS;
  if (isZh) {
    dayjs.locale('zh-cn');
  } else {
    dayjs.locale('en');
  }

  // Kick off session refresh recovery once on mount. Idempotent: a no-op when
  // already authenticated or when there is no token.
  useEffect(() => {
    void useAuthStore.getState().initialize();
  }, []);

  // Register the global 401 side-effect: apiClient clears the token, then calls
  // this handler to log the user out and bounce to /login. Re-registered only
  // when `navigate` changes (stable for the app lifetime).
  useEffect(() => {
    setUnauthorizedHandler(() => {
      useAuthStore.getState().logout();
      navigate('/login', { replace: true });
    });
    return () => {
      setUnauthorizedHandler(null);
    };
  }, [navigate]);

  const navItems: MenuProps['items'] = [
    { key: '/dashboard', label: t('common:nav.dashboard') },
    { key: '/watchlist', label: t('common:nav.watchlist') },
    { key: '/backtest', label: t('common:nav.backtests') },
  ];

  const userMenuItems: MenuProps['items'] = [
    {
      key: 'signOut',
      label: t('auth:userMenu.signOut'),
      onClick: () => {
        logout();
        navigate('/login', { replace: true });
      },
    },
  ];

  return (
    <ConfigProvider
      locale={antdLocale}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 6,
        },
      }}
    >
      {/* flex column + minHeight 100vh: Content (flex:1) fills, Footer sticks
          to the bottom even when page content is short. */}
      <Layout style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
        <Header
          style={{
            position: 'sticky',
            top: 0,
            zIndex: 10,
            display: 'flex',
            alignItems: 'center',
            background: '#001529',
            color: '#fff',
          }}
        >
          <Title level={4} style={{ color: '#fff', margin: 0, marginRight: 16 }}>
            {t('common:appName')}
          </Title>
          <Tag color="blue">{t('common:version')}</Tag>
          <Menu
            theme="dark"
            mode="horizontal"
            selectedKeys={[location.pathname]}
            items={navItems}
            style={{ minWidth: 200, marginLeft: 8, background: 'transparent' }}
            onClick={({ key }) => navigate(key)}
          />
          <div
            style={{
              marginLeft: 'auto',
              display: 'flex',
              alignItems: 'center',
              gap: 12,
            }}
          >
            <LanguageSwitcher />

            {status === 'authenticated' && user ? (
              <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
                <Button type="text" style={{ color: '#fff' }} icon={<UserOutlined />}>
                  {user.email}
                </Button>
              </Dropdown>
            ) : status === 'unauthenticated' ? (
              <Button type="link" style={{ color: '#fff' }} onClick={() => navigate('/login')}>
                {t('auth:signIn.submit')}
              </Button>
            ) : (
              <Spin size="small" />
            )}
          </div>
        </Header>

        {/* No maxWidth cap (FRA-24): the dashboard fills the viewport width.
            flex:1 pushes the Footer down to the bottom on short pages. */}
        <Content style={{ flex: 1, padding: '24px 32px' }}>
          <Outlet />
        </Content>

        {/* The risk disclaimer lives in the Footer so it always sits at the
            bottom of the viewport rather than floating with page content. */}
        <Footer style={{ textAlign: 'center', color: '#888' }}>
          <Alert
            type="warning"
            showIcon
            style={{ textAlign: 'left', marginBottom: 12 }}
            message={t('common:disclaimer.title')}
            description={t('common:disclaimer.body')}
          />
          {t('common:appName')} · {t('common:tagline')}
        </Footer>
      </Layout>
    </ConfigProvider>
  );
}

export default App;
