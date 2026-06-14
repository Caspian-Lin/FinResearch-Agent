/**
 * English — `errors` namespace.
 *
 * IMPORTANT: error display is keyed by **stable error codes** (`error.*`),
 * never by raw backend message strings. Backend failure messages may change
 * and are not localized; the frontend maps a known error code to a stable,
 * translated user-facing message. Unknown codes fall back to `errors.unknown`.
 */

const errors = {
  /** Generic unknown / unmapped error. Never expose the raw key to users. */
  unknown: 'Something went wrong. Please try again.',
  network: 'Network error. Please check your connection and retry.',
  timeout: 'The request timed out. Please retry.',
  unauthorized: 'You are not authorized to perform this action.',
  forbidden: 'Access denied.',
  notFound: 'The requested resource was not found.',
  conflict: 'The resource already exists or conflicts with existing data.',
  validation: 'Some fields are invalid. Please review and retry.',
  rateLimited: 'Too many requests. Please slow down and retry shortly.',
  server: 'Server error. We have been notified. Please retry later.',

  /** Domain error codes — keep stable identifiers; map on the frontend. */
  assetNotFound: 'Asset not found.',
  ohlcvSyncFailed: 'Failed to sync OHLCV data for the requested symbol.',
  watchlistLimitReached: 'You have reached the maximum number of watchlist entries.',
  backtestFailed: 'Backtest execution failed. Check parameters and retry.',
} as const;

export default errors;
