/**
 * Pure ECharts option builders for the backtest result charts (FRA-38).
 *
 * Two builders, both pure (data + i18n `t` → `EChartsOption`), mirroring the
 * `buildPriceChartOption` pattern (FRA-11/24): a `category` x-axis over the
 * actual trading days (weekends/holidays take no horizontal space), `dataZoom`
 * for scroll/zoom, and a `key={language}` remount in the wrapper for label
 * translation.
 *
 * - `buildEquityCurveOption`: strategy vs benchmark equity (two line series).
 * - `buildDrawdownOption`:   strategy (+ benchmark) drawdown (line + area).
 *
 * Drawdown sign: `equity / cummax - 1` is always ≤ 0 (0 = at a peak, negative =
 * underwater), so the curve sits at/below the zero line (a classic underwater
 * chart); the y-axis and tooltip format it as a percent. Both series are
 * reindexed server-side to the strategy's trading days, so they share one time
 * index; benchmark points may be missing for the prefix where the benchmark had
 * no data (rendered as a gap via `connectNulls: false`).
 */
import type { EChartsOption, SeriesOption } from 'echarts';
import dayjs from 'dayjs';
import type { TFunction } from 'i18next';

import type { EquityCurvePointRead } from '@/types/api';
import type { ChartTheme } from '@/theme';

const DEFAULT_CHART_THEME: ChartTheme = {
  text: '#252833',
  mutedText: '#667085',
  gridLine: '#e7e9ef',
  axisLine: '#c9ced8',
  surface: '#ffffff',
  tooltipBg: 'rgba(255, 255, 255, 0.98)',
  tooltipBorder: '#d9dee8',
  primary: '#b85033',
  primarySoft: 'rgba(184, 80, 51, 0.16)',
  quality: '#16877d',
  warning: '#b27a00',
  danger: '#c94135',
  ma5: '#b98500',
  ma20: '#7357b8',
  volume: 'rgba(22, 135, 125, 0.34)',
};

/** Sort ascending by ISO `time`. */
function sortByTime(a: EquityCurvePointRead, b: EquityCurvePointRead): number {
  return a.time < b.time ? -1 : a.time > b.time ? 1 : 0;
}

/** ISO datetime → `YYYY-MM-DD` (the category-axis label). */
function dayLabel(time: string): string {
  return dayjs(time).format('YYYY-MM-DD');
}

/** Split points by series_kind, each sorted ascending by time. */
function splitByKind(points: EquityCurvePointRead[]): {
  strategy: EquityCurvePointRead[];
  benchmark: EquityCurvePointRead[];
} {
  return {
    strategy: points.filter((p) => p.series_kind === 'strategy').sort(sortByTime),
    benchmark: points.filter((p) => p.series_kind === 'benchmark').sort(sortByTime),
  };
}

/**
 * Strategy-vs-benchmark equity curve. The x-axis is the strategy's trading days;
 * both series are looked up by day on that axis (benchmark prefix gaps → null).
 */
export function buildEquityCurveOption(
  points: EquityCurvePointRead[],
  t: TFunction,
  theme: ChartTheme = DEFAULT_CHART_THEME,
): EChartsOption {
  const { strategy, benchmark } = splitByKind(points);
  const times = strategy.map((p) => dayLabel(p.time));
  const stratMap = new Map(strategy.map((p) => [dayLabel(p.time), p.equity]));
  const benchMap = new Map(benchmark.map((p) => [dayLabel(p.time), p.equity]));

  const series: SeriesOption[] = [
    {
      name: t('backtest:equity.strategy'),
      type: 'line',
      showSymbol: false,
      lineStyle: { color: theme.primary, width: 2 },
      itemStyle: { color: theme.primary },
      data: times.map((tk) => stratMap.get(tk) ?? null),
    },
  ];
  if (benchmark.length > 0) {
    series.push({
      name: t('backtest:equity.benchmark'),
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      lineStyle: { color: theme.quality, width: 2 },
      itemStyle: { color: theme.quality },
      data: times.map((tk) => benchMap.get(tk) ?? null),
    });
  }

  return {
    tooltip: {
      trigger: 'axis',
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text },
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

/**
 * Drawdown (underwater) curve. Drawdown is ≤ 0; the y-axis + tooltip format it
 * as a percent. Strategy is filled with a light area; benchmark (if present) is
 * overlaid and may gap on the prefix.
 */
export function buildDrawdownOption(
  points: EquityCurvePointRead[],
  t: TFunction,
  theme: ChartTheme = DEFAULT_CHART_THEME,
): EChartsOption {
  const { strategy, benchmark } = splitByKind(points);
  const times = strategy.map((p) => dayLabel(p.time));
  const stratMap = new Map(strategy.map((p) => [dayLabel(p.time), p.drawdown]));
  const benchMap = new Map(benchmark.map((p) => [dayLabel(p.time), p.drawdown]));

  const series: SeriesOption[] = [
    {
      name: t('backtest:equity.strategy'),
      type: 'line',
      showSymbol: false,
      lineStyle: { color: theme.danger, width: 2 },
      itemStyle: { color: theme.danger },
      areaStyle: { color: theme.primarySoft },
      data: times.map((tk) => stratMap.get(tk) ?? null),
    },
  ];
  if (benchmark.length > 0) {
    series.push({
      name: t('backtest:equity.benchmark'),
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      lineStyle: { color: theme.warning, width: 2 },
      itemStyle: { color: theme.warning },
      areaStyle: { opacity: 0.08 },
      data: times.map((tk) => benchMap.get(tk) ?? null),
    });
  }

  const pct = (value: unknown): string => {
    if (value == null) return '—'; // gap on the benchmark prefix / missing drawdown
    const v = Number(value);
    return Number.isFinite(v) ? `${(v * 100).toFixed(2)}%` : '—';
  };

  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) => pct(value),
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text },
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
      axisLabel: {
        color: theme.mutedText,
        formatter: (value: number) => `${(value * 100).toFixed(0)}%`,
      },
      splitLine: { lineStyle: { color: theme.gridLine } },
    },
    dataZoom: [{ type: 'inside' }],
    series,
  };
}
