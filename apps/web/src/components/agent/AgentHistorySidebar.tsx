/**
 * AgentHistorySidebar — list of past agent runs for the current user.
 *
 * Mirrors the pattern of `BacktestHistorySidebar`: a scrollable list of
 * run summaries, each showing the research question (truncated), a status
 * badge, and the creation timestamp. Clicking opens the run detail in the
 * main panel. The "New Research" button returns to the composer view.
 */
import { useTranslation } from 'react-i18next';
import { Button, Empty, List, Spin, Tag, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';

import type { AgentRunSummary } from '@/types/api';

const { Text } = Typography;

function statusColor(status: string): string {
  switch (status) {
    case 'succeeded':
      return 'success';
    case 'failed':
      return 'error';
    case 'running':
      return 'processing';
    case 'queued':
      return 'warning';
    case 'canceled':
      return 'default';
    default:
      return 'default';
  }
}

interface AgentHistorySidebarProps {
  runs: AgentRunSummary[];
  loading: boolean;
  selectedRunId: string | null;
  onOpenRun: (runId: string) => void;
  onNewRun: () => void;
}

function AgentHistorySidebar({
  runs,
  loading,
  selectedRunId,
  onOpenRun,
  onNewRun,
}: AgentHistorySidebarProps) {
  const { t } = useTranslation('agent');

  return (
    <div className="agent-history-sidebar">
      <div className="agent-history-header">
        <Text strong>{t('history.title')}</Text>
        <Button type="primary" size="small" icon={<PlusOutlined />} onClick={onNewRun}>
          {t('history.newRun')}
        </Button>
      </div>

      {loading && (
        <div className="agent-history-loading">
          <Spin size="small" />
        </div>
      )}

      {!loading && runs.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t('history.empty')}
          className="agent-history-empty"
        />
      ) : (
        <List
          dataSource={runs}
          renderItem={(run) => (
            <List.Item
              key={run.id}
              onClick={() => onOpenRun(run.id)}
              className={`agent-history-item ${selectedRunId === run.id ? 'agent-history-item-active' : ''}`}
            >
              <div className="agent-history-item-content">
                <div className="agent-history-item-row">
                  <Tag color={statusColor(run.status)} className="agent-history-status">
                    {t(`run.${run.status}`, run.status)}
                  </Tag>
                  <Text type="secondary" className="agent-history-date">
                    {dayjs(run.created_at).format('MM-DD HH:mm')}
                  </Text>
                </div>
                <Text className="agent-history-question" ellipsis>
                  {run.research_question}
                </Text>
              </div>
            </List.Item>
          )}
        />
      )}
    </div>
  );
}

export { AgentHistorySidebar };
export type { AgentHistorySidebarProps };
export { AgentHistorySidebar as default };
