/**
 * English — `dashboard` namespace.
 *
 * Dashboard / overview page strings. Numbers are formatted at runtime via
 * Intl/locale-aware helpers, never inlined here. Financial abbreviations
 * (OHLCV, ETF, Sharpe, NASDAQ) kept as-is.
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
} as const;

export default dashboard;
