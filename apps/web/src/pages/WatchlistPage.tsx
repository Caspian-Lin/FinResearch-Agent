/**
 * Watchlist page (FRA-16).
 *
 * Multi-watchlist management:
 *  - switch between watchlists (Select)
 *  - create / delete a watchlist (modal + Popconfirm)
 *  - list a watchlist's assets in a Table (React key = asset_id, never symbol)
 *  - search + add an asset (disambiguate by asset_id when a symbol matches
 *    across exchanges)
 *  - remove an asset
 *  - hand an asset off to the (FRA-11) dashboard via the selection store
 *
 * Error handling keys off the stable `ApiError.code` and maps it to a
 * translated message via `t('errors:<code>')` — the backend `detail` is never
 * shown to the user.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';
import {
  Alert,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Radio,
  Space,
  Spin,
  Table,
  Typography,
  message,
} from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { RadioChangeEvent } from 'antd';

import { searchAssets } from '@/api/assets';
import { ApiError } from '@/api/client';
import { SiderLayout } from '@/components/layout/SiderLayout';
import { WatchlistManagerSidebar } from '@/components/watchlist/WatchlistManagerSidebar';
import { useWatchlists } from '@/hooks/useWatchlists';
import { useSelectionStore } from '@/store/selection';
import type { AssetRead, WatchlistItemRead } from '@/types/api';

const { Title, Text } = Typography;

/** Map an ApiError code to a stable i18n key under the `errors` namespace. */
function errorMessageKey(code: string): string {
  // Conflict on watchlist create maps to the more specific duplicate-name copy.
  if (code === 'conflict') return 'errors:watchlistNameExists';
  return `errors:${code}`;
}

/**
 * Wrap an async handler for props that expect a sync void callback
 * (onConfirm / onOk / onClick). Rejections are swallowed because every
 * wrapped handler already surfaces errors via `messageApi` / field errors.
 */
function run(task: () => Promise<unknown>): () => void {
  return () => {
    void task();
  };
}

