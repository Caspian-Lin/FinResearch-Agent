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
import sentiment from './sentiment';
import agent from './agent';
import settings from './settings';

export const en = {
  common,
  auth,
  watchlist,
  dashboard,
  errors,
  backtest,
  factor,
  sentiment,
  agent,
  settings,
} as const;

export default en;
