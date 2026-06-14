/**
 * Asset search client (FRA-7 endpoints). The assets endpoints are public —
 * no Authorization header required by the backend, but the shared axios
 * instance attaches one anyway if present, which is harmless.
 */
import { apiClient } from './client';
import type { AssetRead } from '@/types/api';

interface SearchAssetsParams {
  symbol: string;
  exchange?: string;
}

interface AssetListResponse {
  items: AssetRead[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * `GET /assets?symbol=&exchange=` → matching assets.
 *
 * The backend performs case-insensitive exact match on symbol/exchange and
 * returns multiple rows when a symbol exists across exchanges. The caller is
 * responsible for letting the user disambiguate by picking one `asset_id`.
 */
export async function searchAssets({ symbol, exchange }: SearchAssetsParams): Promise<AssetRead[]> {
  const { data } = await apiClient.get<AssetListResponse>('/assets', {
    params: { symbol, exchange },
  });
  return data.items;
}
