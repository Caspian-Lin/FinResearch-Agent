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
import { ConfigProvider, Layout, Typography, Tag, Alert, Button, Dropdown, Menu, Spin } from 'antd';
import { UserOutlined } from '@ant-design/icons';
import zhCN from 'antd/locale/zh_CN';
import enUS from 'antd/locale/en_US';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import { useTranslation } from 'react-i18next';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import type { MenuProps } from 'antd';

import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { ThemeModeSwitch } from '@/components/ThemeModeSwitch';
import { useLanguage } from '@/i18n/useLanguage';
import { setUnauthorizedHandler } from '@/api/client';
import { useAuthStore } from '@/store/auth';
import { ResearchThemeProvider, useResearchTheme } from '@/theme';

const { Header, Content, Footer } = Layout;
const { Title } = Typography;

function AppContent() {
  const { t } = useTranslation();
  const { language } = useLanguage();
  const { antdTheme, palette, mode } = useResearchTheme();
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
    { key: '/backtest', label: t('common:nav.newBacktest') },
    { key: '/backtest/history', label: t('common:nav.backtestHistory') },
    { key: '/factor-research', label: t('common:nav.factorResearch') },
  ];
  const selectedNavKey = location.pathname.startsWith('/backtest/history')
    ? '/backtest/history'
    : location.pathname;

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
    <ConfigProvider locale={antdLocale} theme={antdTheme}>
      {/* flex column + minHeight 100vh: Content (flex:1) fills, Footer sticks
          to the bottom even when page content is short. */}
      <Layout className="app-shell">
        <Header className="app-header">
          <div className="app-brand" onClick={() => navigate('/dashboard')} role="presentation">
            <span className="app-brand-mark">FR</span>
            <span className="app-brand-text">
              <Title level={4} className="app-brand-title">
                {t('common:appName')}
              </Title>
              <span className="app-brand-subtitle">{t('common:tagline')}</span>
            </span>
          </div>
          <Tag className="app-version-tag">{t('common:version')}</Tag>
          <Menu
            theme={mode}
            mode="horizontal"
            selectedKeys={[selectedNavKey]}
            items={navItems}
            className="app-nav"
            onClick={({ key }) => navigate(key)}
          />
          <div className="app-header-actions">
            <ThemeModeSwitch />
            <LanguageSwitcher />

            {status === 'authenticated' && user ? (
              <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
                <Button type="text" className="app-user-button" icon={<UserOutlined />}>
                  {user.email}
                </Button>
              </Dropdown>
            ) : status === 'unauthenticated' ? (
              <Button type="link" onClick={() => navigate('/login')}>
                {t('auth:signIn.submit')}
              </Button>
            ) : (
              <Spin size="small" />
            )}
          </div>
        </Header>

        {/* No maxWidth cap (FRA-24): the dashboard fills the viewport width.
            flex:1 pushes the Footer down to the bottom on short pages. */}
        <Content className="app-content">
          <Outlet />
        </Content>

        {/* The risk disclaimer lives in the Footer so it always sits at the
            bottom of the viewport rather than floating with page content. */}
        <Footer className="app-footer">
          <Alert
            type="warning"
            showIcon
            className="app-disclaimer"
            message={t('common:disclaimer.title')}
            description={t('common:disclaimer.body')}
          />
          <span style={{ color: palette.muted }}>
            {t('common:appName')} · {t('common:tagline')}
          </span>
        </Footer>
      </Layout>
    </ConfigProvider>
  );
}

function App() {
  return (
    <ResearchThemeProvider>
      <AppContent />
    </ResearchThemeProvider>
  );
}

export default App;
