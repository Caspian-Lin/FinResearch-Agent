/**
 * Aggregated Simplified-Chinese resources, keyed by namespace.
 * Consumed by `src/i18n/index.ts`.
 */
import common from './common';
import auth from './auth';
import watchlist from './watchlist';
import dashboard from './dashboard';
import errors from './errors';

export const zhCN = {
  common,
  auth,
  watchlist,
  dashboard,
  errors,
} as const;

export default zhCN;
