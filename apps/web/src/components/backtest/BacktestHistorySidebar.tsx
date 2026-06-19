/**
 * BacktestHistorySidebar — the backtest page's left sidebar (FRA-45).
 *
 * Lists recent backtest runs (click → open in main) plus a "new run" button
 * that scrolls to the config form. Pure-presentational; the page owns
 * `history`, `detail`, and `handleOpenHistory` (this just calls back).
 *
 * Reuses the generic `.watchlist-sidebar` / `.sidebar-*` classes (same shell as
 * the dashboard + watchlist sidebars) so all three sidebars look identical.
 */
import { Button, Empty, Menu, Spin, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';

import { useResearchTheme } from '@/theme';
import type { BacktestRunRead } from '@/types/api';

const { Text } = Typography;

export interface BacktestHistorySidebarProps {
  history: BacktestRunRead[];
  loading: boolean;
  /** id of the run currently open in the main area (for highlight), or null. */
  selectedRunId: string | null;
  onOpenRun: (runId: string) => void;
  /** Scroll/focus the config form to start a new run. */
  onNewRun: () => void;
}

export function BacktestHistorySidebar({
  history,
  loading,
  selectedRunId,
  onOpenRun,
  onNewRun,
}: BacktestHistorySidebarProps) {
  const { t } = useTranslation();
  const { mode } = useResearchTheme();

  return (
    <div className="watchlist-sidebar">
      <Text strong className="sidebar-title">
        {t('backtest:history.title')}
      </Text>

      <Button block type="primary" icon={<PlusOutlined />} onClick={onNewRun}>
        {t('backtest:run.new')}
      </Button>

      <div className="sidebar-list">
        {loading ? (
          <Spin />
        ) : history.length === 0 ? (
          <Empty description={t('backtest:history.empty')} />
        ) : (
          <Menu
            mode="vertical"
            theme={mode}
            selectedKeys={selectedRunId ? [selectedRunId] : []}
            items={history.map((r) => ({
              key: r.id,
              label: (
                <div className="sidebar-item">
                  <span className="sidebar-item-symbol">{r.name}</span>
                  <span className="sidebar-item-name">
                    {t(`backtest:status.${r.status}`, { defaultValue: r.status })}
                    {' · '}
                    {dayjs(r.created_at).format('YYYY-MM-DD')}
                  </span>
                </div>
              ),
              onClick: () => onOpenRun(r.id),
            }))}
          />
        )}
      </div>
    </div>
  );
}

export default BacktestHistorySidebar;
