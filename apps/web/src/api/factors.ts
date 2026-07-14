/**
 * Factor research API client (FRA-56 sync + FRA-57 async endpoints).
 *
 * Sync endpoints return computed results directly (IC / quantile / sensitivity);
 * async endpoints enqueue a worker job (202 → `run_id`) then the page polls
 * `getFactorJob(run_id)` until terminal (success / failed). Execution +
 * persistence happen in the worker (FRA-57); the page only triggers + renders.
 *
 * Each function returns the typed payload or throws `ApiError` (mapped to a
 * stable `code` the view layer resolves via `t('errors:<code>')`).
 */
import { apiClient } from './client';
import type {
  FactorComputeRequest,
  FactorComputeResponse,
  FactorJobEnqueueResponse,
  FactorJobStatusResponse,
  FactorRankingSnapshotResponse,
  ICResponse,
  QuantileBacktestRequest,
  QuantileBacktestResponse,
  SensitivityRequest,
  SensitivityResponse,
} from '@/types/api';

// --- sync (FRA-56) ---------------------------------------------------------

/** `POST /factors/compute` — load prices → compute factors → idempotent upsert. */
export async function computeFactors(
  payload: FactorComputeRequest,
): Promise<FactorComputeResponse> {
  const { data } = await apiClient.post<FactorComputeResponse>('/factors/compute', payload);
  return data;
}

/**
 * `GET /factors/{name}/ic` — cross-sectional Spearman IC of `factor_name` vs
 * `horizon`-day forward returns. `universe` / `source` / `start` / `end` /
 * `horizon` ride the query string.
 */
export async function getFactorIC(
  factorName: string,
  params: {
    universe: string[];
    source: string;
    start: string;
    end: string;
    horizon?: number;
    price_field?: string;
  },
): Promise<ICResponse> {
  const { data } = await apiClient.get<ICResponse>(`/factors/${factorName}/ic`, { params });
  return data;
}

/** `GET /factors/{name}/snapshot` — one-date cross-sectional rank table. */
export async function getFactorRankingSnapshot(
  factorName: string,
  params: {
    universe: string[];
    source: string;
    start: string;
    end: string;
    snapshot_date?: string;
    n_quantiles?: number;
    price_field?: string;
  },
): Promise<FactorRankingSnapshotResponse> {
  const { data } = await apiClient.get<FactorRankingSnapshotResponse>(
    `/factors/${factorName}/snapshot`,
    { params },
  );
  return data;
}

/** `POST /factors/quantile-backtest` — N-bucket stratified backtest (sync). */
export async function quantileBacktest(
  payload: QuantileBacktestRequest,
): Promise<QuantileBacktestResponse> {
  const { data } = await apiClient.post<QuantileBacktestResponse>(
    '/factors/quantile-backtest',
    payload,
  );
  return data;
}

/** `POST /factors/sensitivity` — factor parameter/cost sensitivity sweep (sync). */
export async function factorSensitivity(payload: SensitivityRequest): Promise<SensitivityResponse> {
  const { data } = await apiClient.post<SensitivityResponse>('/factors/sensitivity', payload);
  return data;
}

// --- async worker jobs (FRA-57) --------------------------------------------

/** `POST /factors/compute-async` — enqueue a batch factor computation (202). */
export async function enqueueFactorCompute(
  payload: FactorComputeRequest,
): Promise<FactorJobEnqueueResponse> {
  const { data } = await apiClient.post<FactorJobEnqueueResponse>(
    '/factors/compute-async',
    payload,
  );
  return data;
}

/** `POST /factors/quantile-backtest-async` — enqueue a stratified backtest (202). */
export async function enqueueQuantileBacktest(
  payload: QuantileBacktestRequest,
): Promise<FactorJobEnqueueResponse> {
  const { data } = await apiClient.post<FactorJobEnqueueResponse>(
    '/factors/quantile-backtest-async',
    payload,
  );
  return data;
}

/** `POST /factors/sensitivity-async` — enqueue a sensitivity sweep (202). */
export async function enqueueFactorSensitivity(
  payload: SensitivityRequest,
): Promise<FactorJobEnqueueResponse> {
  const { data } = await apiClient.post<FactorJobEnqueueResponse>(
    '/factors/sensitivity-async',
    payload,
  );
  return data;
}

/** `GET /factors/jobs/{run_id}` — poll a factor job's status + result. */
export async function getFactorJob(runId: string): Promise<FactorJobStatusResponse> {
  const { data } = await apiClient.get<FactorJobStatusResponse>(`/factors/jobs/${runId}`);
  return data;
}
