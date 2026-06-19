/**
 * Dashboard page (FRA-11, extended FRA-24).
 *
 * The dashboard for a single selected asset:
 *  - reads the cross-page selection from `useSelectionStore`
 *  - empty state when nothing is selected (link back to the watchlist)
 *  - filters: data source (Select), date window (RangePicker, default 1 year),
 *    chart type (Segmented: line/candle/area), adjust mode (Segmented:
 *    adjusted/raw), MA overlays (Checkbox), volume sub-chart (Switch)
 *  - parallel fetch of OHLCV + quality with independent loading/data/error so
 *    a partial failure still shows whichever half succeeded (no cross-blocking)
 *  - OHLCV price chart (top), quality panel (bottom-left), sync control
 *    (bottom-right); the sync control calls back into `refetch` on success
 *
 * Chart-type / volume / MA / adjust only affect rendering, never the data
 * request, so they are NOT in `loadData`'s dependency list (switching them
 * re-renders without re-fetching). Language switches re-render labels only.
 *
 * Errors map to `t('errors:<code>')` and never surface the backend `detail`.
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  Alert,
  Checkbox,
  Col,
  DatePicker,
  Empty,
  Row,
  Segmented,
  Select,
  Space,
  Switch,
  Typography,
} from 'antd';
import type { Dayjs } from 'dayjs';
import dayjs from 'dayjs';

import { fetchOhlcv } from '@/api/ohlcv';
import { fetchQuality } from '@/api/quality';
import { ApiError } from '@/api/client';
import { useSelectionStore } from '@/store/selection';
import { PriceChart } from '@/components/dashboard/PriceChart';
import type { Adjust, ChartType } from '@/components/dashboard/priceChartOption';
import { QualityPanel } from '@/components/dashboard/QualityPanel';
import { SyncControl } from '@/components/dashboard/SyncControl';
import type { OhlcvRead, QualityReport } from '@/types/api';

const { RangePicker } = DatePicker;
const { Title, Text } = Typography;

/** The only data source currently supported by the backend. */
const SOURCE_OPTIONS = [{ value: 'yfinance', label: 'yfinance' }];

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

  const [source, setSource] = useState<string>('yfinance');
  const [dateRange, setDateRange] = useState<DateRange>([
    dayjs().subtract(1, 'year'),
    dayjs(),
  ]);
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
        const code =
          ohlcvResult.reason instanceof ApiError ? ohlcvResult.reason.code : 'unknown';
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

  // --- Empty state: nothing selected -----------------------------------------
  if (!selectedAsset) {
    return (
      <div>
        <Title level={2}>{t('dashboard:page.title')}</Title>
        <Empty description={t('dashboard:noSelection.message')}>
          <Link to="/watchlist">{t('dashboard:noSelection.link')}</Link>
        </Empty>
      </div>
    );
  }

  return (
    <div>
      <Title level={2} style={{ marginBottom: 4 }}>
        {t('dashboard:page.title')}
      </Title>
      {/* ellipsis guards against very long symbols / Chinese names (FRA-24). */}
      <Text type="secondary" ellipsis style={{ display: 'block', marginBottom: 16 }}>
        {selectedAsset.symbol} · {selectedAsset.exchange} · {selectedAsset.name}
      </Text>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={t('dashboard:dataLimit.title')}
        description={t('dashboard:dataLimit.body')}
      />

      {/* Filters */}
      <Space style={{ marginBottom: 16 }} wrap>
        <span>
          <Text type="secondary">{t('dashboard:filters.source')}: </Text>
          <Select
            aria-label={t('dashboard:filters.source')}
            value={source}
            onChange={setSource}
            options={SOURCE_OPTIONS}
            style={{ width: 160 }}
          />
        </span>
        <span>
          <Text type="secondary">{t('dashboard:filters.dateRange')}: </Text>
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
        <span>
          <Text type="secondary">{t('dashboard:filters.chartType')}: </Text>
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
        <span>
          <Text type="secondary">{t('dashboard:priceChart.adjust.label')}: </Text>
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
        <span>
          <Text type="secondary">{t('dashboard:priceChart.size.label')}: </Text>
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
        <span>
          <Text type="secondary">{t('dashboard:priceChart.ma.label')}: </Text>
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
        <span>
          <Text type="secondary">{t('dashboard:priceChart.volume.label')}: </Text>
          <Switch
            aria-label={t('dashboard:priceChart.volume.label')}
            checked={showVolume}
            onChange={setShowVolume}
          />
        </span>
      </Space>

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

      <Row gutter={24} style={{ marginTop: 24 }}>
        <Col xs={24} lg={14}>
          <QualityPanel
            report={quality.data}
            loading={quality.loading}
            errorCode={quality.errorCode}
          />
        </Col>
        <Col xs={24} lg={10}>
          <Title level={5}>{t('dashboard:sync.button')}</Title>
          <SyncControl
            assetId={assetId}
            source={source}
            start={start}
            end={end}
            onSuccess={loadData}
          />
        </Col>
      </Row>
    </div>
  );
}

export default DashboardPage;
