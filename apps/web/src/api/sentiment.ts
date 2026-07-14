/**
 * Sentiment research API client (FRA-70 sync/async + FRA-71 comparison).
 *
 * Sync endpoints return computed results directly (news sync, classify,
 * factor compute); async endpoints enqueue a worker job (202 → `run_id`)
 * then the page polls `getSentimentJob(run_id)` until terminal (success /
 * failed). Execution + persistence happen in the worker; the page only
 * triggers + renders.
 *
 * Each function returns the typed payload or throws `ApiError` (mapped to a
 * stable `code` so the view layer can resolve `t('errors:<code>')`).
 */
import { apiClient } from './client';
import type {
  ComparisonCreateRequest,
  ComparisonDetailRead,
  ComparisonEnqueueResponse,
  NewsItemRead,
  NewsListResponse,
  NewsSyncRequest,
  NewsSyncResponse,
  SentimentClassifyResponse,
  SentimentFactorComputeResponse,
  SentimentFactorRequest,
  SentimentFactorResponse,
  SentimentJobEnqueueResponse,
  SentimentJobStatusResponse,
  SentimentScoreRequest,
  SentimentScoresResponse,
  SentimentSummariesResponse,
} from '@/types/api';

// --- news sync -------------------------------------------------------------

/** `POST /sentiment/news/sync` — fetch news via provider + idempotent upsert (sync). */
export async function syncNews(payload: NewsSyncRequest): Promise<NewsSyncResponse> {
  const { data } = await apiClient.post<NewsSyncResponse>('/sentiment/news/sync', payload);
  return data;
}

/** `POST /sentiment/news/sync-async` — enqueue a news sync job (202). */
export async function enqueueNewsSync(
  payload: NewsSyncRequest,
): Promise<SentimentJobEnqueueResponse> {
  const { data } = await apiClient.post<SentimentJobEnqueueResponse>(
    '/sentiment/news/sync-async',
    payload,
  );
  return data;
}

// --- news list -------------------------------------------------------------

/** `GET /sentiment/news` — list persisted news items (time-descending). */
export async function listNews(params: {
  asset_id?: string;
  source?: string;
  start?: string;
  end?: string;
  limit?: number;
}): Promise<NewsListResponse> {
  const { data } = await apiClient.get<NewsListResponse>('/sentiment/news', { params });
  return data;
}

// --- score / classify ------------------------------------------------------

/** `POST /sentiment/score` — find news + batch classify + idempotent upsert (sync). */
export async function classifyNews(
  payload: SentimentScoreRequest,
): Promise<SentimentClassifyResponse> {
  const { data } = await apiClient.post<SentimentClassifyResponse>('/sentiment/score', payload);
  return data;
}

/** `POST /sentiment/score-async` — enqueue a sentiment classification job (202). */
export async function enqueueClassifyNews(
  payload: SentimentScoreRequest,
): Promise<SentimentJobEnqueueResponse> {
  const { data } = await apiClient.post<SentimentJobEnqueueResponse>(
    '/sentiment/score-async',
    payload,
  );
  return data;
}

// --- scores list -----------------------------------------------------------

/** `GET /sentiment/scores` — list persisted sentiment scores (time-descending). */
export async function listSentimentScores(params: {
  asset_id?: string;
  model_name?: string;
  start?: string;
  end?: string;
  limit?: number;
}): Promise<SentimentScoresResponse> {
  const { data } = await apiClient.get<SentimentScoresResponse>('/sentiment/scores', { params });
  return data;
}

// --- sentiment factor ------------------------------------------------------

/** `GET /sentiment/factor` — compute the daily sentiment factor on-the-fly (sync). */
export async function getSentimentFactor(params: {
  universe: string[];
  start: string;
  end: string;
  model_name: string;
}): Promise<SentimentFactorResponse> {
  const { data } = await apiClient.get<SentimentFactorResponse>('/sentiment/factor', { params });
  return data;
}

/** `POST /sentiment/factor/compute` — compute + persist the daily sentiment factor (sync). */
export async function computeSentimentFactor(
  payload: SentimentFactorRequest,
): Promise<SentimentFactorComputeResponse> {
  const { data } = await apiClient.post<SentimentFactorComputeResponse>(
    '/sentiment/factor/compute',
    payload,
  );
  return data;
}

/** `POST /sentiment/factor/compute-async` — enqueue a sentiment factor job (202). */
export async function enqueueSentimentFactor(
  payload: SentimentFactorRequest,
): Promise<SentimentJobEnqueueResponse> {
  const { data } = await apiClient.post<SentimentJobEnqueueResponse>(
    '/sentiment/factor/compute-async',
    payload,
  );
  return data;
}

// --- summaries -------------------------------------------------------------

/** `GET /sentiment/summaries` — daily sentiment summaries with label counts. */
export async function getSentimentSummaries(params: {
  universe: string[];
  start: string;
  end: string;
  model_name: string;
  window_days?: number;
}): Promise<SentimentSummariesResponse> {
  const { data } = await apiClient.get<SentimentSummariesResponse>('/sentiment/summaries', {
    params,
  });
  return data;
}

// --- job poll --------------------------------------------------------------

/** `GET /sentiment/jobs/{run_id}` — poll a sentiment job's status + result. */
export async function getSentimentJob(runId: string): Promise<SentimentJobStatusResponse> {
  const { data } = await apiClient.get<SentimentJobStatusResponse>(`/sentiment/jobs/${runId}`);
  return data;
}

// --- FRA-71 comparison -----------------------------------------------------

/** `POST /backtest/comparison` — create + enqueue a comparison backtest (202). */
export async function createComparison(
  payload: ComparisonCreateRequest,
): Promise<ComparisonEnqueueResponse> {
  const { data } = await apiClient.post<ComparisonEnqueueResponse>(
    '/backtest/comparison',
    payload,
  );
  return data;
}

/** `GET /backtest/comparison/{run_id}` — get comparison results (parent + children). */
export async function getComparison(runId: string): Promise<ComparisonDetailRead> {
  const { data } = await apiClient.get<ComparisonDetailRead>(`/backtest/comparison/${runId}`);
  return data;
}

// Re-export the news type for convenience (used by the page's table renderer).
export type { NewsItemRead };
