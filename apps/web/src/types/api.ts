/**
 * Shared API response types — mirroring the backend FRA-7 / FRA-10 contracts.
 *
 * Timestamps are kept as ISO strings (as serialized by the API) rather than
 * `Date` so they survive JSON transport unchanged; locale formatting happens
 * at the view layer via dayjs.
 */

/** A single asset (FRA-7 `AssetRead`). */
export interface AssetRead {
  asset_id: string;
  symbol: string;
  name: string;
  exchange: string;
  asset_type: string;
  currency: string;
  created_at: string;
}

/** A row inside a watchlist (FRA-10 `WatchlistItemRead`). */
export interface WatchlistItemRead {
  asset_id: string;
  symbol: string;
  exchange: string;
  name: string;
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
