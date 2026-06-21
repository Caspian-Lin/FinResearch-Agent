/**
 * Unit tests for the pure factor option builders (FRA-58).
 *
 * No DOM / React context: drive the builders with fixtures and a real i18next
 * `getFixedT`, asserting the resulting EChartsOption structurally. Mirrors
 * `backtest/__tests__/equityChartOption.test.ts`.
 */
import { beforeEach, describe, expect, it } from 'vitest';

import { buildHeatmapOption } from '@/components/factor/heatmapOption';
import { buildICOption } from '@/components/factor/icChartOption';
import { buildQuantileOption } from '@/components/factor/quantileChartOption';
import i18n from '@/i18n';
import type { QuantileResult, TimeSeriesPoint } from '@/types/api';

beforeEach(async () => {
  await i18n.changeLanguage('en');
});

function tsPoint(day: number, value: number): TimeSeriesPoint {
  const d = `2024-01-${String(day).padStart(2, '0')}T00:00:00Z`;
  return { time: d, value };
}

describe('buildICOption', () => {
  it('renders per-period IC as bars with an average markLine on a category axis', () => {
    const t = i18n.getFixedT('en', 'factor');
    const series = [tsPoint(2, 0.1), tsPoint(3, -0.05), tsPoint(4, 0.2)];
    const option = buildICOption(series, t);
    const xAxis = option.xAxis as { type: string; data: string[] };
    expect(xAxis.type).toBe('category');
    expect(xAxis.data).toHaveLength(3);
    const s = option.series as [{ type: string; data: { value: number }[]; markLine: unknown }];
    expect(s[0].type).toBe('bar');
    expect(s[0].data).toHaveLength(3);
    expect(s[0].markLine).toBeDefined();
  });
});

describe('buildQuantileOption', () => {
  it('emits one line per bucket plus the top−bottom spread', () => {
    const t = i18n.getFixedT('en', 'factor');
    const data: QuantileResult = {
      quantile_equity: {
        '1': [tsPoint(2, 0.98)],
        '2': [tsPoint(2, 1.0)],
        '3': [tsPoint(2, 1.02)],
      },
      top_minus_bottom: [tsPoint(2, 0.04)],
      monotonicity: 1.0,
    };
    const option = buildQuantileOption(data, t);
    const series = option.series as { name: string; type: string }[];
    // 3 buckets + 1 spread.
    expect(series).toHaveLength(4);
    expect(series.every((s) => s.type === 'line')).toBe(true);
    const legend = option.legend as { data: string[] };
    expect(legend.data).toHaveLength(4);
  });
});

describe('buildHeatmapOption', () => {
  it('lays out window × cost cells of net Sharpe with a visualMap', () => {
    const t = i18n.getFixedT('en', 'factor');
    const rows = [
      { params: { window: 21, factor: 'momentum' }, cost_bps: 0, net_sharpe: 1.2 },
      { params: { window: 21, factor: 'momentum' }, cost_bps: 10, net_sharpe: 0.8 },
      { params: { window: 63, factor: 'momentum' }, cost_bps: 0, net_sharpe: 0.5 },
    ];
    const option = buildHeatmapOption(rows, t);
    const xAxis = option.xAxis as { data: string[] };
    const yAxis = option.yAxis as { data: string[] };
    expect(xAxis.data).toEqual(['21', '63']);
    expect(yAxis.data).toEqual(['0', '10']);
    const s = option.series as [{ type: string; data: number[][] }];
    expect(s[0].type).toBe('heatmap');
    // 3 unique (window, cost) cells.
    expect(s[0].data).toHaveLength(3);
    expect(option.visualMap).toBeDefined();
  });

  it('handles an empty metric table without throwing', () => {
    const t = i18n.getFixedT('en', 'factor');
    const option = buildHeatmapOption([], t);
    const s = option.series as [{ data: number[][] }];
    expect(s[0].data).toHaveLength(0);
  });
});
