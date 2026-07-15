/**
 * Shared API response types — mirroring the backend FRA-7 / FRA-10 contracts.
 *
 * Timestamps are kept as ISO strings (as serialized by the API) rather than
 * `Date` so they survive JSON transport unchanged; locale formatting happens
 * at the view layer via dayjs.
 */

/**
 * A single asset (FRA-7 `AssetRead`).
 *
 * `data_source` is the originating provider (yfinance / akshare / tushare) and
 * `list_status` is its tradable/listing status — both added by FRA-78.
 */
export interface AssetRead {
  asset_id: string;
  symbol: string;
  name: string;
  exchange: string;
  asset_type: string;
  currency: string;
  data_source: string;
  list_status: string;
  created_at: string;
}

/**
 * A row inside a watchlist (FRA-10 `WatchlistItemRead`).
 *
 * `data_source` (added by FRA-80) mirrors the underlying asset's provider so
 * the watchlist table can show where each row's data comes from.
 */
export interface WatchlistItemRead {
  asset_id: string;
  symbol: string;
  exchange: string;
  name: string;
  data_source: string;
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

// ---------------------------------------------------------------------------
// Factor research (FRA-56 sync API + FRA-57 async worker jobs)
// ---------------------------------------------------------------------------
// Mirrors the backend `app/schemas/factor.py` contract 1:1. Numeric fields are
// JSON numbers; timestamps are ISO strings. `QuantileResult` / `ICResult` align
// with `packages/shared` types (FRA-47). The async job `result` is a freeform
// object whose shape varies by `run_kind` (compute=rows, quantile=curves,
// sweep=summary) — the page casts it per kind.

/** Price source column (same values as `BacktestPriceField`, kept separate for clarity). */
export type FactorPriceField = 'raw' | 'adjusted';

/** A time-series point: IC per period, quantile equity, top−bottom spread. */
export interface TimeSeriesPoint {
  /** ISO 8601, UTC midnight. */
  time: string;
  value: number;
}

/** IC summary stats (mean / ICIR / t-stat / p-value / n / positive_rate). */
export interface ICSummary {
  mean: number;
  icir: number;
  t_stat: number;
  p_value: number;
  n: number;
  positive_rate: number;
}

/** IC evaluation: per-period series + summary. */
export interface ICResult {
  series: TimeSeriesPoint[];
  summary: ICSummary;
}

/** Stratified (quantile) backtest: per-bucket equity + long−short + monotonicity. */
export interface QuantileResult {
  /** key = quantile label 1..N (1 = lowest factor value), value = that bucket's equity series. */
  quantile_equity: Record<string, TimeSeriesPoint[]>;
  /** long top − short bottom cumulative spread. */
  top_minus_bottom: TimeSeriesPoint[];
  /** monotonicity of bucket mean return vs bucket rank (Spearman; NaN if degenerate). */
  monotonicity: number;
}

/** One asset row in a cross-sectional factor ranking snapshot (FRA-76). */
export interface FactorRankingSnapshotItem {
  asset_id: string;
  symbol: string;
  factor_value: number;
  rank_pct: number;
  z_score: number | null;
  quantile_bucket: number;
}

/** Ranking snapshot response for one decision date. */
export interface FactorRankingSnapshotResponse {
  factor_name: string;
  source: string;
  snapshot_time: string | null;
  requested_date: string | null;
  n_quantiles: number;
  items: FactorRankingSnapshotItem[];
  total: number;
  config_snapshot: Record<string, unknown>;
}

/** One dimension's sensitivity impact (FRA-54 `ParamImpact`). */
export interface ParamImpact {
  param: string;
  normalized_range: number;
  absolute_range: number;
  high_impact: boolean;
}

/** Factor sensitivity sweep summary (FRA-54 `SweepSummary`). */
export interface SensitivitySummary {
  metric_table: Record<string, unknown>[];
  param_impacts: ParamImpact[];
  highly_sensitive: boolean;
  best_net_sharpe: number | null;
  worst_net_sharpe: number | null;
}

/** Factor worker job kind (mirrors backend factor run_kind values, FRA-57). */
export type FactorJobKind = 'factor_compute' | 'factor_quantile' | 'factor_sweep';

/** Factor worker job lifecycle (mirrors `BACKTEST_STATUSES`). */
export type FactorJobStatus = 'pending' | 'running' | 'success' | 'failed';

// ---------------------------------------------------------------------------
// Sentiment research (FRA-70 API + FRA-71 comparison)
// ---------------------------------------------------------------------------
// Mirrors the backend `app/schemas/sentiment.py` contract 1:1. Timestamps are
// ISO strings; numeric fields are JSON numbers. Each research response carries
// a `config_snapshot` for reproducibility.

/** Sentiment label (mirrors backend label set). */
export type SentimentLabel = 'positive' | 'negative' | 'neutral';

/** One persisted news item (FRA-70 `NewsItemRead`). */
export interface NewsItemRead {
  id: string;
  asset_id: string;
  source: string;
  published_at: string;
  headline: string;
  summary: string | null;
  url: string | null;
}

/** One classified news item with score (FRA-70 `SentimentScoreRead`). */
export interface SentimentScoreRead {
  id: string;
  news_item_id: string;
  asset_id: string;
  published_at: string;
  model_name: string;
  label: string;
  score: number;
  confidence: number | null;
  source: string;
  headline: string;
  summary: string | null;
  url: string | null;
}

/** One per-day per-asset sentiment aggregate (FRA-70 `SentimentSummaryRead`). */
export interface SentimentSummaryRead {
  asset_id: string;
  signal_date: string;
  window_start: string;
  window_end: string;
  model_name: string;
  prompt_version: string;
  score: number | null;
  confidence: number | null;
  news_count: number;
  label_counts: Record<string, number>;
  source: string;
}

// --- sentiment request types ----------------------------------------------

/** `POST /sentiment/news/sync` (sync) + `POST /sentiment/news/sync-async`. */
export interface NewsSyncRequest {
  name?: string;
  universe: string[];
  start: string;
  end: string;
  provider?: string;
}

/** `POST /sentiment/score` (sync) + `POST /sentiment/score-async`. */
export interface SentimentScoreRequest {
  name?: string;
  universe: string[];
  start: string;
  end: string;
  classifier?: string;
}

/** `POST /sentiment/factor/compute` (sync) + `POST /sentiment/factor/compute-async`. */
export interface SentimentFactorRequest {
  name?: string;
  universe: string[];
  start: string;
  end: string;
  model_name: string;
}

// --- sentiment response types ---------------------------------------------

export interface NewsListResponse {
  items: NewsItemRead[];
  total: number;
}

export interface NewsSyncResponse {
  provider: string;
  assets: number;
  fetched: number;
  inserted: number;
  updated: number;
  status: string;
  warning: string | null;
  config_snapshot: Record<string, unknown>;
}

export interface SentimentScoresResponse {
  items: SentimentScoreRead[];
  total: number;
}

export interface SentimentClassifyResponse {
  classifier: string | null;
  news: number;
  classified: number;
  skipped: number;
  inserted: number;
  updated: number;
  status: string;
  config_snapshot: Record<string, unknown>;
}

export interface SentimentFactorItemRead {
  asset_id: string;
  values: TimeSeriesPoint[];
}

export interface SentimentFactorResponse {
  model_name: string;
  items: SentimentFactorItemRead[];
  config_snapshot: Record<string, unknown>;
}

export interface SentimentFactorComputeResponse {
  model_name: string;
  assets: number;
  scores_read: number;
  rows_written: number;
  status: string;
  config_snapshot: Record<string, unknown>;
}

export interface SentimentSummariesResponse {
  model_name: string;
  items: SentimentSummaryRead[];
  total: number;
  config_snapshot: Record<string, unknown>;
}

/** Sentiment worker job kind. */
export type SentimentJobKind =
  | 'sentiment_sync_news'
  | 'sentiment_classify'
  | 'sentiment_factor';

/** `GET /sentiment/jobs/{run_id}` — poll pending → running → success/failed. */
export interface SentimentJobStatusResponse {
  run_id: string;
  name: string;
  run_kind: string;
  status: string;
  error_message: string | null;
  result: Record<string, unknown> | null;
  config_snapshot: Record<string, unknown>;
}

/** 202 response after a sentiment job is created + enqueued. */
export interface SentimentJobEnqueueResponse {
  run_id: string;
  run_kind: string;
  status: string;
}

// --- FRA-71 comparison types -----------------------------------------------

/** Comparison fusion mode (mirrors backend `SentimentTechStrategy` mode param). */
export type ComparisonMode = 'overlay' | 'combined';

/** Technical factor names available for the comparison (mirrors factor registry). */
export type ComparisonTechnicalFactor = 'momentum' | 'reversal' | 'rsi' | 'volatility';

/** `POST /backtest/comparison` payload. */
export interface ComparisonCreateRequest {
  name: string;
  universe: string[];
  start: string;
  end: string;
  benchmark_asset_id?: string | null;
  initial_capital?: number;
  cost_bps?: number;
  rebalance?: RebalanceFreq;
  price_field?: BacktestPriceField;
  model_name: string;
  strategy_params?: {
    technical_factor?: ComparisonTechnicalFactor;
    window?: number;
    top_k?: number;
    mode?: ComparisonMode;
    sentiment_threshold?: number;
    sentiment_weight?: number;
  };
  include_sentiment_only?: boolean;
}

/** 202 response after a comparison run is created + enqueued. */
export interface ComparisonEnqueueResponse {
  run_id: string;
  status: string;
}

/** One child run within a comparison (role + run detail + metrics). */
export interface ComparisonChildRead {
  role: string;
  run: BacktestRunRead;
  metrics: BacktestMetricsRead | null;
}

/** Full comparison result: parent run + child runs side-by-side. */
export interface ComparisonDetailRead {
  run: BacktestRunRead;
  children: ComparisonChildRead[];
}

/** `POST /factors/compute` payload (sync) — also the `*-async` body. */
export interface FactorComputeRequest {
  name?: string;
  universe: string[];
  source: string;
  start: string;
  end: string;
  price_field?: FactorPriceField;
  factor_names: string[];
}

/** `POST /factors/quantile-backtest` payload (sync) — also the `*-async` body. */
export interface QuantileBacktestRequest {
  name?: string;
  universe: string[];
  source: string;
  start: string;
  end: string;
  price_field?: FactorPriceField;
  factor_name: string;
  n_quantiles?: number;
}

/** `POST /factors/sensitivity` payload (sync) — also the `*-async` body. */
export interface SensitivityRequest {
  name?: string;
  universe: string[];
  source: string;
  start: string;
  end: string;
  price_field?: FactorPriceField;
  factors: string[];
  windows?: Record<string, number[]> | null;
  top_ks?: number[];
  quantiles?: number[];
  n_quantiles?: number;
  rebalances?: string[];
  cost_bands?: number[];
}

/** `POST /factors/compute` response. */
export interface FactorComputeResponse {
  source: string;
  factor_names: string[];
  rows_written: number;
  config_snapshot: Record<string, unknown>;
}

/** `GET /factors/{name}/ic` response. */
export interface ICResponse {
  factor_name: string;
  result: ICResult;
  config_snapshot: Record<string, unknown>;
}

/** `POST /factors/quantile-backtest` response. */
export interface QuantileBacktestResponse {
  factor_name: string;
  result: QuantileResult;
  config_snapshot: Record<string, unknown>;
}

/** `POST /factors/sensitivity` response. */
export interface SensitivityResponse extends SensitivitySummary {
  config_snapshot: Record<string, unknown>;
}

/** 202 response after a factor job is created + enqueued (FRA-57). */
export interface FactorJobEnqueueResponse {
  run_id: string;
  run_kind: FactorJobKind;
  status: 'pending';
}

/**
 * `GET /factors/jobs/{id}` response (FRA-57): poll pending → running → success/failed.
 *
 * `result` is the worker-written `result_json` (shape varies by `run_kind`: compute
 * = `{rows_written, factor_names}`, quantile = `QuantileResult`, sweep =
 * `SensitivitySummary`); null until success. `error_message` is a short backend
 * message surfaced only on failure.
 */
export interface FactorJobStatusResponse {
  run_id: string;
  name: string;
  run_kind: FactorJobKind;
  status: FactorJobStatus;
  error_message: string | null;
  result: Record<string, unknown> | null;
  config_snapshot: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Agent Research (FRA-90 API + FRA-91 UI)
// ---------------------------------------------------------------------------
// Mirrors the backend `app/schemas/agent_run.py` wire-level types 1:1.
// The canonical plan contract lives in `@finresearch/shared` (ResearchPlanT);
// the API surface below consumes it for type safety.

import type { ResearchPlanT } from '@finresearch/shared';

/** `POST /agent/plans` response — plan draft (no side effects). */
export interface AgentPlanResponse {
  research_question: string;
  plan: ResearchPlanT | null;
  plan_hash: string | null;
  clarification_needed: string | null;
  validation_errors: string[];
  planner_provider: string | null;
  planner_model: string | null;
}

/** `POST /agent/runs` request body. */
export interface AgentRunCreateRequest {
  plan: ResearchPlanT;
  plan_hash: string;
}

/** `POST /agent/runs` response — 202 enqueued. */
export interface AgentRunEnqueuedResponse {
  run_id: string;
  status: string;
  plan_hash: string;
}

/** Compact run summary for list responses. */
export interface AgentRunSummary {
  id: string;
  research_question: string;
  status: string;
  plan_hash: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_summary: string | null;
  current_step: string | null;
}

/** Full run detail with plan + synthesis. */
export interface AgentRunDetail extends AgentRunSummary {
  plan: ResearchPlanT | null;
  synthesis: Record<string, unknown> | null;
  step_count: number;
  completed_steps: number;
}

/** Paginated list of a user's runs. */
export interface AgentRunListResponse {
  runs: AgentRunSummary[];
  total: number;
  limit: number;
  offset: number;
}

/** One sanitized tool call in the trace. */
export interface ToolCallTrace {
  id: string;
  tool_name: string;
  status: string;
  args: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  error: string | null;
  error_code: string | null;
  evidence_refs: Record<string, unknown>[] | null;
  duration_ms: number | null;
  started_at: string | null;
  finished_at: string | null;
}

/** One step in the trace, with nested tool calls. */
export interface StepTrace {
  id: string;
  sequence: number;
  agent_role: string;
  kind: string;
  status: string;
  input_summary: Record<string, unknown> | null;
  output_summary: Record<string, unknown> | null;
  error: string | null;
  duration_ms: number | null;
  started_at: string | null;
  finished_at: string | null;
  tool_calls: ToolCallTrace[];
}

/** Full trace for a run — ordered steps with nested tool calls. */
export interface AgentTraceResponse {
  run_id: string;
  run_status: string;
  steps: StepTrace[];
}

/** `POST /agent/runs/{id}/cancel` response. */
export interface AgentCancelResponse {
  run_id: string;
  status: string;
  message: string;
}

// ---------------------------------------------------------------------------
// User LLM Config (FRA-93)
// ---------------------------------------------------------------------------

/** `GET /settings/llm` response — masked, never includes the API key. */
export interface LLMConfigRead {
  provider: string;
  has_api_key: boolean;
  api_key_last4: string | null;
  base_url: string | null;
  model: string | null;
  temperature: number | null;
  updated_at: string | null;
}

/** `PUT /settings/llm` request body. All fields optional. */
export interface LLMConfigUpdate {
  provider?: string;
  api_key?: string;
  base_url?: string;
  model?: string;
  temperature?: number;
}
