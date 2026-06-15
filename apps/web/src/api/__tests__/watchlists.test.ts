/**
 * Regression tests for the watchlist API client parsing (hotfix).
 *
 * The WatchlistPage tests mock `listWatchlists` itself, so they never
 * exercised how the client unpacks the HTTP response — which let a
 * `{items}`-vs-bare-array mismatch slip through and white-screen the page.
 * These tests mock the `apiClient` layer (one level down) and assert the
 * client returns the backend's bare `list[WatchlistRead]` array directly.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/api/client', () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

import { apiClient } from '@/api/client';
import { listWatchlists, createWatchlist } from '@/api/watchlists';
import type { WatchlistRead } from '@/types/api';

// `vi.mocked` on an unbound method trips @typescript-eslint/unbound-method —
// a known false positive for vitest mocks. Bound locally here, no real `this`.
/* eslint-disable @typescript-eslint/unbound-method */
const mockGet = vi.mocked(apiClient.get);
const mockPost = vi.mocked(apiClient.post);
/* eslint-enable @typescript-eslint/unbound-method */

const wl: WatchlistRead = {
  watchlist_id: 'w-1',
  name: 'Tech',
  created_at: '2026-01-01T00:00:00Z',
  items: [],
};

describe('watchlists api parsing', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
  });

  it('listWatchlists returns the bare array (backend is list[WatchlistRead], not {items})', async () => {
    mockGet.mockResolvedValueOnce({ data: [wl] });
    const result = await listWatchlists();
    expect(Array.isArray(result)).toBe(true);
    expect(result).toEqual([wl]);
  });

  it('listWatchlists returns [] for an empty response', async () => {
    mockGet.mockResolvedValueOnce({ data: [] });
    expect(await listWatchlists()).toEqual([]);
  });

  it('createWatchlist returns the created watchlist', async () => {
    mockPost.mockResolvedValueOnce({ data: wl });
    expect(await createWatchlist('Tech')).toEqual(wl);
  });
});
