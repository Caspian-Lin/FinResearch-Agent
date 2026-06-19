/**
 * Shared API response types — mirroring the backend FRA-7 / FRA-10 contracts.
 *
 * Timestamps are kept as ISO strings (as serialized by the API) rather than
 * `Date` so they survive JSON transport unchanged; locale formatting happens
 * at the view layer via dayjs.
 */

/** A single asset (FRA-7 `AssetRead`). */
export interface AssetRead {
  asset_id: string;
  symbol: string;
  name: string;
  exchange: string;
  asset_type: string;
  currency: string;
  created_at: string;
}

/** A row inside a watchlist (FRA-10 `WatchlistItemRead`). */
export interface WatchlistItemRead {
  asset_id: string;
  symbol: string;
  exchange: string;
  name: string;
  added_at: string;
}

/** A watchlist with its items (FRA-10 `WatchlistRead`). */
export interface WatchlistRead {
  watchlist_id: string;
  name: string;
  created_at: string;
  items: WatchlistItemRead[];
}

/** Minimal asset projection used by the cross-page selection store. */
export interface SelectedAsset {
  asset_id: string;
  symbol: string;
  exchange: string;
  name: string;
}

/**
 * Authenticated user (FRA-6 `UserRead`).
 *
 * `id` is a UUID; `created_at` is an ISO string (serialized as-is by the API).
 */
export interface UserRead {
  id: string;
  email: string;
  is_active: boolean;
  created_at: string;
}

/**
 * Login response (FRA-6 `TokenResponse`).
 *
 * `expires_in` is in seconds; `token_type` is always `bearer` per the backend
 * contract but kept generic here so the field name is self-documenting.
 */
export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

/**
 * A single OHLCV bar (FRA-15 `OhlcvRead`).
 *
 * `time` is an ISO datetime in UTC. Price/volume fields are nullable: the
 * backend stores raw bars which may be partially populated (e.g. an ETF with
 * no reported volume). The view layer decides how to fill gaps (see PriceChart:
 * `adjusted_close ?? close`).
 */
export interface OhlcvRead {
  asset_id: string;
  time: string;
  source: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  adjusted_close: number | null;
  volume: number | null;
}

/**
 * One keyset-paginated page of OHLCV (FRA-15).
 *
 * `next_cursor` is opaque (forwarded verbatim); `has_more` is the authoritative
 * "are there more pages" signal. The aggregator in `api/ohlcv` follows the
 * cursor until `has_more` is false.
 */
export interface OhlcvPage {
  items: OhlcvRead[];
  next_cursor: string | null;
  has_more: boolean;
}

/**
 * A single detected data anomaly for an OHLCV bar (FRA-9 `AnomalyPoint`).
 *
 * `rule` is one of a fixed enum of quality rules. `detail` is backend freeform
 * text; it is shown verbatim (untranslated) since it is computed/rule-specific
 * rather than user-facing copy.
 */
export interface AnomalyPoint {
  time: string;
  rule: string;
  detail: string | null;
}

/**
 * Quality report for an asset/window (FRA-9 `QualityReport`).
 *
 * `coverage` is a 0..1 ratio (observed / expected trading sessions).
 * `missing_sessions` are ISO dates (calendar, not datetime). `anomalies` lists
 * rule violations found within the window.
 */
export interface QualityReport {
  asset_id: string;
  source: string;
  start: string;
  end: string;
  expected_sessions: number;
  observed_sessions: number;
  missing_sessions_count: number;
  coverage: number;
  missing_sessions: string[];
  anomalies: AnomalyPoint[];
}

/**
 * `POST /sync` 202 response (FRA-8). The job runs asynchronously; poll
 * `getSyncJob(job_id)` for terminal status.
 */
export interface SyncEnqueueResponse {
  job_id: string;
  status: string;
  asset_id: string;
  start: string;
  end: string;
  source: string;
}

/** Lifecycle status of a sync job (FRA-8/FRA-22). */
export type SyncJobStatus = 'pending' | 'running' | 'success' | 'success_no_data' | 'failed';

/**
 * A sync job snapshot (FRA-8 `GET /sync/{job_id}`).
 *
 * On terminal failure `error` carries a sanitized `{ type, message }` pair; the
 * `message` is short (<200 chars) and safe to surface to users (unlike generic
 * API `detail`, which is debug-only).
 */
export interface SyncJob {
  job_id: string;
  status: SyncJobStatus;
  asset_id: string | null;
  start: string | null;
  end: string | null;
  source: string | null;
  inserted: number | null;
  updated: number | null;
  total_bars: number | null;
  warning: string | null;
  error: { type: string; message: string } | null;
}

// ---------------------------------------------------------------------------
// Backtest (FRA-36 contract, consumed by the FRA-38 page)
// ---------------------------------------------------------------------------

/** Registered strategy names (mirrors backend ``ALLOWED_STRATEGIES``). */
export type BacktestStrategyName =
  | 'buy_hold'
  | 'equal_weight'
  | 'ma_crossover'
  | 'momentum'
  | 'reversal';

