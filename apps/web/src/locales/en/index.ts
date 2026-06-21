/**
 * Aggregated English resources, keyed by namespace.
 * Consumed by `src/i18n/index.ts`.
 */
import common from './common';
import auth from './auth';
import watchlist from './watchlist';
import dashboard from './dashboard';
import errors from './errors';
import backtest from './backtest';
import factor from './factor';

export const en = {
  common,
  auth,
  watchlist,
  dashboard,
  errors,
  backtest,
  factor,
} as const;

export default en;
