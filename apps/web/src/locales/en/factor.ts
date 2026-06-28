/**
 * English — `factor` namespace (FRA-58).
 *
 * Factor research page copy: config form (universe / factor / window), the three
 * research actions (IC / quantile / sensitivity), visualizations (IC series +
 * summary cards, quantile curves + spread, sensitivity heatmap), async poll
 * status, and the one-page factor performance report + JSON/Markdown export
 * (FRA-77). Financial abbreviations (IC, ICIR, t-stat, p-value, Sharpe, bps)
 * and factor names (momentum_21, macd_hist, rsi_14) stay verbatim. Keep parity
 * with `zh-CN/factor.ts`; do not overstate predictive power; not investment
 * advice.
 */
const factor = {
  page: {
    title: 'Factor Research',
    description:
      'Pick a universe and a factor, then evaluate IC, quantile returns, and parameter sensitivity (research only, not investment advice).',
    empty: 'Choose a universe and a factor, then run an analysis.',
  },

  form: {
    watchlist: 'Universe',
    watchlistPlaceholder: 'Select a watchlist as the universe',
    factor: 'Factor',
    dateRange: 'Date range',
    nQuantiles: 'Quantiles',
    source: 'Source',
    priceField: 'Price field',
    run: 'Run',
    hint: 'Computation runs in a background worker (IC is an instant query).',
  },

  factors: {
    momentum_21: 'Momentum 21d',
    momentum_63: 'Momentum 63d',
    momentum_126: 'Momentum 126d',
    reversal_5: 'Reversal 5d',
    reversal_21: 'Reversal 21d',
    macd_hist: 'MACD histogram',
    rsi_14: 'RSI 14',
    volatility_20d: 'Volatility 20d',
    volatility_63d: 'Volatility 63d',
  },

  priceField: {
    adjusted: 'Adjusted',
    raw: 'Raw',
  },

  tabs: {
    ic: 'IC',
    ranking: 'Ranking',
    quantile: 'Quantile',
    sensitivity: 'Sensitivity',
    report: 'Report',
  },

  actions: {
    runIC: 'Compute IC',
    runQuantile: 'Run quantile backtest',
    runSensitivity: 'Run sensitivity sweep',
  },

  ic: {
    title: 'Information Coefficient (IC)',
    series: 'IC per period',
    mean: 'Mean IC',
    icir: 'ICIR',
    tStat: 't-stat',
    pValue: 'p-value',
    n: 'Periods',
    positiveRate: 'Positive rate',
    noData: 'No IC series yet — run the IC analysis first.',
    minUniverse:
      'IC analysis needs at least 2 assets (cross-sectional ranking) — add more to the universe.',
  },

  quantile: {
    title: 'Quantile return curves',
    bucket: 'Bucket {{n}}',
    spread: 'Top − Bottom spread',
    monotonicity: 'Monotonicity',
    noData: 'No quantile curves yet — run the quantile backtest first.',
  },

  ranking: {
    title: 'Cross-sectional ranking snapshot',
    snapshotDate: 'Date',
    latestValid: 'Latest valid',
    snapshotTime: 'Snapshot: {{date}}',
    noData:
      'No valid cross-section for this date/window — warmup or missing factor values are not filled.',
    minUniverse: 'Ranking needs at least 2 assets — add more to the universe.',
    columns: {
      symbol: 'Symbol',
      value: 'Factor value',
      rank: 'Rank',
      zScore: 'Z-score',
      bucket: 'Bucket',
    },
  },

  heatmap: {
    title: 'Parameter sensitivity heatmap',
    window: 'Window',
    cost: 'Cost',
    noData: 'No sensitivity data yet — run the sensitivity sweep first.',
    metric: {
      net_sharpe: 'Net Sharpe',
      gross_sharpe: 'Gross Sharpe',
    },
  },

  run: {
    triggered: 'Submitted — computing in the background…',
    polling: 'Computing — polling status…',
    success: 'Computation complete.',
    failed: 'Computation failed.',
    timeout: 'Timed out — please retry later.',
  },

  sweepUnsupported:
    'This factor does not support the sensitivity sweep (momentum / RSI / volatility only).',

  preflight: {
    title: 'Missing price data',
    body: 'These assets have insufficient price coverage in {{window}} (source: {{source}}). Sync them now?',
    coverage: 'coverage {{pct}}%',
    hint: 'Sync pulls bars from the data source; you will re-run the analysis once it completes.',
    syncButton: 'Sync data',
    syncDone: 'Data synced. Please re-run the analysis.',
    syncFailed: 'Some assets failed to sync.',
    syncTimeout: 'Sync timed out — please retry later.',
    enqueueFailed: 'failed to enqueue',
    rerunHint: 'Coverage is now updated — run the analysis again.',
    job: {
      queued: 'Queued',
      pending: 'Queued…',
      running: 'Syncing…',
      success: 'Done',
      success_no_data: 'No data',
      failed: 'Failed',
    },
  },

  report: {
    title: 'Factor performance report',
    intro:
      'A one-page summary of factor performance under the current configuration (historical simulation, not investment advice).',
    notRun: 'Not run',
    none: 'None',
    headings: {
      config: 'Configuration & assumptions',
      metrics: 'Performance summary',
      limitations: 'Limitations & disclaimer',
    },
    config: {
      factor: 'Factor',
      source: 'Source',
      window: 'Data window',
      universe: 'Universe size',
      horizon: 'IC horizon',
      nQuantiles: 'Quantiles',
      priceField: 'Price field',
      costBands: 'Cost bands (bps)',
    },
    metrics: {
      icSummary: 'IC summary',
      quantile: 'Quantile backtest',
      sensitivity: 'Sensitivity',
      monotonicity: 'Monotonicity',
      tmbEnding: 'Top−bottom ending value',
      bestSharpe: 'Best net Sharpe',
      worstSharpe: 'Worst net Sharpe',
      highImpactParams: 'High-impact params',
      noHighImpact: 'No high-impact params',
    },
    export: {
      json: 'Export JSON',
      markdown: 'Export Markdown',
    },
    limitations: {
      title: 'Limitations & disclaimer',
      icNotAlpha:
        'IC measures cross-sectional rank predictive power only — it excludes trading costs, slippage, market impact, capacity, and shortability. A statistically significant IC may vanish once costs and investability are accounted for.',
      shortWindow:
        'The default demo window (~1 year, small sample) leaves IC t-stats and quantile monotonicity unstable; picking optimal parameters on the sensitivity grid almost certainly overfits.',
      singleSource:
        'Data comes from yfinance, a single free source — possible split-adjustment errors, missing delisted data, and lag. Factor values and IC inherit all biases of that source.',
      survivorship:
        'The universe comes from the user watchlist; the system has no historical index constituents or delisted securities, so survivorship bias cannot be fully removed. Results are a historical simulation of the given stock set over the window only.',
      lookAhead:
        'System-internal factors are lookahead-safe via rolling windows + warmup NaN + a shift(1) boundary; future external / LLM-generated factors must separately guarantee their inputs contain no future data.',
      disclaimer: 'Historical simulation for research only — does not predict the future and is not investment advice.',
    },
  },
} as const;

export default factor;
