/**
 * English — `backtest` namespace (FRA-38).
 *
 * Backtest page copy: config form, result visualization (equity / drawdown /
 * metrics / trades), polling status, and the recent-runs list. Financial
 * abbreviations (MA, bps) and symbol/currency codes (QQQ, SPY, USD) are NOT
 * translated. Keep keys in sync with `zh-CN/backtest.ts`.
 */
const backtest = {
  page: {
    title: 'Backtest',
    description:
      'Configure a strategy, run it over a window, and inspect equity, drawdown, metrics, and trades.',
    empty: 'Run a backtest to see results.',
  },

  equity: {
    title: 'Equity curve',
    strategy: 'Strategy',
    benchmark: 'Benchmark',
    noData: 'No equity curve yet — run a backtest first.',
  },

  drawdown: {
    title: 'Drawdown',
    noData: 'No drawdown curve yet — run a backtest first.',
  },

  metrics: {
    title: 'Performance metrics',
    gross: 'Gross (pre-cost)',
    net: 'Net (post-cost)',
    annual_return: 'Annual return',
    volatility: 'Volatility',
    sharpe_ratio: 'Sharpe',
    max_drawdown: 'Max drawdown',
    calmar_ratio: 'Calmar',
    turnover: 'Turnover',
    win_rate: 'Win rate',
    beta: 'Beta',
    correlation: 'Correlation',
  },

  trades: {
    title: 'Trades',
    empty: 'No trades recorded.',
    columns: {
      time: 'Date',
      asset: 'Asset',
      side: 'Side',
      quantity: 'Quantity',
      price: 'Price',
      cost: 'Cost',
    },
    side: { buy: 'Buy', sell: 'Sell' },
  },

  form: {
    title: 'Configuration',
    name: 'Run name',
    watchlist: 'Universe (watchlist)',
    watchlistPlaceholder: 'Select a watchlist',
    strategy: 'Strategy',
    dateRange: 'Date range',
    benchmark: 'Benchmark (optional)',
    benchmarkPlaceholder: 'Search QQQ / SPY …',
    initialCapital: 'Initial capital',
    costBps: 'Cost (bps)',
    rebalance: 'Rebalance',
    priceField: 'Price field',
    run: 'Run backtest',
    hint: 'Backtests are simulations; this is not investment advice.',
  },

  strategy: {
    buy_hold: 'Buy & hold',
    equal_weight: 'Equal weight',
    ma_crossover: 'MA crossover',
    momentum: 'Momentum',
    reversal: 'Reversal',
    params: {
      fast: 'Fast MA',
      slow: 'Slow MA',
      lookback: 'Lookback (days)',
      topK: 'Top K',
      bottomK: 'Bottom K',
    },
  },

  rebalance: { daily: 'Daily', weekly: 'Weekly', monthly: 'Monthly' },
  priceField: { adjusted: 'Adjusted', raw: 'Raw' },

  status: {
    pending: 'Queued',
    running: 'Running',
    success: 'Done',
    failed: 'Failed',
  },

  run: {
    new: 'New backtest',
    triggered: 'Backtest queued.',
    polling: 'Running backtest…',
    success: 'Backtest complete.',
    failed: 'Backtest failed.',
    timeout: 'Backtest is still running — refresh later to see results.',
  },

  history: {
    title: 'Recent runs',
    empty: 'No past runs.',
    run: 'Run',
    strategy: 'Strategy',
    status: 'Status',
    created: 'Created',
  },

  preflight: {
    title: 'Missing price data',
    body: 'These assets have insufficient price coverage in {{window}} (source: {{source}}). Sync them now?',
    coverage: 'coverage {{pct}}%',
    hint: 'Sync pulls bars from the data source; you will re-run the backtest once it completes.',
    syncButton: 'Sync data',
    syncDone: 'Data synced. Please re-run the backtest.',
    syncFailed: 'Some assets failed to sync.',
    syncTimeout: 'Sync timed out — please retry later.',
    enqueueFailed: 'failed to enqueue',
    rerunHint: 'Coverage is now updated — click "Run backtest" again.',
    job: {
      queued: 'Queued',
      pending: 'Queued…',
      running: 'Syncing…',
      success: 'Done',
      failed: 'Failed',
    },
  },
} as const;

export default backtest;
