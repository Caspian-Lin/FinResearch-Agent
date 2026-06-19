/**
 * Pure ECharts option builder for the OHLCV price chart (FRA-11, extended FRA-24).
 *
 * Supports three main chart types — line / candlestick / area — an optional
 * volume sub-chart (second grid), optional MA5/MA20 overlays, and an
 * adjusted-vs-raw price toggle. Pure: takes bars + t + options, returns an
 * EChartsOption. Unit-tested without a DOM.
 *
 * Non-trading days are hidden: the x-axis is a `category` axis whose data is
 * exactly the trading days present in `bars`, so weekends/holidays take no
 * horizontal space and the series are drawn continuously (no gaps). All series
 * align to that axis by index.
 *
 * Candlestick requires a complete OHLC for every slot (echarts' candle data
 * type has no null), so in candle mode bars with any null OHLC are dropped
 * (yfinance bars always carry full OHLCV, so this loses nothing in practice).
 * Line/area/volume/MA tolerate per-bar nulls on their own (gaps / connectNulls).
 *
 * Backward compatibility: called with no options (or `chartType` omitted) it
 * returns the original single-line chart (now on a category axis).
 *
 * Price-field semantics:
 *  - line / area: price = `adjusted_close ?? close` when `adjust='adjusted'`
 *    (the default), or `close` when `adjust='raw'`.
 *  - candlestick: always raw OHLC — the backend stores no split/dividend-adjusted
 *    open/high/low (see FRA-23), so the adjust toggle has no effect on candles.
 */
import type { EChartsOption, SeriesOption } from 'echarts';
import dayjs from 'dayjs';
import type { TFunction } from 'i18next';

import type { OhlcvRead } from '@/types/api';
import type { ChartTheme } from '@/theme';

export type ChartType = 'line' | 'candle' | 'area';
export type Adjust = 'adjusted' | 'raw';

export interface PriceChartOptions {
  /** Main chart style. Defaults to 'line' (keeps legacy behaviour). */
  chartType?: ChartType;
  /** Show a volume sub-chart (second grid). Defaults to false at the builder
   * level; the page wires its own default (true) via state. */
  showVolume?: boolean;
  /** Moving-average overlays over the main chart. */
  ma?: { ma5?: boolean; ma20?: boolean };
  /** Price source for line/area. Defaults to 'adjusted'. No effect on candle. */
  adjust?: Adjust;
  /** Visual theme shared with the app shell. */
  theme?: ChartTheme;
}

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

/** A bar with a guaranteed-complete OHLC (candlestick needs all four). */
type OhlcBar = OhlcvRead & {
  open: number;
  close: number;
  high: number;
  low: number;
};

function hasOhlc(b: OhlcvRead): b is OhlcBar {
  return b.open != null && b.close != null && b.high != null && b.low != null;
}

/**
 * Simple moving average over a (possibly sparse) series. Returns one value per
 * input: null for the first `period-1` entries (not enough data) and for any
 * window containing a null (a missing day). Pure + unit-tested.
 */
export function calcMA(values: (number | null)[], period: number): (number | null)[] {
  const out: (number | null)[] = [];
  for (let i = 0; i < values.length; i += 1) {
    if (i < period - 1) {
      out.push(null);
      continue;
    }
    const window = values.slice(i - period + 1, i + 1);
    if (window.some((v) => v == null)) {
      out.push(null);
      continue;
    }
    const sum = window.reduce<number>((acc, v) => acc + (v as number), 0);
    out.push(sum / period);
  }
  return out;
}

