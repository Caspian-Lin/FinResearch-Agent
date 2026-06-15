/**
 * Pure ECharts option builder for the OHLCV price chart (FRA-11, extended FRA-24).
 *
 * Extracted from `PriceChart.tsx` so the component file exports only a component
 * (react-refresh requires it) and the option logic — multi-type series, volume
 * sub-chart, MA overlays, adjusted/raw toggle — is unit-testable without a DOM.
 *
 * Backward compatibility: called with no options (or `chartType` omitted) it
 * returns the original single-line chart, so the existing priceChartOption.test
 * assertions still hold. New behaviour is opt-in via the `opts` argument.
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
}

/** A-share convention: up (close ≥ open) red, down green. */
const UP_COLOR = '#ef5350';
const DOWN_COLOR = '#26a69a';
const MA5_COLOR = '#ff9800';
const MA20_COLOR = '#9c27b0';

function fmtNum(v: number | null | undefined): string {
  return v == null ? '—' : v.toLocaleString();
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

  const fieldName = t('dashboard:priceChart.field.adjustedClose');
  const tsOf = (b: OhlcvRead) => dayjs(b.time).valueOf();

  // Price used by line/area points and by MA in line/area mode.
  const priceOf = (b: OhlcvRead): number | null =>
    adjust === 'adjusted' ? (b.adjusted_close ?? b.close ?? null) : (b.close ?? null);

  // --- Main series + the close series MA rides on --------------------------
  let mainSeries: SeriesOption;
  let closesForMA: (number | null)[];
  if (chartType === 'candle') {
    const candleData: [number, number, number, number, number][] = [];
    for (const b of bars) {
      if (b.open == null || b.close == null || b.high == null || b.low == null) continue;
      candleData.push([tsOf(b), b.open, b.close, b.low, b.high]);
    }
    mainSeries = {
      name: fieldName,
      type: 'candlestick',
      data: candleData,
      itemStyle: {
        color: UP_COLOR,
        color0: DOWN_COLOR,
        borderColor: UP_COLOR,
        borderColor0: DOWN_COLOR,
      },
    };
    closesForMA = bars.map((b) => b.close);
  } else {
    const lineData: [number, number | null][] = bars.map((b) => [tsOf(b), priceOf(b)]);
    mainSeries = {
      name: fieldName,
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      data: lineData,
      ...(chartType === 'area' ? { areaStyle: { opacity: 0.15 } } : {}),
    };
    closesForMA = bars.map((b) => priceOf(b));
  }

  // --- MA overlays (line series on the main grid) --------------------------
  const series: SeriesOption[] = [mainSeries];
  if (opts.ma?.ma5) {
    const ma5 = calcMA(closesForMA, 5);
    series.push({
      name: 'MA5',
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      lineStyle: { color: MA5_COLOR, width: 1 },
      data: bars.map((b, i) => [tsOf(b), ma5[i]]),
    });
  }
  if (opts.ma?.ma20) {
    const ma20 = calcMA(closesForMA, 20);
    series.push({
      name: 'MA20',
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      lineStyle: { color: MA20_COLOR, width: 1 },
      data: bars.map((b, i) => [tsOf(b), ma20[i]]),
    });
  }

  // --- Volume sub-chart (second grid, shared time axis) --------------------
  const hasVolume = showVolume && bars.some((b) => b.volume != null);
  if (hasVolume) {
    series.push({
      name: t('dashboard:priceChart.volume.label'),
      type: 'bar',
      xAxisIndex: 1,
      yAxisIndex: 1,
      // Per-bar colour by up/down day; null-volume days emit a gap.
      data: bars.map((b) => {
        const ts = tsOf(b);
        if (b.volume == null) return { value: [ts, null] };
        const up = (b.close ?? 0) >= (b.open ?? 0);
        return { value: [ts, b.volume], itemStyle: { color: up ? UP_COLOR : DOWN_COLOR } };
      }),
    });
  }

  // Tooltip renders one row per series at the hovered time; candle rows show OHLC.
  const tooltip: EChartsOption['tooltip'] = {
    trigger: 'axis',
    formatter: (params) => {
      const arr = Array.isArray(params) ? params : [params];
      const first = arr[0];
      const ms = first && Array.isArray(first.value) ? (first.value[0] as number) : null;
      if (ms == null) return '';
      const date = dayjs(ms).format('LL');
      const rows = arr
        .map((p) => {
          const v = (p as { value?: unknown }).value;
          const marker = (p.marker ?? '') as string;
          if (!Array.isArray(v)) return '';
          if (p.seriesType === 'candlestick') {
            const [, o, c, l, h] = v as number[];
            return `${marker} ${p.seriesName}<br/>O ${fmtNum(o)} | H ${fmtNum(h)} | L ${fmtNum(l)} | C ${fmtNum(c)}`;
          }
          const price = v[1] as number | null;
          return `${marker} ${p.seriesName}: ${price == null ? '—' : Number(price).toLocaleString()}`;
        })
        .filter(Boolean);
      return `${date}<br/>${rows.join('<br/>')}`;
    },
  };

  // legend lists main + MA only (volume sub-chart stays out of the legend).
  const legend = {
    data: series.filter((s) => s.type !== 'bar').map((s) => s.name as string),
    top: 0,
  };

  const dataZoom: EChartsOption['dataZoom'] = [{ type: 'inside' }];

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
        { type: 'time', gridIndex: 0 },
        { type: 'time', gridIndex: 1, axisLabel: { show: false } },
      ],
      yAxis: [
        { type: 'value', scale: true, gridIndex: 0 },
        { type: 'value', scale: true, gridIndex: 1, splitNumber: 2 },
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
    xAxis: { type: 'time' },
    yAxis: { type: 'value', scale: true },
    dataZoom,
    series,
  };
}
