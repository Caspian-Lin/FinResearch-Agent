/**
 * Price chart (FRA-11).
 *
 * Renders an OHLCV price line via echarts-for-react. The price field is
 * `adjusted_close`, falling back to `close` per-bar when `adjusted_close` is
 * null; bars where both are null are emitted as gaps (null y) so the line
 * breaks instead of interpolating across missing data. See
 * `priceChartOption.ts` for the (pure, exported, unit-tested) option builder.
 *
 * Language responsiveness: the parent passes the active `language` as `key` so a
 * language change remounts the chart with a freshly-translated option (echarts
 * does not re-read `t` on a prop change otherwise). Switching language does NOT
 * re-fetch data — `bars` are unchanged, only labels are translated.
 */
import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';
import { Alert, Empty, Spin } from 'antd';
import { useTranslation } from 'react-i18next';

import type { OhlcvRead } from '@/types/api';
import { useLanguage } from '@/i18n/useLanguage';
import { buildPriceChartOption } from './priceChartOption';

interface PriceChartProps {
  bars: OhlcvRead[];
  loading: boolean;
  /** Stable ApiError code (e.g. "notFound"); the backend detail is never shown. */
  errorCode: string | null;
}

export function PriceChart({ bars, loading, errorCode }: PriceChartProps) {
  const { t } = useTranslation();
  const { language } = useLanguage();

  const option = useMemo(() => buildPriceChartOption(bars, t), [bars, t]);

  if (loading) {
    // Fixed 360px placeholder matches the rendered chart height below, so
    // toggling between loading and data doesn't make the page jump (FRA-24).
    return (
      <div
        style={{
          height: 360,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Spin tip={t('dashboard:loading')}>
          <div style={{ height: 48, width: 48 }} />
        </Spin>
      </div>
    );
  }

  if (errorCode) {
    return <Alert type="error" showIcon message={t(`errors:${errorCode}`)} />;
  }

  if (bars.length === 0) {
    return <Empty description={t('dashboard:priceChart.noData')} />;
  }

  return (
    <div>
      {/* `key={language}` forces a remount on language change so the freshly
          translated option (legend/tooltip) takes effect. */}
      <ReactECharts key={language} option={option} style={{ height: 360 }} notMerge />
      <div style={{ marginTop: 8, color: '#888', fontSize: 12 }}>
        {t('dashboard:priceChart.fallbackNote')}
      </div>
    </div>
  );
}

export default PriceChart;
