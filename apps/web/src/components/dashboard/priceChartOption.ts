/**
 * Pure ECharts option builder for the OHLCV price line (FRA-11).
 *
 * Extracted from `PriceChart.tsx` so that the component file exports only a
 * component (react-refresh requires it) and so the option logic — price-field
 * fallback + i18n legend/tooltip — is unit-testable without a DOM.
 *
 * Each bar contributes a `[timestampMs, price | null]` point. Price is
 * `adjusted_close ?? close`; when both are null the point is `[ts, null]`,
 * which ECharts renders as a gap (the line breaks instead of interpolating).
 */
import type { EChartsOption } from 'echarts';
import dayjs from 'dayjs';
import type { TFunction } from 'i18next';

import type { OhlcvRead } from '@/types/api';

export function buildPriceChartOption(bars: OhlcvRead[], t: TFunction): EChartsOption {
  const fieldName = t('dashboard:priceChart.field.adjustedClose');

  const data: [number, number | null][] = bars.map((bar) => {
    const ms = dayjs(bar.time).valueOf();
    const price = bar.adjusted_close ?? bar.close ?? null;
    return [ms, price];
  });

  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = Array.isArray(params) ? params[0] : params;
        if (!p || p.value == null) return '';
        const [ms, value] = p.value as [number, number | null];
        const date = dayjs(ms).format('LL');
        const num = value == null ? '—' : value.toLocaleString();
        return `${date}<br/>${fieldName}: ${num}`;
      },
    },
    xAxis: {
      type: 'time',
    },
    yAxis: {
      type: 'value',
      scale: true,
    },
    legend: {
      data: [fieldName],
      top: 0,
    },
    grid: {
      left: 48,
      right: 24,
      top: 32,
      bottom: 32,
    },
    series: [
      {
        name: fieldName,
        type: 'line',
        showSymbol: false,
        connectNulls: false,
        data,
      },
    ],
  };
}
