/**
 * Unit tests for the pure backtest option builders (FRA-38).
 *
 * No DOM / React context: drive the builders with fixtures and a real i18next
 * `getFixedT` (matching `priceChartOption.test.ts`), asserting the resulting
 * EChartsOption structurally. Drawdown is `equity / cummax - 1` ≤ 0; the y-axis
 * and tooltip format it as a percent.
 */
import { beforeEach, describe, expect, it } from 'vitest';

import {
  buildDrawdownOption,
  buildEquityCurveOption,
} from '@/components/backtest/equityChartOption';
import i18n from '@/i18n';
import type { EquityCurvePointRead } from '@/types/api';

beforeEach(async () => {
  // Deterministic starting language; the i18n setup resets to 'en' afterEach.
  await i18n.changeLanguage('en');
});

function makePoint(overrides: Partial<EquityCurvePointRead> = {}): EquityCurvePointRead {
  return {
    backtest_run_id: 'run-1',
    series_kind: 'strategy',
    time: '2024-01-02T00:00:00Z',
    equity: 100000,
    daily_return: 0,
    drawdown: 0,
    ...overrides,
  };
}

describe('buildEquityCurveOption', () => {
  it('maps strategy equity to series[0].data aligned to the day category axis', () => {
    const t = i18n.getFixedT('en', 'backtest');
    const option = buildEquityCurveOption(
      [
        makePoint({ time: '2024-01-02T00:00:00Z', equity: 100000 }),
        makePoint({ time: '2024-01-03T00:00:00Z', equity: 101000 }),
      ],
      t,
    );
    const xAxis = option.xAxis as { type: string; data: string[] };
    expect(xAxis.type).toBe('category');
    expect(xAxis.data).toEqual(['2024-01-02', '2024-01-03']);
    const series = option.series as [{ data: (number | null)[] }];
    expect(series[0].data).toEqual([100000, 101000]);
  });

  it('adds a benchmark series only when benchmark points exist', () => {
    const t = i18n.getFixedT('en', 'backtest');
    const strat = [
      makePoint({ time: '2024-01-02T00:00:00Z', equity: 100000 }),
      makePoint({ time: '2024-01-03T00:00:00Z', equity: 101000 }),
    ];
    // no benchmark → single series
    expect((buildEquityCurveOption(strat, t).series as unknown[]).length).toBe(1);

    // benchmark present only on 01-03 → prefix gap renders as null on 01-02
    const withBench = buildEquityCurveOption(
      [
        ...strat,
        makePoint({ series_kind: 'benchmark', time: '2024-01-03T00:00:00Z', equity: 99500 }),
      ],
      t,
    );
    const series = withBench.series as [{ data: (number | null)[] }, { data: (number | null)[] }];
    expect(series.length).toBe(2);
    expect(series[1].data).toEqual([null, 99500]);
  });

  it('uses translated strategy/benchmark names in series + legend', () => {
    const t = i18n.getFixedT('en', 'backtest');
    const option = buildEquityCurveOption(
      [
        makePoint({ time: '2024-01-02T00:00:00Z', equity: 1 }),
        makePoint({ series_kind: 'benchmark', time: '2024-01-02T00:00:00Z', equity: 1 }),
      ],
      t,
    );
    const series = option.series as [{ name: string }, { name: string }];
    const legend = option.legend as { data: string[] };
    expect(series[0].name).toBe('Strategy');
    expect(series[1].name).toBe('Benchmark');
    expect(legend.data).toEqual(['Strategy', 'Benchmark']);
  });

  it('handles an empty points array without throwing', () => {
    const t = i18n.getFixedT('en', 'backtest');
    const option = buildEquityCurveOption([], t);
    const series = option.series as [{ data: unknown[] }];
    expect(series[0].data).toEqual([]);
  });
});

describe('buildDrawdownOption', () => {
  it('maps strategy drawdown (≤ 0) to series[0].data with an area fill', () => {
    const t = i18n.getFixedT('en', 'backtest');
    const option = buildDrawdownOption(
      [
        makePoint({ time: '2024-01-02T00:00:00Z', drawdown: 0 }),
        makePoint({ time: '2024-01-03T00:00:00Z', drawdown: -0.05 }),
      ],
      t,
    );
    const series = option.series as [{ data: (number | null)[]; areaStyle?: unknown }];
    expect(series[0].data).toEqual([0, -0.05]);
    expect(series[0].areaStyle).toBeDefined();
  });

  it('formats the y-axis label and tooltip value as a percent', () => {
    const t = i18n.getFixedT('en', 'backtest');
    const option = buildDrawdownOption([makePoint({ drawdown: -0.123 })], t);
    const yAxis = option.yAxis as { axisLabel: { formatter: (v: number) => string } };
    expect(yAxis.axisLabel.formatter(-0.1)).toBe('-10%');
    const tooltip = option.tooltip as unknown as {
      valueFormatter: (value: number | null) => string;
    };
    expect(tooltip.valueFormatter(-0.05)).toBe('-5.00%');
    expect(tooltip.valueFormatter(null)).toBe('—');
  });

  it('reflects a language change for the series name', async () => {
    const tEn = i18n.getFixedT('en', 'backtest');
    const optionEn = buildDrawdownOption([makePoint()], tEn);
    expect((optionEn.series as [{ name: string }])[0].name).toBe('Strategy');

    await i18n.changeLanguage('zh-CN');
    const tZh = i18n.getFixedT('zh-CN', 'backtest');
    const optionZh = buildDrawdownOption([makePoint()], tZh);
    expect((optionZh.series as [{ name: string }])[0].name).toBe('策略');
  });
});
