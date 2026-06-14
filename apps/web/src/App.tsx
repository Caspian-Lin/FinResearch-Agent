import { ConfigProvider, Layout, Typography, Space, Tag, theme, Alert } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import enUS from 'antd/locale/en_US';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import { LinkOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import type { ReactNode } from 'react';

import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { useLanguage } from '@/i18n/useLanguage';

const { Header, Content, Footer } = Layout;
const { Title, Paragraph, Text } = Typography;

interface AppProps {
  /** Optional page content rendered inside the layout, sharing ConfigProvider. */
  children?: ReactNode;
}

/**
 * Root app component.
 *
 * The Ant Design `ConfigProvider.locale` is bound to the active i18n language
 * so antd's built-in copy (pagination, date pickers, etc.) and date formatting
 * follow the user's language. `dayjs` locale is switched in lockstep so any
 * locale-aware date rendering stays consistent.
 */
function App({ children }: AppProps = {}) {
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

  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

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
          <Tag color="default">{t('dashboard:scaffolding.tag')}</Tag>
          <div style={{ marginLeft: 'auto' }}>
            <LanguageSwitcher />
          </div>
        </Header>

        <Content style={{ padding: '48px 24px' }}>
          <div style={{ maxWidth: 960, margin: '0 auto' }}>
            <Title level={2}>{t('dashboard:welcome.title')}</Title>
            <Paragraph>
              <Text>{t('dashboard:welcome.intro')}</Text>
            </Paragraph>

            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <Paragraph>
                <ul>
                  <li>
                    <Text strong>{t('dashboard:scaffolding.backendApi')}:</Text>{' '}
                    <a href={apiBaseUrl}>
                      {apiBaseUrl}
                    </a>{' '}
                    <LinkOutlined />
                  </li>
                  <li>
                    <Text strong>{t('dashboard:scaffolding.apiDocs')}:</Text>{' '}
                    <a href={`${apiBaseUrl}/docs`}>/docs</a>
                  </li>
                  <li>
                    <Text strong>{t('dashboard:scaffolding.healthProbe')}:</Text>{' '}
                    <a href={`${apiBaseUrl}/health`}>/health</a>
                  </li>
                </ul>
              </Paragraph>

              <Alert
                type="warning"
                showIcon
                message={t('common:disclaimer.title')}
                description={t('common:disclaimer.body')}
              />

              {children}
            </Space>
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
