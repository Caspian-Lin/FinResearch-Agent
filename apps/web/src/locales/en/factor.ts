/**
 * English — `factor` namespace (FRA-58).
 *
 * Factor research page copy: config form (universe / factor / window), the three
 * research actions (IC / quantile / sensitivity), visualizations (IC series +
 * summary cards, quantile curves + spread, sensitivity heatmap), and async poll
 * status. Financial abbreviations (IC, ICIR, t-stat, p-value, Sharpe, bps) and
 * factor names (momentum_21, macd_hist, rsi_14) stay verbatim. Keep parity with
 * `zh-CN/factor.ts`; do not overstate predictive power; not investment advice.
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
} as const;

export default factor;
