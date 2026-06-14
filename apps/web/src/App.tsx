/**
 * Root app layout.
 *
 * App is a pure layout component rendered as the parent of a React Router
 * `<Route>` tree: it renders the Header (brand + language switcher + user menu)
 * and a Content area whose body is `<Outlet/>` (the matched child route), with
 * the project-wide risk disclaimer pinned below the page content. Page-specific
 * content is supplied by routes in `main.tsx`.
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
 */
import { useEffect } from 'react';
import { ConfigProvider, Layout, Typography, Tag, theme, Alert, Button, Dropdown, Spin } from 'antd';
import { UserOutlined } from '@ant-design/icons';
import zhCN from 'antd/locale/zh_CN';
import enUS from 'antd/locale/en_US';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import { useTranslation } from 'react-i18next';
import { Outlet, useNavigate } from 'react-router-dom';
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
      <Layout style={{ minHeight: '100vh' }}>
        <Header
          style={{
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

        <Content style={{ padding: '48px 24px' }}>
          <div style={{ maxWidth: 1100, margin: '0 auto' }}>
            <Outlet />

            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 32 }}
              message={t('common:disclaimer.title')}
              description={t('common:disclaimer.body')}
            />
          </div>
        </Content>

        <Footer style={{ textAlign: 'center', color: '#888' }}>
          {t('common:appName')} · {t('common:tagline')}
        </Footer>
      </Layout>
    </ConfigProvider>
  );
}

export default App;