function WatchlistPage() {
  const { t } = useTranslation(['watchlist', 'errors', 'common']);
  const [messageApi, messageContext] = message.useMessage();
  const navigate = useNavigate();

  const { watchlists, loading, error, clearError, refresh, create, remove, addAsset, removeAsset } =
    useWatchlists();

  const [selectedWatchlistId, setSelectedWatchlistId] = useState<string | null>(null);

  // Default-select the first watchlist once the list resolves; clear when empty.
  useEffect(() => {
    const exists = watchlists.some((w) => w.watchlist_id === selectedWatchlistId);
    if (watchlists.length > 0 && !exists) {
      setSelectedWatchlistId(watchlists[0].watchlist_id);
    } else if (watchlists.length === 0) {
      setSelectedWatchlistId(null);
    }
  }, [watchlists, selectedWatchlistId]);

  const selectedWatchlist = useMemo(
    () => watchlists.find((w) => w.watchlist_id === selectedWatchlistId) ?? null,
    [watchlists, selectedWatchlistId],
  );

  // --- Create-watchlist modal -------------------------------------------------
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm<{ name: string }>();
  const [creating, setCreating] = useState(false);

  async function handleCreate() {
    setCreating(true);
    try {
      const values = await createForm.validateFields();
      const created = await create(values.name.trim());
      setCreateOpen(false);
      createForm.resetFields();
      setSelectedWatchlistId(created.watchlist_id);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === 'conflict') {
          // Show as an inline field error so the user can rename and retry.
          createForm.setFields([{ name: 'name', errors: [t('errors:watchlistNameExists')] }]);
        } else {
          messageApi.error(t(errorMessageKey(err.code)));
        }
      }
      // validateFields rejects with field-error info when required is missing;
      // antd already shows those, nothing more to do.
    } finally {
      setCreating(false);
    }
  }

  // --- Delete watchlist -------------------------------------------------------
  async function handleDeleteWatchlist(watchlistId: string) {
    try {
      await remove(watchlistId);
    } catch (err) {
      if (err instanceof ApiError) {
        messageApi.error(t(errorMessageKey(err.code)));
      }
    }
  }

  // --- Add-asset modal --------------------------------------------------------
  const [addOpen, setAddOpen] = useState(false);
  const [searching, setSearching] = useState(false);
  const [adding, setAdding] = useState(false);
  const [searchResults, setSearchResults] = useState<AssetRead[]>([]);
  const [searchDone, setSearchDone] = useState(false);
  const [pickedAssetId, setPickedAssetId] = useState<string | null>(null);
  const [addForm] = Form.useForm<{ symbol: string; exchange: string }>();

  function openAddModal() {
    addForm.resetFields();
    setSearchResults([]);
    setSearchDone(false);
    setPickedAssetId(null);
    setAddOpen(true);
  }

  async function handleSearch() {
    try {
      const values = await addForm.validateFields();
      const symbol = values.symbol.trim();
      if (!symbol) return;
      setSearching(true);
      setPickedAssetId(null);
      try {
        const items = await searchAssets({
          symbol,
          exchange: values.exchange?.trim() || undefined,
        });
        setSearchResults(items);
        setSearchDone(true);
      } catch (err) {
        if (err instanceof ApiError) {
          messageApi.error(t(errorMessageKey(err.code)));
        }
        setSearchResults([]);
        setSearchDone(false);
      } finally {
        setSearching(false);
      }
    } catch {
      // required-symbol validation error — antd shows it.
    }
  }

  async function handleAddAsset() {
    if (!selectedWatchlistId || !pickedAssetId) return;
    setAdding(true);
    try {
      await addAsset(selectedWatchlistId, pickedAssetId);
      setAddOpen(false);
    } catch (err) {
      if (err instanceof ApiError) {
        messageApi.error(t(errorMessageKey(err.code)));
      }
    } finally {
      setAdding(false);
    }
  }

  // --- Remove asset -----------------------------------------------------------
  async function handleRemoveAsset(assetId: string) {
    if (!selectedWatchlistId) return;
    try {
      await removeAsset(selectedWatchlistId, assetId);
    } catch (err) {
      if (err instanceof ApiError) {
        messageApi.error(t(errorMessageKey(err.code)));
      }
    }
  }

  // --- Dashboard hand-off -----------------------------------------------------
  const setSelectedAsset = useSelectionStore((s) => s.setSelectedAsset);

  function handleViewInDashboard(item: WatchlistItemRead) {
    setSelectedAsset({
      asset_id: item.asset_id,
      symbol: item.symbol,
      exchange: item.exchange,
      name: item.name,
    });
    messageApi.success(t('watchlist:selectForDashboard', { symbol: item.symbol }));
    navigate('/dashboard');
  }

  // --- Table columns ----------------------------------------------------------
  const columns: ColumnsType<WatchlistItemRead> = [
    {
      title: t('watchlist:columns.symbol'),
      dataIndex: 'symbol',
      key: 'symbol',
    },
    {
      title: t('watchlist:columns.exchange'),
      dataIndex: 'exchange',
      key: 'exchange',
    },
    {
      title: t('watchlist:columns.name'),
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: t('watchlist:columns.addedAt'),
      dataIndex: 'added_at',
      key: 'added_at',
      render: (value: string) => (value ? dayjs(value).format('LL') : ''),
    },
    {
      title: t('watchlist:columns.actions'),
      key: 'actions',
      render: (_, record) => (
        <Space className="table-action-group">
          <Button
            size="small"
            className="secondary-action-button"
            onClick={() => handleViewInDashboard(record)}
          >
            {t('watchlist:viewInDashboard')}
          </Button>
          <Popconfirm
            title={t('watchlist:remove.confirm')}
            onConfirm={run(() => handleRemoveAsset(record.asset_id))}
          >
            <Button size="small" icon={<DeleteOutlined />} className="danger-outline-button">
              {t('watchlist:remove.button')}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <SiderLayout
      sidebar={
        <WatchlistManagerSidebar
          watchlists={watchlists}
          loading={loading}
          error={null}
          selectedWatchlistId={selectedWatchlistId}
          onSelectWatchlist={setSelectedWatchlistId}
          onCreateClick={() => setCreateOpen(true)}
          onDeleteWatchlist={(id) => void handleDeleteWatchlist(id)}
          onAddAssetClick={openAddModal}
        />
      }
    >
      <div className="page">
        {messageContext}

        <div className="page-header">
          <div>
            <Title level={2} className="page-title">
              {t('watchlist:page.title')}
            </Title>
          </div>
        </div>

        {error && (
          <Alert
            type="error"
            showIcon
            message={t(errorMessageKey(error.code))}
            closable
            onClose={clearError}
            action={
              <Button size="small" onClick={() => void refresh()}>
                {t('common:actions.retry')}
              </Button>
            }
          />
        )}

        {loading ? (
          <div className="loading-block">
            <Spin tip={t('watchlist:loading')}>
              <div style={{ height: 48 }} />
            </Spin>
          </div>
        ) : watchlists.length === 0 ? null : (
          <Table<WatchlistItemRead>
            rowKey="asset_id"
            columns={columns}
            dataSource={selectedWatchlist?.items ?? []}
            pagination={false}
            scroll={{ x: 760 }}
            locale={{
              emptyText: <Empty description={t('watchlist:empty.assets')} />,
            }}
          />
        )}

        {/* Create watchlist modal */}
        <Modal
          open={createOpen}
          title={t('watchlist:create.modal.title')}
          onCancel={() => {
            setCreateOpen(false);
            createForm.resetFields();
          }}
          confirmLoading={creating}
          onOk={run(handleCreate)}
          okText={t('watchlist:create.submit')}
          cancelText={t('common:actions.cancel')}
        >
          <Form form={createForm} layout="vertical" preserve={false}>
            <Form.Item
              name="name"
              label={t('watchlist:create.form.name.label')}
              rules={[{ required: true, message: t('errors:validation') }]}
            >
              <Input placeholder={t('watchlist:create.form.name.placeholder')} autoComplete="off" />
            </Form.Item>
          </Form>
        </Modal>

        {/* Add asset modal */}
        <Modal
          open={addOpen}
          title={t('watchlist:addAsset.modal.title')}
          onCancel={() => setAddOpen(false)}
          confirmLoading={adding}
          onOk={run(handleAddAsset)}
          okText={t('watchlist:addAsset.submit')}
          okButtonProps={{ disabled: !pickedAssetId }}
          cancelText={t('common:actions.cancel')}
        >
          <Form form={addForm} layout="vertical" preserve={false}>
            <Form.Item
              name="symbol"
              label={t('watchlist:addAsset.form.symbol.label')}
              rules={[{ required: true }]}
            >
              <Input
                placeholder={t('watchlist:addAsset.form.symbol.placeholder')}
                autoComplete="off"
              />
            </Form.Item>
            <Form.Item name="exchange" label={t('watchlist:addAsset.form.exchange.label')}>
              <Input
                placeholder={t('watchlist:addAsset.form.exchange.placeholder')}
                autoComplete="off"
              />
            </Form.Item>
            <Button onClick={run(handleSearch)} loading={searching}>
              {t('watchlist:addAsset.search.button')}
            </Button>

            {searchDone && searchResults.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <Text>
                  {t('watchlist:addAsset.search.resultsCount', { count: searchResults.length })}
                </Text>
                <Radio.Group
                  value={pickedAssetId}
                  onChange={(e: RadioChangeEvent) => setPickedAssetId(e.target.value as string)}
                  style={{ display: 'block', marginTop: 8 }}
                >
                  <Space direction="vertical">
                    {searchResults.map((asset) => (
                      <Radio key={asset.asset_id} value={asset.asset_id}>
                        {asset.symbol} · {asset.exchange} · {asset.name}
                      </Radio>
                    ))}
                  </Space>
                </Radio.Group>
              </div>
            )}
            {searchDone && searchResults.length === 0 && (
              <Empty
                description={t('watchlist:addAsset.search.noResults')}
                style={{ marginTop: 16 }}
              />
            )}
          </Form>
        </Modal>
      </div>
    </SiderLayout>
  );
}

export default WatchlistPage;
