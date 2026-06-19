/**
 * English — `watchlist` namespace.
 *
 * Watchlist page UI strings covering multi-watchlist management and asset
 * search/add/remove. Symbols (e.g. AAPL, QQQ), exchange codes (NASDAQ) and
 * currency codes (USD) are intentionally never translated — they are runtime
 * data interpolated at the call site, never inlined here.
 */

const watchlist = {
  title: 'Watchlist',
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
    exchange: 'Exchange',
    addedAt: 'Added',
    actions: 'Actions',
  },
  /** Asset-type display names. Symbols (ETF, etc.) kept as-is. */
  assetType: {
    stock: 'Stock',
    etf: 'ETF',
    index: 'Index',
  },

  /** Page-level UI. */
  page: {
    title: 'Watchlists',
  },
  loading: 'Loading…',

  /** Empty states. */
  empty: {
    watchlists: 'You have no watchlists yet. Create one to start tracking assets.',
    assets: 'This watchlist is empty. Add an asset to start tracking it.',
  },

  /** Create-watchlist modal & button. */
  create: {
    button: 'New watchlist',
    modal: {
      title: 'Create watchlist',
    },
    form: {
      name: {
        label: 'Name',
        placeholder: 'e.g. Tech majors',
      },
    },
    submit: 'Create',
  },

  /** Delete-watchlist controls. {{name}} is the watchlist name. */
  delete: {
    button: 'Delete',
    confirm: 'Delete watchlist "{{name}}"? This cannot be undone.',
  },

  /** Watchlist switcher. */
  switch: {
    label: 'Watchlist',
    placeholder: 'Select a watchlist',
  },

  /** Watchlist-page left sidebar (FRA-45). */
  sidebar: {
    title: 'Watchlists',
    hint: 'Switch, create, or delete watchlists here.',
  },

  /** Add-asset modal & flow. */
  addAsset: {
    button: 'Add asset',
    modal: {
      title: 'Add asset',
    },
    form: {
      symbol: {
        label: 'Symbol',
        placeholder: 'e.g. AAPL',
      },
      exchange: {
        label: 'Exchange (optional)',
        placeholder: 'e.g. NASDAQ',
      },
    },
    search: {
      button: 'Search',
      noResults: 'No assets matched your search.',
      /** {{count}} is the number of results returned. */
      resultsCount: '{{count}} asset(s) found. Select one to add.',
    },
    select: {
      prompt: 'Select an asset to add.',
    },
    submit: 'Add',
  },

  /** Remove-asset controls. */
  remove: {
    button: 'Remove',
    confirm: 'Remove this asset from the watchlist?',
  },

  /** Hand-off to the (FRA-11) dashboard. {{symbol}} is the asset symbol. */
  viewInDashboard: 'View in dashboard',
  /** {{symbol}} is the asset symbol that was selected. */
  selectForDashboard: 'Selected {{symbol}}. It will be shown in the dashboard.',
} as const;

export default watchlist;