/** Rebalance frequency (mirrors backend ``ALLOWED_REBALANCE``). */
export type RebalanceFreq = 'daily' | 'weekly' | 'monthly';

/** Price source column (mirrors backend ``PRICE_FIELDS``). */
export type BacktestPriceField = 'raw' | 'adjusted';

/** Backtest run lifecycle status (mirrors ``BACKTEST_STATUSES``). */
export type BacktestStatus = 'pending' | 'running' | 'success' | 'failed';

/** Run origin: ``backtest`` (POST /backtest) vs ``sensitivity`` (FRA-35 sweep). */
export type BacktestRunKind = 'backtest' | 'sensitivity';

/** Equity-curve series kind: the strategy vs its benchmark (FRA-41). */
export type EquitySeriesKind = 'strategy' | 'benchmark';

/** Trade direction (FRA-42). */
export type TradeSide = 'buy' | 'sell';

/**
 * A backtest run's metadata + full config snapshot (FRA-36 `BacktestRunRead`).
 *
 * Numeric Decimal fields are serialized as JSON numbers (FRA-24 pattern). The
 * full config lives in `config_json` for reproducibility (§11.3). `error_message`
 * is a short backend message, surfaced only when `status==='failed'`.
 */
export interface BacktestRunRead {
  id: string;
  user_id: string;
  name: string;
  strategy_type: string;
  config_json: Record<string, unknown>;
  benchmark_asset_id: string | null;
  start_date: string;
  end_date: string;
  price_field: BacktestPriceField;
  status: BacktestStatus;
  error_message: string | null;
  run_kind: BacktestRunKind;
  created_at: string;
}

/**
 * Gross + net metric sets for a finished run (FRA-36 `BacktestMetricsRead`).
 *
 * Every field is `number | null` (Decimal → float, FRA-24 pattern): null while
 * pending/running, or when a metric couldn't be computed (e.g. beta/correlation
 * without a benchmark). Gross = before cost, net = after cost.
 */
export interface BacktestMetricsRead {
  backtest_run_id: string;
  gross_annual_return: number | null;
  gross_volatility: number | null;
  gross_sharpe_ratio: number | null;
  gross_max_drawdown: number | null;
  gross_calmar_ratio: number | null;
  gross_turnover: number | null;
  gross_win_rate: number | null;
  gross_beta: number | null;
  gross_correlation: number | null;
  net_annual_return: number | null;
  net_volatility: number | null;
  net_sharpe_ratio: number | null;
  net_max_drawdown: number | null;
  net_calmar_ratio: number | null;
  net_turnover: number | null;
  net_win_rate: number | null;
  net_beta: number | null;
  net_correlation: number | null;
}

/**
 * One point of the equity / daily-return / drawdown curve (FRA-36).
 *
 * `series_kind` distinguishes the strategy's curve from the benchmark's; both
 * share the same time index. `daily_return`/`drawdown` are null on the first
 * point (nothing to diff/peak against).
 */
export interface EquityCurvePointRead {
  backtest_run_id: string;
  series_kind: EquitySeriesKind;
  time: string;
  equity: number;
  daily_return: number | null;
  drawdown: number | null;
}

/** One rebalance fill persisted by the worker (FRA-42 `TradeRead`). */
export interface TradeRead {
  id: string;
  backtest_run_id: string;
  time: string;
  asset_id: string;
  side: TradeSide;
  quantity: number;
  price: number;
  cost: number;
  created_at: string;
}

/**
 * Full result for `GET /backtest/{id}` (FRA-36 `BacktestDetailRead`): run +
 * metrics + curves + trades. `metrics`/`equity_curve`/`trades` are empty/null
 * until the worker reaches `status==='success'`.
 */
export interface BacktestDetailRead {
  run: BacktestRunRead;
  metrics: BacktestMetricsRead | null;
  equity_curve: EquityCurvePointRead[];
  trades: TradeRead[];
}

/**
 * `POST /backtest` payload (FRA-36 `BacktestCreateRequest`).
 *
 * `universe` is the asset UUIDs to backtest (non-empty); `strategy_params`
 * carries strategy-specific knobs (e.g. ma_crossover's `fast`/`slow`); the rest
 * default server-side if omitted.
 */
export interface BacktestCreateRequest {
  name: string;
  strategy_name: BacktestStrategyName;
  universe: string[];
  start: string;
  end: string;
  benchmark_asset_id?: string | null;
  initial_capital?: number;
  cost_bps?: number;
  rebalance?: RebalanceFreq;
  price_field?: BacktestPriceField;
  strategy_params?: Record<string, unknown>;
}

/** 202 response after a run is created + enqueued (FRA-36). */
export interface BacktestEnqueueResponse {
  run_id: string;
  status: 'pending';
}

/** Paginated list of the caller's runs (`GET /backtest`, FRA-36). */
export interface BacktestListResponse {
  items: BacktestRunRead[];
  total: number;
}
