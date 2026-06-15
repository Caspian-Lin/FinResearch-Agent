/**
 * OHLCV client (FRA-15 endpoints).
 *
 * The endpoint is keyset-paginated (cursor-based). Long windows — up to ~5
 * years ≈ 1260 daily bars — exceed the single-page max of 1000, so callers want
 * the whole series rather than one page. `fetchOhlcv` aggregates every page by
 * following `next_cursor` until `has_more` is false, with a hard safety cap of
 * 20 pages so a malformed `next_cursor` chain can never loop forever.
 *
 * Errors propagate as `ApiError` (mapped from the HTTP status by the response
 * interceptor); 404 asset / 422 bad window surface their stable code.
 */
import { apiClient } from './client';
import type { OhlcvPage, OhlcvRead } from '@/types/api';

/** Query params for the first OHLCV page. Dates are ISO date strings (no time). */
export interface FetchOhlcvParams {
  asset_id: string;
  source: string;
  start: string;
  end: string;
}

/** Per-page size. The backend max is 1000; using it minimizes round-trips. */
const PAGE_LIMIT = 1000;

/** Safety ceiling on how many pages we'll walk before stopping. */
const MAX_PAGES = 20;

/**
 * `GET /ohlcv?asset_id=&source=&start=&end=` → the full aggregated series.
 *
 * Returns bars oldest-first (the backend ordering). If the page cap is reached,
 * the partial result already fetched is returned (truncation is logged via the
 * returned length; callers treat the data as best-effort).
 */
export async function fetchOhlcv(params: FetchOhlcvParams): Promise<OhlcvRead[]> {
  const all: OhlcvRead[] = [];
  let cursor: string | null = null;

  for (let page = 0; page < MAX_PAGES; page += 1) {
    // Explicit annotation breaks a circular inference: `cursor` (typed from
    // `data.next_cursor`) feeds the params spread, which feeds `data`'s own
    // generic — without the annotation TS reports TS7022 (implicit any).
    const response = await apiClient.get<OhlcvPage>('/ohlcv', {
      params: {
        asset_id: params.asset_id,
        source: params.source,
        start: params.start,
        end: params.end,
        limit: PAGE_LIMIT,
        ...(cursor ? { cursor } : {}),
      },
    });
    const data: OhlcvPage = response.data;
    all.push(...data.items);
    if (!data.has_more || !data.next_cursor) break;
    cursor = data.next_cursor;
  }

  return all;
}
