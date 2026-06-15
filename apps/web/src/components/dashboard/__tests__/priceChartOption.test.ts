/**
 * Unit tests for the pure option builder `buildPriceChartOption` (FRA-11).
 *
 * No DOM / React context is needed: we drive the builder with fixtures and a
 * real i18next `getFixedT` so the i18n behavior is exercised (not mocked).
 * The resulting EChartsOption is asserted structurally.
 */
import { describe, it, expect, beforeEach } from 'vitest';

import { buildPriceChartOption } from '@/components/dashboard/priceChartOption';
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
    const series = option.series as [{ data: [number, number | null][] }];
    expect(series[0].data[0][1]).toBe(101.5);
    expect(series[0].data[1][1]).toBe(102.75);
  });

  it('falls back to close when adjusted_close is null', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const bars = [
      makeBar({ time: '2024-01-02T00:00:00Z', adjusted_close: null, close: 50 }),
    ];
    const option = buildPriceChartOption(bars, t);
    const series = option.series as [{ data: [number, number | null][] }];
    expect(series[0].data[0][1]).toBe(50);
  });

  it('emits a null y when both adjusted_close and close are null', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const bars = [
      makeBar({ time: '2024-01-02T00:00:00Z', adjusted_close: 1, close: 1 }),
      makeBar({ time: '2024-01-03T00:00:00Z', adjusted_close: null, close: null }),
      makeBar({ time: '2024-01-04T00:00:00Z', adjusted_close: 3, close: 3 }),
    ];
    const option = buildPriceChartOption(bars, t);
    const series = option.series as [{ data: [number, number | null][] }];
    expect(series[0].data[1][1]).toBeNull();
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

  it('emits series.data timestamp as epoch ms via dayjs(time).valueOf()', () => {
    const t = i18n.getFixedT('en', 'dashboard');
    const iso = '2024-03-15T00:00:00Z';
    const bars = [makeBar({ time: iso, adjusted_close: 7 })];
    const option = buildPriceChartOption(bars, t);
    const series = option.series as [{ data: [number, number | null][] }];
    const [ms, price] = series[0].data[0];
    // dayjs parses the ISO string to epoch ms; just assert it is a number and
    // corresponds to the same instant (non-zero, plausible 2024 range).
    expect(typeof ms).toBe('number');
    expect(ms).toBe(new Date(iso).getTime());
    expect(price).toBe(7);
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
