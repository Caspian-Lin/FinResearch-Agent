/**
 * Backtest API client (FRA-36 endpoints; consumed by the FRA-38 page).
 *
 * - `POST /backtest`   → 202 `{ run_id, status }` (creates a pending run +
 *   enqueues the worker); poll `getBacktest` until status is success/failed
 *   (execution + persistence happen in the worker, FRA-37).
 * - `GET /backtest/{id}` → run + metrics + equity/drawdown curve + trades.
 * - `GET /backtest`     → the caller's runs, paginated.
 *
 * Each function returns the typed payload or throws `ApiError` (mapped to a
 * stable `code` so the view layer can resolve `t('errors:<code>')`).
 */
import { apiClient } from './client';
import type {
  BacktestCreateRequest,
  BacktestDetailRead,
  BacktestEnqueueResponse,
  BacktestListResponse,
} from '@/types/api';

/** Create + enqueue a backtest run (202). */
export async function createBacktest(
  payload: BacktestCreateRequest,
): Promise<BacktestEnqueueResponse> {
  const { data } = await apiClient.post<BacktestEnqueueResponse>('/backtest', payload);
  return data;
}

/** Fetch a run's full result: metadata + metrics + curves + trades. */
export async function getBacktest(runId: string): Promise<BacktestDetailRead> {
  const { data } = await apiClient.get<BacktestDetailRead>(`/backtest/${runId}`);
  return data;
}

/** List the caller's runs, newest first. */
export async function listBacktests(
  params: { limit?: number; offset?: number } = {},
): Promise<BacktestListResponse> {
  const { data } = await apiClient.get<BacktestListResponse>('/backtest', { params });
  return data;
}
