/**
 * Dashboard page (FRA-11).
 *
 * The dashboard for a single selected asset:
 *  - reads the cross-page selection from `useSelectionStore`
 *  - empty state when nothing is selected (link back to the watchlist)
 *  - filters: data source (Select) + date window (RangePicker, default 1 year)
 *  - parallel fetch of OHLCV + quality with independent loading/data/error so
 *    a partial failure still shows whichever half succeeded (no cross-blocking)
 *  - OHLCV price chart (top), quality panel (bottom-left), sync control
 *    (bottom-right); the sync control calls back into `refetch` on success
 *
 * Errors map to `t('errors:<code>')` and never surface the backend `detail`.
 * Switching language re-renders labels/options but does NOT re-fetch data.
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  Alert,
  Col,
  DatePicker,
  Empty,
  Row,
  Select,
  Space,
  Typography,
} from 'antd';
import type { Dayjs } from 'dayjs';
import dayjs from 'dayjs';

import { fetchOhlcv } from '@/api/ohlcv';
import { fetchQuality } from '@/api/quality';
import { ApiError } from '@/api/client';
import { useSelectionStore } from '@/store/selection';
import { PriceChart } from '@/components/dashboard/PriceChart';
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

  // (Re)fetch whenever the selection / source / window changes. Language is
  // intentionally NOT a dependency — switching language only re-renders labels.
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
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
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
      </Space>

      <PriceChart bars={ohlcv.data ?? []} loading={ohlcv.loading} errorCode={ohlcv.errorCode} />

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
