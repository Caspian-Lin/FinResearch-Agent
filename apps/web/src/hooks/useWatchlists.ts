/**
 * `useWatchlists` — encapsulates the watchlist list lifecycle for the
 * Watchlist page: load on mount, expose loading/error state, and provide
 * mutating helpers that keep the local list in sync with the API.
 *
 * Mutations refresh the affected watchlist's items from the server response
 * (the add endpoint returns the updated watchlist; delete/remove return
 * void, so we patch local state). Errors surface as an `ApiError` on
 * `error` so the caller can map `error.code` to a translated message — the
 * raw backend `detail` is intentionally not propagated to the UI.
 */
import { useCallback, useEffect, useState } from 'react';

import { listWatchlists, createWatchlist, deleteWatchlist } from '@/api/watchlists';
import { addWatchlistAsset, removeWatchlistAsset } from '@/api/watchlists';
import type { ApiError } from '@/api/client';
import type { WatchlistRead } from '@/types/api';

interface UseWatchlistsResult {
  watchlists: WatchlistRead[];
  loading: boolean;
  error: ApiError | null;
  /** Clear the last error (e.g. after the user dismisses it). */
  clearError: () => void;
  /** Re-fetch the full list. */
  refresh: () => Promise<void>;
  /** Create a watchlist; returns the new watchlist or throws ApiError. */
  create: (name: string) => Promise<WatchlistRead>;
  /** Delete a watchlist by id; patches local state on success. */
  remove: (watchlistId: string) => Promise<void>;
  /** Add an asset to a watchlist; updates local state from the response. */
  addAsset: (watchlistId: string, assetId: string) => Promise<WatchlistRead>;
  /** Remove an asset from a watchlist; patches local state on success. */
  removeAsset: (watchlistId: string, assetId: string) => Promise<void>;
}

export function useWatchlists(): UseWatchlistsResult {
  const [watchlists, setWatchlists] = useState<WatchlistRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const items = await listWatchlists();
      setWatchlists(items);
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = useCallback(async (name: string) => {
    const created = await createWatchlist(name);
    setWatchlists((prev) => [...prev, created]);
    return created;
  }, []);

  const remove = useCallback(async (watchlistId: string) => {
    await deleteWatchlist(watchlistId);
    setWatchlists((prev) => prev.filter((w) => w.watchlist_id !== watchlistId));
  }, []);

  const addAsset = useCallback(async (watchlistId: string, assetId: string) => {
    const updated = await addWatchlistAsset(watchlistId, assetId);
    setWatchlists((prev) => prev.map((w) => (w.watchlist_id === watchlistId ? updated : w)));
    return updated;
  }, []);

  const removeAsset = useCallback(async (watchlistId: string, assetId: string) => {
    await removeWatchlistAsset(watchlistId, assetId);
    setWatchlists((prev) =>
      prev.map((w) =>
        w.watchlist_id === watchlistId
          ? { ...w, items: w.items.filter((it) => it.asset_id !== assetId) }
          : w,
      ),
    );
  }, []);

  return {
    watchlists,
    loading,
    error,
    clearError: () => setError(null),
    refresh,
    create,
    remove,
    addAsset,
    removeAsset,
  };
}
