/**
 * Root app layout.
 *
 * App is now a pure layout component rendered as the parent of a React Router
 * `<Route>` tree: it renders the Header (brand + language switcher) and a
 * Content area whose body is `<Outlet/>` (the matched child route), with the
 * project-wide risk disclaimer pinned below the page content. Page-specific
 * content is supplied by routes in `main.tsx`.
 *
 * Ant Design `ConfigProvider.locale` is bound to the active i18n language so
 * antd's built-in copy (pagination, date pickers, Empty, …) follows the user's
 * language, and `dayjs` locale is switched in lockstep so locale-aware date
 * rendering stays consistent.
 */
import { ConfigProvider, Layout, Typography, Tag, theme, Alert } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import enUS from 'antd/locale/en_US';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import { useTranslation } from 'react-i18next';
import { Outlet } from 'react-router-dom';

import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { useLanguage } from '@/i18n/useLanguage';

const { Header, Content, Footer } = Layout;
const { Title } = Typography;

function App() {
  const { t } = useTranslation();
  const { language } = useLanguage();

  const isZh = language === 'zh-CN';

  // Keep antd + dayjs locales in sync with the active language.
  const antdLocale = isZh ? zhCN : enUS;
  if (isZh) {
    dayjs.locale('zh-cn');
  } else {
    dayjs.locale('en');
  }

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
          <div style={{ marginLeft: 'auto' }}>
            <LanguageSwitcher />
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
