/**
 * Dashboard page (FRA-11, extended FRA-24, FRA-45 master/detail layout).
 *
 * A left sidebar lists the assets of a watchlist; the main area shows the
 * selected asset's dashboard. Picking an asset in the sidebar writes to
 * `useSelectionStore`; this page reads it back and re-fetches, so the sidebar
 * replaces the old "go to /watchlist → pick → come back" round-trip.
 *
 * For a single selected asset the main area:
 *  - reads the cross-page selection from `useSelectionStore`
 *  - empty state when no asset is selectable (sidebar present but no items)
 *  - filters: data source (Select), date window (RangePicker, default 1 year),
 *    chart type (Segmented: line/candle/area), adjust mode (Segmented:
 *    adjusted/raw), MA overlays (Checkbox), volume sub-chart (Switch)
 *  - parallel fetch of OHLCV + quality with independent loading/data/error so
 *    a partial failure still shows whichever half succeeded (no cross-blocking)
 *  - OHLCV price chart (top), quality panel (bottom-left), sync control
 *    (bottom-right); the sync control calls back into `loadData` on success
 *
 * Sidebar data (`useWatchlists`) and the active-watchlist choice are owned here
 * (lifted) so the desktop `Sider` and the narrow-screen `Drawer` share one fetch
 * + one state. On first load, if nothing is selected yet, the first asset of the
 * active watchlist is auto-selected (per the FRA-45 product decision).
 *
 * Chart-type / volume / MA / adjust only affect rendering, never the data
 * request, so they are NOT in `loadData`'s dependency list (switching them
 * re-renders without re-fetching). Language switches re-render labels only.
 *
 * Errors map to `t('errors:<code>')` and never surface the backend `detail`.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  Alert,
  Card,
  Checkbox,
  Col,
  DatePicker,
  Empty,
  Row,
  Segmented,
  Switch,
  Typography,
} from 'antd';
import type { Dayjs } from 'dayjs';
import dayjs from 'dayjs';

import { fetchOhlcv } from '@/api/ohlcv';
import { fetchQuality } from '@/api/quality';
import { ApiError } from '@/api/client';
import { useSelectionStore } from '@/store/selection';
import { useWatchlists } from '@/hooks/useWatchlists';
import { PriceChart } from '@/components/dashboard/PriceChart';
import type { Adjust, ChartType } from '@/components/dashboard/priceChartOption';
import { QualityPanel } from '@/components/dashboard/QualityPanel';
import { SyncControl } from '@/components/dashboard/SyncControl';
import { WatchlistSidebar } from '@/components/dashboard/WatchlistSidebar';
import { SiderLayout } from '@/components/layout/SiderLayout';
import { ToggleSelect } from '@/components/ui/ToggleSelect';
import type { OhlcvRead, QualityReport, WatchlistItemRead } from '@/types/api';

const { RangePicker } = DatePicker;
const { Title, Text } = Typography;

/** Tuple type for the RangePicker value (null when cleared). */
type DateRange = [Dayjs, Dayjs];

interface AsyncState<T> {
  loading: boolean;
  data: T | null;
  /** Stable ApiError code, or null. */
  errorCode: string | null;
}

function initState<T>(): AsyncState<T> {
  return { loading: false, data: null, errorCode: null };
}

function toIsoDate(d: Dayjs): string {
  return d.format('YYYY-MM-DD');
}

