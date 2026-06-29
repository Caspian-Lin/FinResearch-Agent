/**
 * English — `common` namespace.
 *
 * Generic UI strings shared across pages: app name, navigation, actions,
 * generic status labels, and the project-wide risk disclaimer.
 *
 * NOTE: keep keys and intent in sync with `zh-CN/common.ts`. Financial
 * abbreviations (OHLCV, ETF, API) and currency/symbol codes (USD) are
 * intentionally NOT translated.
 */

const common = {
  appName: 'FinResearch Agent',
  version: 'v0.1.0',
  tagline: 'LLM-powered Financial Research and Backtesting System',

  nav: {
    dashboard: 'Dashboard',
    watchlist: 'Watchlist',
    newBacktest: 'New Backtest',
    backtestHistory: 'Backtest History',
    factorResearch: 'Factor Research',
    memos: 'Research Memos',
    settings: 'Settings',
  },

  actions: {
    save: 'Save',
    cancel: 'Cancel',
    confirm: 'Confirm',
    delete: 'Delete',
    edit: 'Edit',
    add: 'Add',
    refresh: 'Refresh',
    close: 'Close',
    retry: 'Retry',
    loading: 'Loading…',
  },

  status: {
    online: 'Online',
    offline: 'Offline',
    pending: 'Pending',
    running: 'Running',
    completed: 'Completed',
    failed: 'Failed',
  },

  language: {
    label: 'Language',
    english: 'English',
    chineseSimplified: '简体中文',
  },

  theme: {
    label: 'Theme',
    light: 'Light',
    dark: 'Dark',
  },

  /** Project-wide risk disclaimer. Must appear in both languages verbatim in intent. */
  disclaimer: {
    title: 'Important Disclaimer',
    body: 'FinResearch Agent is a research and reproducibility tool. It is NOT an automated trading bot, does not connect to brokerages, and does not guarantee profit. Any output is bound to a stated data window, asset universe, and assumptions. This is not investment advice.',
  },
} as const;

export default common;
