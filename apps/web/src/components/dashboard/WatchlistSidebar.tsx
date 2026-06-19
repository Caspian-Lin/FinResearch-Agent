/**
 * Dashboard sidebar — pick an asset from a watchlist without leaving the page.
 *
 * Pure-presentational: the watchlist data and the active-watchlist choice are
 * owned by `DashboardPage` (lifted) so the desktop `Sider` and the narrow-screen
 * `Drawer` share a single `useWatchlists` call and one selection state. Picking
 * an asset calls `onPick`; DashboardPage routes that to
 * `useSelectionStore.setSelectedAsset`, and the main area re-fetches on the
 * store change — no prop drilling.
 *
 * The Menu `theme` follows the active mode (FRA-45) so the active-item highlight
 * stays legible in dark mode — same reason App's header Menu binds `theme={mode}`.
 * Menu `key` is `asset_id` (matches WatchlistPage's table `rowKey`); `selectedKeys`
 * is the current asset id, giving a free active highlight with no custom state.
 */
import { Alert, Empty, Menu, Spin, Typography } from 'antd';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { ToggleSelect } from '@/components/ui/ToggleSelect';
import type { ApiError } from '@/api/client';
import { useResearchTheme } from '@/theme';
import type { WatchlistItemRead, WatchlistRead } from '@/types/api';

const { Text } = Typography;

export interface WatchlistSidebarProps {
  watchlists: WatchlistRead[];
  loading: boolean;
  error: ApiError | null;
  selectedWatchlistId: string | null;
  onSelectWatchlist: (id: string) => void;
  selectedAssetId: string | null;
  onPick: (item: WatchlistItemRead) => void;
}

export function WatchlistSidebar({
  watchlists,
  loading,
  error,
  selectedWatchlistId,
  onSelectWatchlist,
  selectedAssetId,
  onPick,
}: WatchlistSidebarProps) {
  const { t } = useTranslation(['dashboard', 'errors']);
  const { mode } = useResearchTheme();

  const items = watchlists.find((w) => w.watchlist_id === selectedWatchlistId)?.items ?? [];

  return (
    <div className="watchlist-sidebar">
      <Text strong className="sidebar-title">
        {t('dashboard:sidebar.title')}
      </Text>
      <ToggleSelect
        ariaLabel={t('dashboard:sidebar.switch')}
        value={selectedWatchlistId}
        onChange={onSelectWatchlist}
        options={watchlists.map((w) => ({ value: w.watchlist_id, label: w.name }))}
        loading={loading}
        placeholder={t('dashboard:sidebar.switch')}
        width="100%"
      />
      <div className="sidebar-list">
        {loading ? (
          <Spin />
        ) : error ? (
          <Alert type="error" showIcon message={t(`errors:${error.code}`)} />
        ) : items.length === 0 ? (
          <Empty description={t('dashboard:sidebar.empty.assets')} />
        ) : (
          <Menu
            mode="vertical"
            theme={mode}
            selectedKeys={selectedAssetId ? [selectedAssetId] : []}
            items={items.map((it) => ({
              key: it.asset_id,
              label: (
                <div className="sidebar-item">
                  <span className="sidebar-item-symbol">{it.symbol}</span>
                  <span className="sidebar-item-name">{it.name}</span>
                </div>
              ),
              onClick: () => onPick(it),
            }))}
          />
        )}
      </div>
      <Link to="/watchlist" className="sidebar-manage-link">
        {t('dashboard:sidebar.manage')}
      </Link>
    </div>
  );
}

export default WatchlistSidebar;
