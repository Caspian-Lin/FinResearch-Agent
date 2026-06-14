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

/**
 * Authenticated user (FRA-6 `UserRead`).
 *
 * `id` is a UUID; `created_at` is an ISO string (serialized as-is by the API).
 */
export interface UserRead {
  id: string;
  email: string;
  is_active: boolean;
  created_at: string;
}

/**
 * Login response (FRA-6 `TokenResponse`).
 *
 * `expires_in` is in seconds; `token_type` is always `bearer` per the backend
 * contract but kept generic here so the field name is self-documenting.
 */
export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}
