/**
 * OHLCV sync client (FRA-8 endpoints).
 *
 * Sync runs as a background job: `POST /sync` enqueues (202 + job_id), then the
 * client polls `GET /sync/{job_id}` until a terminal status (success/failed).
 *
 * The backend accepts a window of up to 1825 days and `source: 'yfinance'`
 * only; the UI pre-validates these to give immediate feedback rather than
 * waiting for a 422 round-trip.
 */
import { apiClient } from './client';
import type { SyncEnqueueResponse, SyncJob } from '@/types/api';

export interface EnqueueSyncParams {
  asset_id: string;
  start: string;
  end: string;
  source: string;
}

/** `POST /sync` → 202 with the new job id (status "pending"). */
export async function enqueueSync(params: EnqueueSyncParams): Promise<SyncEnqueueResponse> {
  const { data } = await apiClient.post<SyncEnqueueResponse>('/sync', {
    asset_id: params.asset_id,
    start: params.start,
    end: params.end,
    source: params.source,
  });
  return data;
}

/** `GET /sync/{job_id}` → current job snapshot. */
export async function getSyncJob(jobId: string): Promise<SyncJob> {
  const { data } = await apiClient.get<SyncJob>(`/sync/${encodeURIComponent(jobId)}`);
  return data;
}
