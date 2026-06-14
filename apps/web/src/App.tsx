import { Layout, Typography, Space, Tag } from 'antd';
import { LinkOutlined } from '@ant-design/icons';

const { Header, Content, Footer } = Layout;
const { Title, Paragraph, Text } = Typography;

function App() {
  return (
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
          FinResearch Agent
        </Title>
        <Tag color="blue">v0.1.0</Tag>
        <Tag color="default">Week 1 scaffold</Tag>
      </Header>

      <Content style={{ padding: '48px 24px' }}>
        <div style={{ maxWidth: 960, margin: '0 auto' }}>
          <Title level={2}>Welcome to FinResearch Agent</Title>
          <Paragraph>
            <Text>
              This is a scaffold shell. Real dashboard pages (watchlists, OHLCV
              viewer, data quality, backtests, memos) will be added in
              subsequent commits per the Week 1 roadmap.
            </Text>
          </Paragraph>

          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Paragraph>
              <ul>
                <li>
                  <Text strong>Backend API:</Text>{' '}
                  <a href={import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'}>
                    {import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'}
                  </a>{' '}
                  <LinkOutlined />
                </li>
                <li>
                  <Text strong>API docs (OpenAPI):</Text>{' '}
                  <a href={`${import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'}/docs`}>
                    /docs
                  </a>
                </li>
                <li>
                  <Text strong>Health probe:</Text>{' '}
                  <a href={`${import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'}/health`}>
                    /health
                  </a>
                </li>
              </ul>
            </Paragraph>
          </Space>
        </div>
      </Content>

      <Footer style={{ textAlign: 'center', color: '#888' }}>
        FinResearch Agent · LLM-powered Financial Research and Backtesting System
      </Footer>
    </Layout>
  );
}

export default App;
