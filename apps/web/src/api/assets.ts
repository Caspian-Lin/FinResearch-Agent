/**
 * Asset search client (FRA-7 endpoints). The assets endpoints are public —
 * no Authorization header required by the backend, but the shared axios
 * instance attaches one anyway if present, which is harmless.
 */
import { apiClient } from './client';
import type { AssetRead } from '@/types/api';

/**
 * Search filters for `GET /assets` (FRA-7 / FRA-80).
 *
 * `keyword` matches symbol OR name (case-insensitive fuzzy, OR-combined);
 * `name` narrows by name only (ilike); `exchanges` filters by exchange IN-list;
 * `source` filters by exact `data_source`. At least `keyword` or `symbol`
 * should be non-empty for a meaningful result set.
 */
export interface SearchAssetsParams {
  /** Fuzzy match on symbol OR name (OR-combined by the backend). */
  keyword?: string;
  /** Name-only ilike filter. */
  name?: string;
  /** Exact symbol match (kept for backward compatibility). */
  symbol?: string;
  /** Exchange IN-list filter. */
  exchanges?: string[];
  /** Exact `data_source` filter (yfinance / akshare / tushare). */
  source?: string;
}

interface AssetListResponse {
  items: AssetRead[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * `GET /assets` → matching assets.
 *
 * Passes `keyword` / `name` / `symbol` / `exchanges` / `source` through to the
 * backend. The shared axios instance has `paramsSerializer: { indexes: null }`,
 * so array query params (`exchanges`) are serialized as repeated keys
 * (`?exchanges=A&exchanges=B`), matching the FastAPI `Query(list)` contract.
 * Returns multiple rows when a symbol exists across exchanges; the caller lets
 * the user disambiguate by picking one `asset_id`.
 */
export async function searchAssets({
  keyword,
  name,
  symbol,
  exchanges,
  source,
}: SearchAssetsParams): Promise<AssetRead[]> {
  const { data } = await apiClient.get<AssetListResponse>('/assets', {
    params: { keyword, name, symbol, exchanges, source },
  });
  return data.items;
}
