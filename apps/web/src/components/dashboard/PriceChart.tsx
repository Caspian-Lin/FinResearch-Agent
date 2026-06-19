/**
 * Price chart (FRA-11, extended FRA-24).
 *
 * Renders OHLCV via echarts-for-react in one of three styles — line /
 * candlestick / area — with an optional volume sub-chart and MA5/MA20 overlays.
 * The option is built by the pure, unit-tested `buildPriceChartOption`.
 *
 * The parent owns chart-type / volume / MA / adjust / height state (they only
 * affect rendering, never re-fetch) and passes them down as props.
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
import { useResearchTheme } from '@/theme';
import { buildPriceChartOption } from './priceChartOption';
import type { Adjust, ChartType } from './priceChartOption';

interface PriceChartProps {
  bars: OhlcvRead[];
  loading: boolean;
  /** Stable ApiError code (e.g. "notFound"); the backend detail is never shown. */
  errorCode: string | null;
  /** Main chart style; defaults to line via the builder. */
  chartType?: ChartType;
  /** Whether to render the volume sub-chart. */
  showVolume?: boolean;
  /** Moving-average overlays. */
  ma?: { ma5?: boolean; ma20?: boolean };
  /** Price source for line/area (no effect on candle). */
  adjust?: Adjust;
  /** Chart height in px (loading placeholder matches so toggles don't jump). */
  height?: number;
}

export function PriceChart({
  bars,
  loading,
  errorCode,
  chartType,
  showVolume,
  ma,
  adjust,
  height = 480,
}: PriceChartProps) {
  const { t } = useTranslation();
  const { language } = useLanguage();
  const { palette } = useResearchTheme();

  const option = useMemo(
    () =>
      buildPriceChartOption(bars, t, { chartType, showVolume, ma, adjust, theme: palette.chart }),
    [bars, t, chartType, showVolume, ma, adjust, palette.chart],
  );

  if (loading) {
    return (
      <div
        style={{
          height,
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
      <ReactECharts key={language} option={option} style={{ height }} notMerge />
      <div className="chart-footnote">{t('dashboard:priceChart.fallbackNote')}</div>
    </div>
  );
}

export default PriceChart;
