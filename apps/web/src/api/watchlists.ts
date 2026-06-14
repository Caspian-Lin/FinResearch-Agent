/**
 * Watchlist CRUD client (FRA-10 endpoints).
 *
 * Each function returns the typed payload or throws an `ApiError` (mapped from
 * the HTTP status by the response interceptor). Callers decide how to surface
 * the error code via i18n.
 */
import { apiClient, type ApiError } from './client';
import type { WatchlistRead } from '@/types/api';

/** `GET /watchlists` → all of the caller's watchlists with their items. */
export async function listWatchlists(): Promise<WatchlistRead[]> {
  const { data } = await apiClient.get<{ items: WatchlistRead[] }>('/watchlists');
  return data.items;
}

/** `POST /watchlists` → create a new watchlist. 409 on duplicate name. */
export async function createWatchlist(name: string): Promise<WatchlistRead> {
  const { data } = await apiClient.post<WatchlistRead>('/watchlists', { name });
  return data;
}

/** `DELETE /watchlists/{watchlist_id}` → 204 on success, 404 if missing/owned by another. */
export async function deleteWatchlist(watchlistId: string): Promise<void> {
  await apiClient.delete(`/watchlists/${watchlistId}`);
}

/** `POST /watchlists/{watchlist_id}/assets/{asset_id}` → updated watchlist (idempotent). */
export async function addWatchlistAsset(
  watchlistId: string,
  assetId: string,
): Promise<WatchlistRead> {
  const { data } = await apiClient.post<WatchlistRead>(
    `/watchlists/${watchlistId}/assets/${assetId}`,
  );
  return data;
}

/** `DELETE /watchlists/{watchlist_id}/assets/{asset_id}` → 204 (idempotent). */
export async function removeWatchlistAsset(watchlistId: string, assetId: string): Promise<void> {
  await apiClient.delete(`/watchlists/${watchlistId}/assets/${assetId}`);
}

/** Re-exported so callers can `import { ApiError }` from this module too. */
export type { ApiError };
