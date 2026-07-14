/**
 * Pure ECharts option builders for the factor research charts (FRA-58).
 *
 * Three builders, all pure (`(data, t, theme) → EChartsOption`), mirroring the
 * `buildEquityCurveOption` pattern (FRA-11/24/38): a category x-axis over the
 * actual dates, `dataZoom`, and a `key={language}` remount in the wrapper for
 * label translation. Colors come from `palette.chart` (light/dark aware); the
 * quantile palette + heatmap scale are colorblind-safe (Okabe–Ito / diverging),
 * and no meaning rests on color alone (values are in tooltips / a table).
 *
 * - `buildICOption`:        per-period IC bars + average markLine (zero axis).
 * - `buildQuantileOption`:  N quantile-bucket equity lines + top−bottom spread.
 * - `buildHeatmapOption`:   window × cost_bps grid of net Sharpe (sensitivity).
 */
import type { EChartsOption, SeriesOption } from 'echarts';
import dayjs from 'dayjs';
import type { TFunction } from 'i18next';

import type { TimeSeriesPoint } from '@/types/api';
import type { ChartTheme } from '@/theme';
import { DEFAULT_FACTOR_CHART_THEME } from './defaultChartTheme';

/** ISO datetime → `YYYY-MM-DD` (the category-axis label). */
function dayLabel(time: string): string {
  return dayjs(time).format('YYYY-MM-DD');
}

/** Sort ascending by ISO `time`. */
function sortByTime(a: TimeSeriesPoint, b: TimeSeriesPoint): number {
  return a.time < b.time ? -1 : a.time > b.time ? 1 : 0;
}

/**
 * Per-period IC (information coefficient) chart. IC is a cross-sectional rank
 * correlation, centered on 0; bars encode the sign/magnitude each period and a
 * dashed markLine shows the average (the headline IC). A zero axis baseline makes
 * sign readable in addition to the red/green tint (color is not the only cue).
 */
export function buildICOption(
  series: TimeSeriesPoint[],
  t: TFunction,
  theme: ChartTheme = DEFAULT_FACTOR_CHART_THEME,
): EChartsOption {
  const sorted = [...series].sort(sortByTime);
  const times = sorted.map((p) => dayLabel(p.time));
  const values = sorted.map((p) => p.value);
  const mean = values.length > 0 ? values.reduce((s, v) => s + v, 0) / values.length : 0;

  const icSeries: SeriesOption = {
    name: t('factor:ic.series'),
    type: 'bar',
    data: values.map((v) => ({
      value: v,
      itemStyle: { color: v >= 0 ? theme.quality : theme.danger },
    })),
    barWidth: '70%',
    markLine: {
      symbol: 'none',
      lineStyle: { color: theme.primary, type: 'dashed', width: 2 },
      label: {
        formatter: () => `${t('factor:ic.mean')}: ${mean.toFixed(3)}`,
        color: theme.text,
      },
      data: [{ yAxis: mean }],
    },
  };

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
    grid: { left: 56, right: 24, top: 24, bottom: 32 },
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
        formatter: (value: number) => value.toFixed(2),
      },
      splitLine: { lineStyle: { color: theme.gridLine } },
    },
    dataZoom: [{ type: 'inside' }],
    series: [icSeries],
  };
}
