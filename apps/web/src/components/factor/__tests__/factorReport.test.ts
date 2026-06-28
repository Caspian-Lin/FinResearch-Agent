/**
 * factorReport.ts unit tests (FRA-77).
 *
 * The report builders are pure functions over the page's existing research
 * results + config, so we feed hand-built inputs and assert structure / key
 * content rather than DOM output. `downloadText` is exercised against the jsdom
 * URL + anchor primitives it relies on.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  buildFactorReportJson,
  buildFactorReportMarkdown,
  downloadText,
  highImpactParams,
  topMinusBottomEndingValue,
  type FactorReportConfig,
  type FactorReportInput,
  type FactorReportLabels,
} from '@/components/factor/factorReport';
import type { ICResult, QuantileResult, SensitivitySummary } from '@/types/api';

const config: FactorReportConfig = {
  factor: 'momentum_21',
  source: 'yfinance',
  start: '2025-01-01',
  end: '2025-12-31',
  universeSize: 5,
  priceField: 'adjusted',
  nQuantiles: 5,
  horizon: 5,
  costBands: [0, 5, 10, 25],
};

const ic: ICResult = {
  series: [{ time: '2025-01-01', value: 0.03 }],
  summary: { mean: 0.03, icir: 0.5, t_stat: 2.1, p_value: 0.04, n: 100, positive_rate: 0.55 },
};

const quantile: QuantileResult = {
  quantile_equity: { '1': [], '5': [] },
  top_minus_bottom: [
    { time: '2025-01-01', value: 1.05 },
    { time: '2025-06-01', value: 1.1 },
  ],
  monotonicity: 0.8,
};

const sensitivity: SensitivitySummary = {
  metric_table: [],
  param_impacts: [
    { param: 'window', normalized_range: 0.3, absolute_range: 0.4, high_impact: true },
    { param: 'cost', normalized_range: 0.1, absolute_range: 0.1, high_impact: false },
  ],
  highly_sensitive: true,
  best_net_sharpe: 1.2,
  worst_net_sharpe: -0.3,
};

const labels: FactorReportLabels = {
  title: 'Report',
  configHeading: 'Config',
  metricsHeading: 'Metrics',
  limitationsHeading: 'Limitations',
  configFactor: 'Factor',
  configSource: 'Source',
  configWindow: 'Window',
  configUniverse: 'Universe',
  configHorizon: 'Horizon',
  configNQuantiles: 'Quantiles',
  configPriceField: 'Price',
  configCostBands: 'Cost bands',
  icSummary: 'IC summary',
  quantileHeading: 'Quantile',
  sensitivityHeading: 'Sensitivity',
  quantileMonotonicity: 'Monotonicity',
  tmbEnding: 'TMB ending',
  bestSharpe: 'Best Sharpe',
  worstSharpe: 'Worst Sharpe',
  highImpactParams: 'High-impact',
  icMean: 'Mean IC',
  icIcir: 'ICIR',
  icTStat: 't-stat',
  icPValue: 'p-value',
  icN: 'Periods',
  icPositiveRate: 'Positive rate',
  notRun: 'n/a',
  none: 'none',
  limitations: ['limA', 'limB'],
  disclaimer: 'disclaimer text',
};

describe('topMinusBottomEndingValue', () => {
  it('returns the last series value', () => {
    expect(topMinusBottomEndingValue(quantile)).toBe(1.1);
  });

  it('returns null for an empty series', () => {
    expect(topMinusBottomEndingValue({ ...quantile, top_minus_bottom: [] })).toBeNull();
  });

  it('returns null when quantile is null', () => {
    expect(topMinusBottomEndingValue(null)).toBeNull();
  });
});

describe('highImpactParams', () => {
  it('keeps only high-impact param names', () => {
    expect(highImpactParams(sensitivity)).toEqual(['window']);
  });

  it('returns an empty list for null sensitivity', () => {
    expect(highImpactParams(null)).toEqual([]);
  });
});

describe('buildFactorReportJson', () => {
  const full: FactorReportInput = { config, ic, quantile, sensitivity };

  it('emits config / ic / quantile / sensitivity sections', () => {
    const json = buildFactorReportJson(full);
    expect(json).toHaveProperty('config');
    expect(json).toHaveProperty('ic');
    expect(json).toHaveProperty('quantile');
    expect(json).toHaveProperty('sensitivity');
  });

  it('binds the tmb ending value and best/worst Sharpe', () => {
    const json = buildFactorReportJson(full);
    const q = json.quantile as Record<string, unknown>;
    const s = json.sensitivity as Record<string, unknown>;
    expect(q.top_minus_bottom_ending_value).toBe(1.1);
    expect(q.monotonicity).toBe(0.8);
    expect(s.best_net_sharpe).toBe(1.2);
    expect(s.worst_net_sharpe).toBe(-0.3);
    expect(s.high_impact_params).toEqual(['window']);
  });

  it('nulls out sections that were not run', () => {
    const json = buildFactorReportJson({ config: null, ic: null, quantile: null, sensitivity: null });
    expect(json.config).toBeNull();
    expect(json.ic).toBeNull();
    expect(json.quantile).toBeNull();
    expect(json.sensitivity).toBeNull();
  });
});

describe('buildFactorReportMarkdown', () => {
  it('embeds the factor name, data window, formatted metrics, and disclaimer', () => {
    const md = buildFactorReportMarkdown({ config, ic, quantile, sensitivity }, labels);
    expect(md).toContain('momentum_21');
    expect(md).toContain('2025-01-01 → 2025-12-31');
    expect(md).toContain('1.1000'); // top−bottom ending value, 4 digits
    expect(md).toContain('1.200'); // best net Sharpe, 3 digits
    expect(md).toContain('-0.300'); // worst net Sharpe, 3 digits
    expect(md).toContain('disclaimer text');
    expect(md).toContain('limA');
  });

  it('renders the "not run" placeholder for every missing section', () => {
    const md = buildFactorReportMarkdown(
      { config: null, ic: null, quantile: null, sensitivity: null },
      labels,
    );
    // Four sections each emit one "not run" line: config + ic + quantile + sensitivity.
    expect(md.match(/n\/a/g)).toHaveLength(4);
  });
});

describe('downloadText', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('creates an object URL, clicks an anchor, and revokes', () => {
    const createURL = vi.fn(() => 'blob:test');
    const revokeURL = vi.fn();
    vi.stubGlobal('URL', { createObjectURL: createURL, revokeObjectURL: revokeURL });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    downloadText('report.json', '{}', 'application/json');

    expect(createURL).toHaveBeenCalledOnce();
    expect(clickSpy).toHaveBeenCalledOnce();
    expect(revokeURL).toHaveBeenCalledWith('blob:test');
  });
});
