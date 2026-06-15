/**
 * Unit tests for the pure option builder `buildPriceChartOption` (FRA-11, FRA-24).
 *
 * No DOM / React context is needed: we drive the builder with fixtures and a
 * real i18next `getFixedT` so the i18n behavior is exercised (not mocked).
 * The resulting EChartsOption is asserted structurally.
 *
 * FRA-24 changed the x-axis from `time` to `category` (trading-day labels) so
 * non-trading days are hidden — the "timestamp" case now asserts the category
 * label, and line data is a plain per-index value array.
 */
import { describe, it, expect, beforeEach } from 'vitest';

import { buildPriceChartOption, calcMA } from '@/components/dashboard/priceChartOption';
import i18n from '@/i18n';
import type { OhlcvRead } from '@/types/api';

beforeEach(async () => {
  // Ensure a deterministic starting language; afterEach in setup resets to 'en'.
  await i18n.changeLanguage('en');
});

function makeBar(overrides: Partial<OhlcvRead> = {}): OhlcvRead {
  return {
    asset_id: 'a-1',
    time: '2024-01-01T00:00:00Z',
    source: 'yfinance',
    open: 10,
    high: 11,
    low: 9,
    close: 10,
    adjusted_close: 10,
    volume: 1000,
    ...overrides,
  };
}

describe('buildPriceChartOption', () => {
  it('uses adjusted_close for each data point when present', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const bars = [
      makeBar({ time: '2024-01-02T00:00:00Z', adjusted_close: 101.5 }),
      makeBar({ time: '2024-01-03T00:00:00Z', adjusted_close: 102.75 }),
    ];
    const option = buildPriceChartOption(bars, t);
    const series = option.series as [{ data: (number | null)[] }];
    expect(series[0].data[0]).toBe(101.5);
    expect(series[0].data[1]).toBe(102.75);
  });

  it('falls back to close when adjusted_close is null', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const bars = [makeBar({ time: '2024-01-02T00:00:00Z', adjusted_close: null, close: 50 })];
    const option = buildPriceChartOption(bars, t);
    const series = option.series as [{ data: (number | null)[] }];
    expect(series[0].data[0]).toBe(50);
  });

  it('emits a null y when both adjusted_close and close are null', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const bars = [
      makeBar({ time: '2024-01-02T00:00:00Z', adjusted_close: 1, close: 1 }),
      makeBar({ time: '2024-01-03T00:00:00Z', adjusted_close: null, close: null }),
      makeBar({ time: '2024-01-04T00:00:00Z', adjusted_close: 3, close: 3 }),
    ];
    const option = buildPriceChartOption(bars, t);
    const series = option.series as [{ data: (number | null)[] }];
    expect(series[0].data[1]).toBeNull();
  });

  it('sets legend.data and series[0].name to the translated field name (en)', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const bars = [makeBar()];
    const option = buildPriceChartOption(bars, t);
    const series = option.series as [{ name: string }];
    const legend = option.legend as { data: string[] };
    expect(series[0].name).toBe('Adjusted close');
    expect(legend.data).toEqual(['Adjusted close']);
  });

  it('reflects language change: legend name becomes the zh-CN translation', async () => {
    // English first.
    const tEn = i18n.getFixedT('en', 'dashboard');
    const optionEn = buildPriceChartOption([makeBar()], tEn);
    const legendEn = optionEn.legend as { data: string[] };
    expect(legendEn.data).toEqual(['Adjusted close']);

    // Switch language and rebuild with a fresh fixed-t.
    await i18n.changeLanguage('zh-CN');
    const tZh = i18n.getFixedT('zh-CN', 'dashboard');
    const optionZh = buildPriceChartOption([makeBar()], tZh);
    const legendZh = optionZh.legend as { data: string[] };
    expect(legendZh.data).toEqual(['复权收盘价']);
  });

  it('uses a category x-axis of trading days (YYYY-MM-DD), hiding non-trading days', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const iso = '2024-03-15T00:00:00Z';
    const bars = [makeBar({ time: iso, adjusted_close: 7 })];
    const option = buildPriceChartOption(bars, t);
    const xAxis = option.xAxis as { type: string; data: string[] };
    expect(xAxis.type).toBe('category');
    expect(xAxis.data).toEqual(['2024-03-15']);
    const series = option.series as [{ data: (number | null)[] }];
    expect(series[0].data[0]).toBe(7);
  });

  it('produces empty series.data for an empty bars array without throwing', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const option = buildPriceChartOption([], t);
    const series = option.series as [{ data: unknown[] }];
    expect(series[0].data).toEqual([]);
  });

  it('disables connectNulls so the line breaks across gaps', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const option = buildPriceChartOption([makeBar()], t);
    const series = option.series as [{ connectNulls: boolean }];
    expect(series[0].connectNulls).toBe(false);
  });
});