export function buildPriceChartOption(
  bars: OhlcvRead[],
  t: TFunction,
  opts: PriceChartOptions = {},
): EChartsOption {
  const chartType: ChartType = opts.chartType ?? 'line';
  const showVolume = opts.showVolume ?? false;
  const adjust: Adjust = opts.adjust ?? 'adjusted';
  const chartTheme = opts.theme ?? DEFAULT_CHART_THEME;

  const fieldName = t('dashboard:priceChart.field.adjustedClose');

  // Candlestick can't represent a null-OHLC slot, so drop such bars in candle
  // mode (keeps the axis gap-free). Line/area keep every bar (per-bar nulls are
  // handled by connectNulls / gaps).
  const effectiveBars: readonly OhlcvRead[] = chartType === 'candle' ? bars.filter(hasOhlc) : bars;

  // Category labels: only the days that actually have a bar. Non-trading days
  // (weekends/holidays) are absent, so the axis is gap-free.
  const tradingDays = effectiveBars.map((b) => dayjs(b.time).format('YYYY-MM-DD'));

  const priceOf = (b: OhlcvRead): number | null =>
    adjust === 'adjusted' ? (b.adjusted_close ?? b.close ?? null) : (b.close ?? null);

  // --- Main series (data aligned to tradingDays by index) -------------------
  let mainSeries: SeriesOption;
  let closesForMA: (number | null)[];
  if (chartType === 'candle') {
    mainSeries = {
      name: fieldName,
      type: 'candlestick',
      data: effectiveBars.map((b): [number, number, number, number] => {
        // candle mode already filtered to OhlcBar; the union type still permits
        // null so coalesce to 0 (a no-op in practice). adjust='adjusted' back-
        // adjusts OHLC by the adjusted_close/close ratio so candles track the
        // split/dividend-adjusted price (line/area use adjusted_close directly);
        // 'raw' keeps original OHLC.
        const o = b.open ?? 0;
        const c = b.close ?? 0;
        const l = b.low ?? 0;
        const h = b.high ?? 0;
        if (adjust === 'adjusted' && b.adjusted_close != null && c !== 0) {
          const ratio = b.adjusted_close / c;
          return [o * ratio, c * ratio, l * ratio, h * ratio];
        }
        return [o, c, l, h];
      }),
      itemStyle: {
        color: chartTheme.danger,
        color0: chartTheme.quality,
        borderColor: chartTheme.danger,
        borderColor0: chartTheme.quality,
      },
    };
    closesForMA = effectiveBars.map((b) => b.close);
  } else {
    mainSeries = {
      name: fieldName,
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      lineStyle: { color: chartTheme.primary, width: 2 },
      itemStyle: { color: chartTheme.primary },
      data: effectiveBars.map((b) => priceOf(b)),
      ...(chartType === 'area' ? { areaStyle: { color: chartTheme.primarySoft } } : {}),
    };
    closesForMA = effectiveBars.map((b) => priceOf(b));
  }

  // --- MA overlays (line series on the main grid, aligned by index) ---------
  const series: SeriesOption[] = [mainSeries];
  if (opts.ma?.ma5) {
    series.push({
      name: 'MA5',
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      lineStyle: { color: chartTheme.ma5, width: 1.2 },
      itemStyle: { color: chartTheme.ma5 },
      z: 10,
      data: calcMA(closesForMA, 5),
    });
  }
  if (opts.ma?.ma20) {
    series.push({
      name: 'MA20',
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      lineStyle: { color: chartTheme.ma20, width: 1.2 },
      itemStyle: { color: chartTheme.ma20 },
      z: 10,
      data: calcMA(closesForMA, 20),
    });
  }

  // --- Volume sub-chart (second grid, shared category axis) -----------------
  const hasVolume = showVolume && effectiveBars.some((b) => b.volume != null);
  if (hasVolume) {
    series.push({
      name: t('dashboard:priceChart.volume.label'),
      type: 'bar',
      xAxisIndex: 1,
      yAxisIndex: 1,
      // Per-bar colour by up/down day; null-volume days emit a gap.
      data: effectiveBars.map((b) => {
        if (b.volume == null) return null;
        const up = (b.close ?? 0) >= (b.open ?? 0);
        return {
          value: b.volume,
          itemStyle: { color: up ? chartTheme.danger : chartTheme.quality },
        };
      }),
    });
  }

  // Tooltip: the category axis gives us the date as `params.name`; candle rows
  // unpack [open, close, low, high], other rows show a single value.
  // Built-in axis tooltip: echarts formats each series itself (OHLC for
  // candlestick, value for line/MA/volume) and shows the category label (the
  // trading day). A custom formatter kept mis-reading echarts' reshaped
  // `value`/`data` on the category axis and showed "—" for every series.
  const tooltip: EChartsOption['tooltip'] = {
    trigger: 'axis',
    backgroundColor: chartTheme.tooltipBg,
    borderColor: chartTheme.tooltipBorder,
    textStyle: { color: chartTheme.text },
  };

  // legend lists main + MA only (volume sub-chart stays out of the legend).
  const legend = {
    data: series.filter((s) => s.type !== 'bar').map((s) => s.name as string),
    top: 0,
    textStyle: { color: chartTheme.mutedText },
  };

  // xAxisIndex links the main chart and the volume sub-chart so zoom/pan on
  // one drives both (otherwise volume stays fixed while the price scrolls).
  const dataZoom: EChartsOption['dataZoom'] = [
    { type: 'inside', xAxisIndex: hasVolume ? [0, 1] : [0] },
  ];

  // Shared category axis config. boundaryGap defaults to true so candlestick
  // bars sit centered on their slot and bar/volume render correctly.
  const categoryAxis = {
    type: 'category' as const,
    data: tradingDays,
    axisLabel: { hideOverlap: true, color: chartTheme.mutedText },
    axisLine: { lineStyle: { color: chartTheme.axisLine } },
    axisTick: { lineStyle: { color: chartTheme.axisLine } },
  };

  // Compact large volume ints (e.g. 150000000 → "150M") so the y-axis labels
  // fit inside the grid's left margin instead of overflowing it.
  const formatVolumeLabel = (value: number) => {
    if (value == null) return '';
    if (value >= 1e9) return `${value / 1e9}B`;
    if (value >= 1e6) return `${value / 1e6}M`;
    if (value >= 1e3) return `${value / 1e3}K`;
    return String(value);
  };

  const valueAxis = {
    type: 'value' as const,
    scale: true,
    axisLabel: { color: chartTheme.mutedText },
    axisLine: { lineStyle: { color: chartTheme.axisLine } },
    splitLine: { lineStyle: { color: chartTheme.gridLine } },
  };

  if (hasVolume) {
    // Dual grid: main chart (top ~58%) + volume (bottom ~18%), shared x.
    return {
      tooltip,
      legend,
      grid: [
        { left: 48, right: 24, top: 32, height: '58%' },
        { left: 48, right: 24, top: '74%', height: '18%' },
      ],
      xAxis: [
        { ...categoryAxis, gridIndex: 0 },
        { ...categoryAxis, gridIndex: 1, axisLabel: { show: false } },
      ],
      yAxis: [
        { ...valueAxis, gridIndex: 0 },
        {
          ...valueAxis,
          gridIndex: 1,
          splitNumber: 2,
          axisLabel: { ...valueAxis.axisLabel, formatter: formatVolumeLabel },
        },
      ],
      dataZoom,
      series,
    };
  }

  // Single-grid (legacy line / candle-without-volume) layout.
  return {
    tooltip,
    legend,
    grid: { left: 48, right: 24, top: 32, bottom: 32 },
    xAxis: { ...categoryAxis },
    yAxis: valueAxis,
    dataZoom,
    series,
  };
}