function DashboardPage() {
  const { t } = useTranslation();
  const selectedAsset = useSelectionStore((s) => s.selectedAsset);
  const setSelectedAsset = useSelectionStore((s) => s.setSelectedAsset);

  // Sidebar data is lifted here so the desktop Sider and the narrow-screen
  // Drawer share one useWatchlists call + one active-watchlist state.
  const { watchlists, loading: watchlistsLoading, error: watchlistsError } = useWatchlists();
  const [selectedWatchlistId, setSelectedWatchlistId] = useState<string | null>(null);

  // Default-select the first watchlist once the list resolves (mirrors
  // WatchlistPage). When the list is empty there is nothing to select.
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

  // First-load auto-select: if the user hasn't picked anything yet, select the
  // first asset of the active watchlist so the dashboard isn't empty on entry.
  // Only fires while nothing is selected (no clobbering if the user clears).
  useEffect(() => {
    if (selectedAsset) return;
    const items = selectedWatchlist?.items ?? [];
    if (items.length > 0) {
      const first = items[0];
      setSelectedAsset({
        asset_id: first.asset_id,
        symbol: first.symbol,
        exchange: first.exchange,
        name: first.name,
      });
    }
  }, [selectedAsset, selectedWatchlist, setSelectedAsset]);

  const handlePick = useCallback(
    (item: WatchlistItemRead) =>
      setSelectedAsset({
        asset_id: item.asset_id,
        symbol: item.symbol,
        exchange: item.exchange,
        name: item.name,
      }),
    [setSelectedAsset],
  );

  const sidebar = (
    <WatchlistSidebar
      watchlists={watchlists}
      loading={watchlistsLoading}
      error={watchlistsError}
      selectedWatchlistId={selectedWatchlistId}
      onSelectWatchlist={setSelectedWatchlistId}
      selectedAssetId={selectedAsset?.asset_id ?? null}
      onPick={handlePick}
    />
  );

  const [source, setSource] = useState<string>('yfinance');
  // Data sources supported by the backend (FRA-23): yfinance (overseas) +
  // akshare/tushare (A-share). Labels are localized; the value is the source
  // key sent to POST /sync.
  const sourceOptions = useMemo(
    () => [
      { value: 'yfinance', label: t('dashboard:sources.yfinance') },
      { value: 'akshare', label: t('dashboard:sources.akshare') },
      { value: 'tushare', label: t('dashboard:sources.tushare') },
    ],
    [t],
  );
  const [dateRange, setDateRange] = useState<DateRange>([dayjs().subtract(1, 'year'), dayjs()]);
  // Render-only options — never trigger a re-fetch, so they stay out of
  // `loadData`'s dependency list.
  const [chartType, setChartType] = useState<ChartType>('line');
  const [showVolume, setShowVolume] = useState(true);
  const [ma, setMa] = useState<{ ma5: boolean; ma20: boolean }>({ ma5: false, ma20: false });
  const [adjust, setAdjust] = useState<Adjust>('adjusted');
  const [chartHeight, setChartHeight] = useState<number>(480);

  const [ohlcv, setOhlcv] = useState<AsyncState<OhlcvRead[]>>(initState());
  const [quality, setQuality] = useState<AsyncState<QualityReport>>(initState());

  const assetId = selectedAsset?.asset_id ?? null;
  const start = dateRange[0] ? toIsoDate(dateRange[0]) : '';
  const end = dateRange[1] ? toIsoDate(dateRange[1]) : '';

  const loadData = useCallback(() => {
    if (!assetId || !start || !end) return;

    // Independent loading flags so each half can resolve/reject on its own.
    setOhlcv({ loading: true, data: null, errorCode: null });
    setQuality({ loading: true, data: null, errorCode: null });

    // Promise.allSettled so one rejection never masks the other.
    void Promise.allSettled([
      fetchOhlcv({ asset_id: assetId, source, start, end }),
      fetchQuality({ asset_id: assetId, source, start, end }),
    ]).then(([ohlcvResult, qualityResult]) => {
      if (ohlcvResult.status === 'fulfilled') {
        setOhlcv({ loading: false, data: ohlcvResult.value, errorCode: null });
      } else {
        const code = ohlcvResult.reason instanceof ApiError ? ohlcvResult.reason.code : 'unknown';
        setOhlcv({ loading: false, data: null, errorCode: code });
      }

      if (qualityResult.status === 'fulfilled') {
        setQuality({ loading: false, data: qualityResult.value, errorCode: null });
      } else {
        const code =
          qualityResult.reason instanceof ApiError ? qualityResult.reason.code : 'unknown';
        setQuality({ loading: false, data: null, errorCode: code });
      }
    });
  }, [assetId, source, start, end]);

  // (Re)fetch whenever the selection / source / window changes. Render-only
  // options (chartType/volume/ma/adjust) and language are intentionally NOT
  // dependencies — they only change presentation, not the data request.
  useEffect(() => {
    loadData();
  }, [loadData]);

  return (
    <SiderLayout sidebar={sidebar}>
      <div className="page">
        <div className="page-header">
          <div>
            <Title level={2} className="page-title">
              {t('dashboard:page.title')}
            </Title>
            {/* ellipsis guards against very long symbols / Chinese names (FRA-24). */}
            {selectedAsset && (
              <Text type="secondary" ellipsis className="page-description">
                {selectedAsset.symbol} · {selectedAsset.exchange} · {selectedAsset.name}
              </Text>
            )}
          </div>
        </div>

        {selectedAsset ? (
          <>
            <Alert
              type="info"
              showIcon
              message={t('dashboard:dataLimit.title')}
              description={t('dashboard:dataLimit.body')}
            />

            {/* Filters */}
            <div className="toolbar-panel">
              <span className="field-cluster">
                <span className="field-label">{t('dashboard:filters.source')}</span>
                <ToggleSelect
                  ariaLabel={t('dashboard:filters.source')}
                  value={source}
                  onChange={setSource}
                  options={sourceOptions}
                  width={160}
                />
              </span>
              <span className="field-cluster">
                <span className="field-label">{t('dashboard:filters.dateRange')}</span>
                <RangePicker
                  aria-label={t('dashboard:filters.dateRange')}
                  value={dateRange}
                  onChange={(values) => {
                    if (values && values[0] && values[1]) {
                      setDateRange([values[0], values[1]]);
                    }
                  }}
                  allowClear={false}
                />
              </span>
              <span className="field-cluster">
                <span className="field-label">{t('dashboard:filters.chartType')}</span>
                <Segmented
                  aria-label={t('dashboard:filters.chartType')}
                  value={chartType}
                  onChange={(v) => setChartType(v as ChartType)}
                  options={[
                    { value: 'line', label: t('dashboard:priceChart.chartType.line') },
                    { value: 'candle', label: t('dashboard:priceChart.chartType.candle') },
                    { value: 'area', label: t('dashboard:priceChart.chartType.area') },
                  ]}
                />
              </span>
              <span className="field-cluster">
                <span className="field-label">{t('dashboard:priceChart.adjust.label')}</span>
                <Segmented
                  aria-label={t('dashboard:priceChart.adjust.label')}
                  value={adjust}
                  onChange={(v) => setAdjust(v as Adjust)}
                  options={[
                    { value: 'adjusted', label: t('dashboard:priceChart.adjust.adjusted') },
                    { value: 'raw', label: t('dashboard:priceChart.adjust.raw') },
                  ]}
                />
              </span>
              <span className="field-cluster">
                <span className="field-label">{t('dashboard:priceChart.size.label')}</span>
                <Segmented
                  aria-label={t('dashboard:priceChart.size.label')}
                  value={chartHeight}
                  onChange={(v) => setChartHeight(v)}
                  options={[
                    { value: 360, label: t('dashboard:priceChart.size.small') },
                    { value: 480, label: t('dashboard:priceChart.size.medium') },
                    { value: 640, label: t('dashboard:priceChart.size.large') },
                  ]}
                />
              </span>
              <span className="field-cluster">
                <span className="field-label">{t('dashboard:priceChart.ma.label')}</span>
                <Checkbox
                  checked={ma.ma5}
                  onChange={(e) => setMa((prev) => ({ ...prev, ma5: e.target.checked }))}
                >
                  {t('dashboard:priceChart.ma.ma5')}
                </Checkbox>
                <Checkbox
                  checked={ma.ma20}
                  onChange={(e) => setMa((prev) => ({ ...prev, ma20: e.target.checked }))}
                >
                  {t('dashboard:priceChart.ma.ma20')}
                </Checkbox>
              </span>
              <span className="field-cluster">
                <span className="field-label">{t('dashboard:priceChart.volume.label')}</span>
                <Switch
                  aria-label={t('dashboard:priceChart.volume.label')}
                  checked={showVolume}
                  onChange={setShowVolume}
                />
              </span>
            </div>

            <Card className="panel" styles={{ body: { padding: 16 } }}>
              <PriceChart
                bars={ohlcv.data ?? []}
                loading={ohlcv.loading}
                errorCode={ohlcv.errorCode}
                chartType={chartType}
                showVolume={showVolume}
                ma={ma}
                adjust={adjust}
                height={chartHeight}
              />
            </Card>

            <Row gutter={[16, 16]}>
              <Col xs={24} lg={14}>
                <Card className="panel" styles={{ body: { padding: 16 } }}>
                  <QualityPanel
                    report={quality.data}
                    loading={quality.loading}
                    errorCode={quality.errorCode}
                  />
                </Card>
              </Col>
              <Col xs={24} lg={10}>
                <Card className="panel" styles={{ body: { padding: 16 } }}>
                  <Title level={5}>{t('dashboard:sync.button')}</Title>
                  <SyncControl
                    assetId={assetId}
                    source={source}
                    start={start}
                    end={end}
                    onSuccess={loadData}
                  />
                </Card>
              </Col>
            </Row>
          </>
        ) : (
          <Card className="panel">
            <Empty description={t('dashboard:noSelection.message')}>
              <Link to="/watchlist">{t('dashboard:noSelection.link')}</Link>
            </Empty>
          </Card>
        )}
      </div>
    </SiderLayout>
  );
}

export default DashboardPage;
