/**
 * WatchlistManagerSidebar — the watchlist page's left sidebar (FRA-45).
 *
 * Manages watchlists: list them, switch the active one, create a new list,
 * delete the active list, and open the add-asset modal. Pure-presentational;
 * the page owns `useWatchlists`, `selectedWatchlistId`, and all modal state.
 *
 * Distinct from the dashboard's `WatchlistSidebar`: that one picks an asset
 * (→ useSelectionStore); this one manages watchlists. Different data flow and
 * actions, hence a separate component (reusing would need prop-bag conditionals
 * that obscure intent).
 */
import { Alert, Button, Empty, Menu, Popconfirm, Space, Spin, Typography } from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';

import type { ApiError } from '@/api/client';
import { useResearchTheme } from '@/theme';
import type { WatchlistRead } from '@/types/api';

const { Text } = Typography;

export interface WatchlistManagerSidebarProps {
  watchlists: WatchlistRead[];
  loading: boolean;
  error: ApiError | null;
  selectedWatchlistId: string | null;
  onSelectWatchlist: (id: string) => void;
  /** Opens the create-watchlist modal (page owns modal state). */
  onCreateClick: () => void;
  /** Delete the given watchlist (wrapped in a Popconfirm here). */
  onDeleteWatchlist: (id: string) => void;
  /** Opens the add-asset modal (page owns modal state). */
  onAddAssetClick: () => void;
}

export function WatchlistManagerSidebar({
  watchlists,
  loading,
  error,
  selectedWatchlistId,
  onSelectWatchlist,
  onCreateClick,
  onDeleteWatchlist,
  onAddAssetClick,
}: WatchlistManagerSidebarProps) {
  const { t } = useTranslation(['watchlist', 'errors']);
  const { mode } = useResearchTheme();

  const selected = watchlists.find((w) => w.watchlist_id === selectedWatchlistId) ?? null;

  return (
    <div className="watchlist-sidebar">
      <Text strong className="sidebar-title">
        {t('watchlist:sidebar.title')}
      </Text>

      <Space direction="vertical" style={{ width: '100%' }}>
        <Button block type="primary" icon={<PlusOutlined />} onClick={onCreateClick}>
          {t('watchlist:create.button')}
        </Button>
        {selected && (
          <Popconfirm
            title={t('watchlist:delete.confirm', { name: selected.name })}
            onConfirm={() => onDeleteWatchlist(selected.watchlist_id)}
          >
            <Button block icon={<DeleteOutlined />} className="danger-outline-button">
              {t('watchlist:delete.button')}
            </Button>
          </Popconfirm>
        )}
        <Button block icon={<PlusOutlined />} onClick={onAddAssetClick} disabled={!selected}>
          {t('watchlist:addAsset.button')}
        </Button>
      </Space>

      <div className="sidebar-list">
        {loading ? (
          <Spin />
        ) : error ? (
          <Alert type="error" showIcon message={t(`errors:${error.code}`)} />
        ) : watchlists.length === 0 ? (
          <Empty description={t('watchlist:empty.watchlists')} />
        ) : (
          <Menu
            mode="vertical"
            theme={mode}
            selectedKeys={selectedWatchlistId ? [selectedWatchlistId] : []}
            items={watchlists.map((w) => ({
              key: w.watchlist_id,
              label: w.name,
              onClick: () => onSelectWatchlist(w.watchlist_id),
            }))}
          />
        )}
      </div>

      <Text type="secondary" className="sidebar-manage">
        {t('watchlist:sidebar.hint')}
      </Text>
    </div>
  );
}

export default WatchlistManagerSidebar;
