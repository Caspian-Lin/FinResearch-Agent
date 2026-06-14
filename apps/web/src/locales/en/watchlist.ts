/**
 * English — `watchlist` namespace.
 *
 * Watchlist page UI strings. Symbols (e.g. AAPL, QQQ) and currency codes
 * (USD) are intentionally never translated.
 */

const watchlist = {
  title: 'Watchlist',
  empty: 'Your watchlist is empty. Add a symbol to get started.',
  addSymbol: {
    label: 'Symbol',
    placeholder: 'e.g. AAPL',
    submit: 'Add to watchlist',
  },
  columns: {
    symbol: 'Symbol',
    name: 'Name',
    type: 'Type',
    lastClose: 'Last close',
    currency: 'Currency',
    updatedAt: 'Updated',
  },
  /** Asset-type display names. Symbols (ETF, etc.) kept as-is. */
  assetType: {
    stock: 'Stock',
    etf: 'ETF',
    index: 'Index',
  },
} as const;

export default watchlist;
