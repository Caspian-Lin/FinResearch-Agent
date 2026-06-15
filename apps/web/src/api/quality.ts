/**
 * Data-quality client (FRA-9 endpoint).
 *
 * `GET /quality/{asset_id}?source=&start=&end=` → a QualityReport describing
 * coverage, missing sessions, and rule-based anomalies. 404 when the asset is
 * unknown; 422 when start>end or no trading calendar exists for the exchange.
 */
import { apiClient } from './client';
import type { QualityReport } from '@/types/api';

export interface FetchQualityParams {
  asset_id: string;
  source: string;
  start: string;
  end: string;
}

/** `GET /quality/{asset_id}` → quality report for the window. */
export async function fetchQuality(params: FetchQualityParams): Promise<QualityReport> {
  const { data } = await apiClient.get<QualityReport>(
    `/quality/${encodeURIComponent(params.asset_id)}`,
    {
      params: {
        source: params.source,
        start: params.start,
        end: params.end,
      },
    },
  );
  return data;
}
