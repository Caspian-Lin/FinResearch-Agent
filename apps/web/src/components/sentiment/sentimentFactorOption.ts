/**
 * Sentiment factor chart option builder (FRA-72).
 *
 * Pure `(data, t, theme) → EChartsOption` builder for the daily sentiment
 * factor time series. Each asset is one line series; values are the daily
 * mean sentiment score in [−1, +1]. Mirrors the `buildICOption` /
 * `buildEquityCurveOption` pattern: category x-axis over dates, dataZoom,
 * `key={language}` remount for label translation.
 */
import type { EChartsOption, SeriesOption } from 'echarts';
import dayjs from 'dayjs';
import type { TFunction } from 'i18next';

import type { SentimentFactorItemRead } from '@/types/api';
import type { ChartTheme } from '@/theme';
import { DEFAULT_FACTOR_CHART_THEME } from '@/components/factor/defaultChartTheme';

const SENTIMENT_PALETTE = [
  '#b85033',
  '#16877d',
  '#7357b8',
  '#b27a00',
  '#0072b2',
  '#d55e00',
  '#cc79a7',
];

/** ISO datetime → `YYYY-MM-DD`. */
function dayLabel(time: string): string {
  return dayjs(time).format('YYYY-MM-DD');
}

export function buildSentimentFactorOption(
  items: SentimentFactorItemRead[],
  t: TFunction,
  theme: ChartTheme = DEFAULT_FACTOR_CHART_THEME,
): EChartsOption {
  if (items.length === 0) {
    return { series: [] };
  }

  // Build the union of all dates across assets (sorted ascending).
  const allDates = new Set<string>();
  for (const item of items) {
    for (const pt of item.values) {
      allDates.add(dayLabel(pt.time));
    }
  }
  const dates = [...allDates].sort();

  const series: SeriesOption[] = items.map((item, idx) => {
    const valueMap = new Map(item.values.map((pt) => [dayLabel(pt.time), pt.value]));
    const color = SENTIMENT_PALETTE[idx % SENTIMENT_PALETTE.length];
    return {
      name: t('sentiment:factor.perAsset', { id: item.asset_id.slice(0, 8) }),
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      lineStyle: { color, width: 2 },
      itemStyle: { color },
      data: dates.map((d) => {
        const v = valueMap.get(d);
        return v !== undefined ? v : null;
      }),
    };
  });

  return {
    tooltip: {
      trigger: 'axis',
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text },
      valueFormatter: (value) => {
        if (value == null) return '—';
        const v = Number(value);
        return Number.isFinite(v) ? v.toFixed(4) : '—';
      },
    },
    legend: {
      top: 0,
      data: series.map((s) => s.name as string),
      textStyle: { color: theme.mutedText },
    },
    grid: { left: 56, right: 24, top: 40, bottom: 32 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { hideOverlap: true, color: theme.mutedText },
      axisLine: { lineStyle: { color: theme.axisLine } },
    },
    yAxis: {
      type: 'value',
      min: -1,
      max: 1,
      axisLabel: {
        color: theme.mutedText,
        formatter: (value: number) => value.toFixed(2),
      },
      splitLine: { lineStyle: { color: theme.gridLine } },
    },
    dataZoom: [{ type: 'inside' }],
    series,
  };
}
