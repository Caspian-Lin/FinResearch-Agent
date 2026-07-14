/**
 * English — `dashboard` namespace.
 *
 * Dashboard / overview page strings. Numbers are formatted at runtime via
 * Intl/locale-aware helpers, never inlined here. Financial abbreviations
 * (OHLCV, ETF, Sharpe, NASDAQ) and source codes (yfinance) kept as-is.
 */

const dashboard = {
  welcome: {
    title: 'Welcome to FinResearch Agent',
    intro:
      'This is a scaffold shell. Real dashboard pages (watchlists, OHLCV viewer, data quality, backtests, memos) will be added in subsequent commits per the Week 1 roadmap.',
  },
  scaffolding: {
    tag: 'Week 1 scaffold',
    backendApi: 'Backend API',
    apiDocs: 'API docs (OpenAPI)',
    healthProbe: 'Health probe',
  },
  metrics: {
    sectionTitle: 'Key metrics',
    annualReturn: 'Annual return',
    volatility: 'Volatility',
    sharpeRatio: 'Sharpe ratio',
    maxDrawdown: 'Max drawdown',
    benchmark: 'Benchmark',
  },
  dataWindow: {
    label: 'Data window',
    /** Interpolation: {{start}}, {{end }} */
    range: '{{start}} → {{end}}',
  },

  page: {
    title: 'Dashboard',
  },

  noSelection: {
    message: 'Select an asset from your watchlist to view its dashboard.',
    link: 'Go to watchlist',
  },

  /** Dashboard sidebar (FRA-45) — pick an asset without leaving the page. */
  sidebar: {
    title: 'Watchlists',
    /** Narrow-screen button that opens the sidebar drawer. */
    toggle: 'Select stock',
    /** Accessible label + placeholder for the watchlist switcher. */
    switch: 'Switch watchlist',
    empty: {
      assets: 'No assets in this watchlist.',
    },
    manage: 'Manage watchlists',
  },

  filters: {
    source: 'Source',
    dateRange: 'Date range',
    chartType: 'Chart type',
  },

  // Data-source picker options (FRA-23). akshare/tushare serve A-shares only.
  sources: {
    yfinance: 'yfinance',
    akshare: 'AkShare',
    tushare: 'Tushare',
  },

  priceChart: {
    title: 'Price',
    field: {
      adjustedClose: 'Adjusted close',
      close: 'Close',
    },
    /** Note shown under the chart explaining the close-price fallback. */
    fallbackNote: 'Adjusted close, falling back to close when missing.',
    noData: 'No price data for the selected window.',
    chartType: {
      line: 'Line',
      candle: 'Candle',
      area: 'Area',
    },
    volume: {
      label: 'Volume',
    },
    ma: {
      label: 'Moving avg',
      ma5: 'MA5',
      ma20: 'MA20',
    },
    adjust: {
      label: 'Adjust',
      adjusted: 'Adjusted',
      raw: 'Raw',
    },
    size: {
      label: 'Height',
      small: 'Small',
      medium: 'Medium',
      large: 'Large',
    },
  },

  quality: {
    title: 'Data quality',
    coverage: 'Coverage',
    expected: 'Expected sessions',
    observed: 'Observed sessions',
    missing: {
      title: 'Missing sessions',
      /** Interpolation: {{count}} — how many more are hidden. */
      more: '+{{count}} more',
    },
    anomalies: {
      title: 'Anomalies',
      /** Interpolation: {{count}}. */
      count: '{{count}} detected',
      empty: 'No anomalies detected.',
    },
    rules: {
      non_positive_price: 'Non-positive price',
      high_lt_low: 'High below low',
      negative_volume: 'Negative volume',
      zero_volume: 'Zero volume',
      large_return: 'Abnormally large return',
    },
  },

  sync: {
    button: 'Sync data',
    status: {
      pending: 'Queued…',
      running: 'Syncing…',
      success: 'Sync complete. Refreshing data…',
      success_no_data:
        'Sync finished, but the data source returned no bars. It may be rate-limited; retry later or choose another source.',
      failed: 'Sync failed.',
    },
    /** Shown when the poll cap is reached without a terminal status. */
    timeout: 'Sync is taking longer than expected. Please check back later.',
    limit: {
      /** Shown when the chosen window exceeds the 1825-day backend limit. */
      window: 'The selected window exceeds the 1825-day sync limit.',
    },
  },

  /**
   * Data-limitations notice. Per AGENTS.md financial-safety requirements this
   * must be presented fully and honestly in both languages; not investment
   * advice.
   */
  dataLimit: {
    title: 'Data limitations',
    body: 'Market data is sourced from yfinance and may be delayed or incomplete. Quality statistics are computed against each exchange’s published trading calendar and are intended as a data-health reference only. Coverage and anomaly figures are indicative, not exhaustive. This is not investment advice.',
  },

  loading: 'Loading…',
} as const;

export default dashboard;