describe('buildPriceChartOption — chart types (FRA-24)', () => {
  it('candlestick: series[0] is candlestick with [open, close, low, high] tuples', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const bars = [
      makeBar({ time: '2024-01-02T00:00:00Z', open: 10, close: 12, high: 13, low: 9 }),
    ];
    const option = buildPriceChartOption(bars, t, { chartType: 'candle', adjust: 'raw' });
    const series = option.series as [
      { type: string; data: ([number, number, number, number] | null)[] },
    ];
    expect(series[0].type).toBe('candlestick');
    expect(series[0].data[0]).toEqual([10, 12, 9, 13]); // [open, close, low, high]
  });

  it('candlestick: drops bars with any null OHLC (keeps the gap-free axis)', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const bars = [
      makeBar({ time: '2024-01-02T00:00:00Z', open: 10, close: 12, high: 13, low: 9 }),
      makeBar({ time: '2024-01-03T00:00:00Z', open: null, close: 12, high: 13, low: 9 }),
    ];
    const option = buildPriceChartOption(bars, t, { chartType: 'candle' });
    const series = option.series as [{ data: unknown[] }];
    expect(series[0].data).toHaveLength(1);
  });

  it('area: line series carries an areaStyle', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const option = buildPriceChartOption([makeBar()], t, { chartType: 'area' });
    const series = option.series as [{ type: string; areaStyle?: unknown }];
    expect(series[0].type).toBe('line');
    expect(series[0].areaStyle).toBeDefined();
  });
});

describe('buildPriceChartOption — volume sub-chart (FRA-24)', () => {
  it('showVolume adds a second grid + a bar series on gridIndex 1', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const bars = [makeBar({ volume: 5000 })];
    const option = buildPriceChartOption(bars, t, { showVolume: true });
    expect(Array.isArray(option.grid)).toBe(true);
    expect((option.grid as unknown[]).length).toBe(2);
    const series = option.series as { type: string; xAxisIndex?: number }[];
    const volSeries = series.find((s) => s.type === 'bar');
    expect(volSeries).toBeDefined();
    expect(volSeries?.xAxisIndex).toBe(1);
  });

  it('default (no opts) keeps a single grid + no bar series', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const bars = [makeBar({ volume: 5000 })];
    const option = buildPriceChartOption(bars, t);
    expect(Array.isArray(option.grid)).toBe(false);
    const series = option.series as { type: string }[];
    expect(series.some((s) => s.type === 'bar')).toBe(false);
  });

  it('volume is omitted when every bar has null volume even with showVolume=true', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const bars = [makeBar({ volume: null })];
    const option = buildPriceChartOption(bars, t, { showVolume: true });
    expect(Array.isArray(option.grid)).toBe(false);
  });
});

describe('buildPriceChartOption — MA overlays (FRA-24)', () => {
  it('ma.ma5 adds an MA5 line series', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const bars = Array.from({ length: 6 }, (_, i) =>
      makeBar({
        time: `2024-01-0${i + 2}T00:00:00Z`,
        close: 10 + i,
        adjusted_close: 10 + i,
      }),
    );
    const option = buildPriceChartOption(bars, t, { ma: { ma5: true } });
    const series = option.series as { name: string; type: string }[];
    expect(series.some((s) => s.name === 'MA5')).toBe(true);
  });

  it('legend excludes the volume bar series', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const bars = [makeBar({ volume: 5000 })];
    const option = buildPriceChartOption(bars, t, { showVolume: true, ma: { ma20: true } });
    const legend = option.legend as { data: string[] };
    expect(legend.data).not.toContain('Volume');
  });
});

describe('buildPriceChartOption — adjust toggle (FRA-24)', () => {
  it('adjust=raw uses close instead of adjusted_close for line', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const bars = [makeBar({ time: '2024-01-02T00:00:00Z', close: 40, adjusted_close: 99 })];
    const option = buildPriceChartOption(bars, t, { adjust: 'raw' });
    const series = option.series as [{ data: (number | null)[] }];
    expect(series[0].data[0]).toBe(40);
  });

  it('adjust=adjusted back-adjusts candle OHLC by the adjusted_close/close ratio', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    // adjusted_close=40, close=20 → ratio 2 → every OHLC value doubled.
    const bars = [
      makeBar({
        time: '2024-01-02T00:00:00Z',
        open: 10,
        close: 20,
        high: 22,
        low: 9,
        adjusted_close: 40,
      }),
    ];
    const optionRaw = buildPriceChartOption(bars, t, { chartType: 'candle', adjust: 'raw' });
    const optionAdj = buildPriceChartOption(bars, t, {
      chartType: 'candle',
      adjust: 'adjusted',
    });
    const sRaw = (optionRaw.series as [
      { data: ([number, number, number, number] | null)[] },
    ])[0];
    const sAdj = (optionAdj.series as [
      { data: ([number, number, number, number] | null)[] },
    ])[0];
    // raw keeps original OHLC; adjusted scales by ratio=2 → [o*2, c*2, l*2, h*2].
    expect(sRaw.data[0]).toEqual([10, 20, 9, 22]);
    expect(sAdj.data[0]).toEqual([20, 40, 18, 44]);
  });
});

describe('calcMA (FRA-24)', () => {
  it('returns the running average, null for the first period-1 entries', () => {
    expect(calcMA([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
  });

  it('returns null for any window containing a null', () => {
    expect(calcMA([1, null, 3, 4, 5], 3)).toEqual([null, null, null, null, 4]);
  });

  it('returns all nulls when data is shorter than the period', () => {
    expect(calcMA([1, 2], 5)).toEqual([null, null]);
  });

  it('returns an empty array for empty input', () => {
    expect(calcMA([], 3)).toEqual([]);
  });
});
