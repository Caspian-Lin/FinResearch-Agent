/**
 * Quantile-backtest chart option builder (FRA-58).
 *
 * Renders N equity curves (one per factor-value bucket, 1 = lowest) plus the
 * long-top − short-bottom spread as a bold overlay. Bucket colors come from the
 * colorblind-safe `QUANTILE_PALETTE` (Okabe–Ito); the spread uses `theme.primary`
 * so it reads distinctly from the bucket family. All curves share one time index
 * (the union of bucket dates), with gaps where a bucket had no point.
 */
import type { EChartsOption, SeriesOption } from 'echarts';
import dayjs from 'dayjs';
import type { TFunction } from 'i18next';

import type { QuantileResult, TimeSeriesPoint } from '@/types/api';
import type { ChartTheme } from '@/theme';
import { DEFAULT_FACTOR_CHART_THEME, QUANTILE_PALETTE } from './defaultChartTheme';

function dayLabel(time: string): string {
  return dayjs(time).format('YYYY-MM-DD');
}

function sortByTime(a: TimeSeriesPoint, b: TimeSeriesPoint): number {
  return a.time < b.time ? -1 : a.time > b.time ? 1 : 0;
}

/** Quantile labels sorted numerically (1, 2, …, N) — bucket keys may be strings. */
function sortedBucketKeys(quantileEquity: Record<string, TimeSeriesPoint[]>): string[] {
  return Object.keys(quantileEquity).sort((a, b) => Number(a) - Number(b));
}

export function buildQuantileOption(
  data: QuantileResult,
  t: TFunction,
  theme: ChartTheme = DEFAULT_FACTOR_CHART_THEME,
): EChartsOption {
  const keys = sortedBucketKeys(data.quantile_equity);
  // One x-axis over the union of all bucket + spread dates (sorted unique).
  const allTimes = new Set<string>();
  for (const k of keys) {
    for (const p of data.quantile_equity[k]) allTimes.add(dayLabel(p.time));
  }
  for (const p of data.top_minus_bottom) allTimes.add(dayLabel(p.time));
  const times = [...allTimes].sort();

  const series: SeriesOption[] = keys.map((k, idx) => {
    const pts = [...data.quantile_equity[k]].sort(sortByTime);
    const valueByDay = new Map(pts.map((p) => [dayLabel(p.time), p.value]));
    return {
      name: t('factor:quantile.bucket', { n: k }),
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      lineStyle: { color: QUANTILE_PALETTE[idx % QUANTILE_PALETTE.length], width: 1.5 },
      itemStyle: { color: QUANTILE_PALETTE[idx % QUANTILE_PALETTE.length] },
      data: times.map((tk) => valueByDay.get(tk) ?? null),
    };
  });

  if (data.top_minus_bottom.length > 0) {
    const spread = [...data.top_minus_bottom].sort(sortByTime);
    const spreadByDay = new Map(spread.map((p) => [dayLabel(p.time), p.value]));
    series.push({
      name: t('factor:quantile.spread'),
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      lineStyle: { color: theme.primary, width: 2.5 },
      itemStyle: { color: theme.primary },
      data: times.map((tk) => spreadByDay.get(tk) ?? null),
    });
  }

  return {
    tooltip: {
      trigger: 'axis',
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text },
      valueFormatter: (value) => {
        const v = Number(value);
        return Number.isFinite(v) ? v.toFixed(4) : '—';
      },
    },
    legend: {
      top: 0,
      data: series.map((s) => s.name as string),
      textStyle: { color: theme.mutedText },
    },
    grid: { left: 56, right: 24, top: 32, bottom: 32 },
    xAxis: {
      type: 'category',
      data: times,
      axisLabel: { hideOverlap: true, color: theme.mutedText },
      axisLine: { lineStyle: { color: theme.axisLine } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: theme.mutedText },
      splitLine: { lineStyle: { color: theme.gridLine } },
    },
    dataZoom: [{ type: 'inside' }],
    series,
  };
}
