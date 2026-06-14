/**
 * WatchlistPage component tests.
 *
 * The API layer is mocked at the module boundary (`@/api/watchlists`,
 * `@/api/assets`) so these tests never issue real HTTP requests. The page's
 * data lifecycle is driven through the hook, which calls the mocked functions,
 * so we control outcomes by resolving/rejecting those mocks.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

import WatchlistPage from '@/pages/WatchlistPage';
import { useSelectionStore } from '@/store/selection';
import { ApiError } from '@/api/client';
import i18n from '@/i18n';
import type { WatchlistRead, AssetRead } from '@/types/api';

// --- Mocks -------------------------------------------------------------------
// `vi.hoisted` ensures the mock fn references exist before `vi.mock` factories
// run (factories are hoisted to the top of the file by vitest).

const mocks = vi.hoisted(() => ({
  listWatchlists: vi.fn<() => Promise<WatchlistRead[]>>(),
  createWatchlist: vi.fn<(name: string) => Promise<WatchlistRead>>(),
  deleteWatchlist: vi.fn<(id: string) => Promise<void>>(),
  addWatchlistAsset: vi.fn<(watchlistId: string, assetId: string) => Promise<WatchlistRead>>(),
  removeWatchlistAsset: vi.fn<(watchlistId: string, assetId: string) => Promise<void>>(),
  searchAssets: vi.fn<(params: { symbol: string; exchange?: string }) => Promise<AssetRead[]>>(),
}));

const {
  listWatchlists,
  createWatchlist,
  deleteWatchlist,
  addWatchlistAsset,
  removeWatchlistAsset,
  searchAssets,
} = mocks;

vi.mock('@/api/watchlists', () => ({
  listWatchlists: mocks.listWatchlists,
  createWatchlist: mocks.createWatchlist,
  deleteWatchlist: mocks.deleteWatchlist,
  addWatchlistAsset: mocks.addWatchlistAsset,
  removeWatchlistAsset: mocks.removeWatchlistAsset,
}));

vi.mock('@/api/assets', () => ({
  searchAssets: mocks.searchAssets,
}));

// --- Fixtures ----------------------------------------------------------------

function makeWatchlist(overrides: Partial<WatchlistRead> = {}): WatchlistRead {
  return {
    watchlist_id: 'wl-1',
    name: 'Tech',
    created_at: '2024-01-01T00:00:00Z',
    items: [],
    ...overrides,
  };
}

function makeAsset(overrides: Partial<AssetRead> = {}): AssetRead {
  return {
    asset_id: 'a-1',
    symbol: 'AAPL',
    name: 'Apple Inc.',
    exchange: 'NASDAQ',
    asset_type: 'stock',
    currency: 'USD',
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  };
}

function makeItem(overrides: Partial<WatchlistRead['items'][number]> = {}) {
  return {
    asset_id: 'a-1',
    symbol: 'AAPL',
    exchange: 'NASDAQ',
    name: 'Apple Inc.',
    added_at: '2024-01-02T00:00:00Z',
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/watchlist']}>
      <Routes>
        <Route path="/watchlist" element={<WatchlistPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  listWatchlists.mockReset();
  createWatchlist.mockReset();
  deleteWatchlist.mockReset();
  addWatchlistAsset.mockReset();
  removeWatchlistAsset.mockReset();
  searchAssets.mockReset();
  useSelectionStore.getState().clearSelection();
  void i18n.changeLanguage('en');
});

// --- Tests -------------------------------------------------------------------

describe('WatchlistPage', () => {
  it('shows a loading state then renders watchlists once loaded', async () => {
    let resolveList!: (v: WatchlistRead[]) => void;
    listWatchlists.mockReturnValue(
      new Promise((res) => {
        resolveList = res;
      }),
    );

    renderPage();
    // While pending, the page shows the loading copy and no watchlist yet.
    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(screen.queryByText('Tech')).toBeNull();

    resolveList([makeWatchlist({ name: 'Tech' })]);

    expect(await screen.findByText('Tech')).toBeInTheDocument();
    expect(listWatchlists).toHaveBeenCalledTimes(1);
  });

  it('shows the empty-watchlists state when none exist', async () => {
    listWatchlists.mockResolvedValue([]);
    renderPage();
    expect(
      await screen.findByText('You have no watchlists yet. Create one to start tracking assets.'),
    ).toBeInTheDocument();
  });

  it('creates a watchlist and it appears in the switcher', async () => {
    const user = userEvent.setup();
    listWatchlists.mockResolvedValue([]);
    renderPage();

    await screen.findByText(/You have no watchlists/);

    await user.click(screen.getByRole('button', { name: /New watchlist/i }));
    const nameInput = await screen.findByPlaceholderText(/Tech majors/i);
    await user.type(nameInput, 'My List');
    createWatchlist.mockResolvedValue(makeWatchlist({ watchlist_id: 'wl-2', name: 'My List' }));
    await user.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => expect(createWatchlist).toHaveBeenCalledWith('My List'));
    // The switcher Select should now show the new watchlist name.
    expect(await screen.findByText('My List')).toBeInTheDocument();
  });

  it('surfaces a 409 conflict as the watchlistNameExists field error', async () => {
    const user = userEvent.setup();
    listWatchlists.mockResolvedValue([]);
    renderPage();
    await screen.findByText(/You have no watchlists/);

    await user.click(screen.getByRole('button', { name: /New watchlist/i }));
    await user.type(await screen.findByPlaceholderText(/Tech majors/i), 'Dup');
    createWatchlist.mockRejectedValue(new ApiError('conflict', 409, 'duplicate'));
    await user.click(screen.getByRole('button', { name: 'Create' }));

    expect(
      await screen.findByText('A watchlist with this name already exists.'),
    ).toBeInTheDocument();
  });

  it('deletes a watchlist after Popconfirm', async () => {
    const user = userEvent.setup();
    listWatchlists.mockResolvedValue([makeWatchlist({ name: 'ToDelete' })]);
    renderPage();
    await screen.findByText('ToDelete');

    deleteWatchlist.mockResolvedValue(undefined);
    await user.click(screen.getByRole('button', { name: /Delete/i }));
    await user.click(await screen.findByRole('button', { name: 'OK' }));

    await waitFor(() => expect(deleteWatchlist).toHaveBeenCalledWith('wl-1'));
    await waitFor(() => expect(screen.queryByText('ToDelete')).toBeNull());
  });

  it('searches assets, picks one, adds it to the table', async () => {
    const user = userEvent.setup();
    const watchlist = makeWatchlist({ items: [] });
    listWatchlists.mockResolvedValue([watchlist]);
    renderPage();
    await screen.findByText('Tech');

    await user.click(screen.getByRole('button', { name: /Add asset/i }));
    await user.type(await screen.findByPlaceholderText('e.g. AAPL'), 'AAPL');
    searchAssets.mockResolvedValue([
      makeAsset({ asset_id: 'a-1', symbol: 'AAPL', exchange: 'NASDAQ' }),
      makeAsset({ asset_id: 'a-2', symbol: 'AAPL', exchange: 'NYSE', name: 'AAPL NYSE' }),
    ]);
    await user.click(screen.getByRole('button', { name: 'Search' }));

    // Two results disambiguated by asset_id.
    expect(await screen.findByText(/2 asset\(s\) found/)).toBeInTheDocument();
    const radio = screen.getByDisplayValue?.('a-1') ?? screen.getAllByRole('radio')[0];
    await user.click(radio);

    const updated = makeWatchlist({
      items: [
        {
          asset_id: 'a-1',
          symbol: 'AAPL',
          exchange: 'NASDAQ',
          name: 'Apple Inc.',
          added_at: '2024-01-02T00:00:00Z',
        },
      ],
    });
    addWatchlistAsset.mockResolvedValue(updated);
    await user.click(screen.getByRole('button', { name: 'Add' }));

    await waitFor(() => expect(addWatchlistAsset).toHaveBeenCalledWith('wl-1', 'a-1'));
    expect(await screen.findByText('Apple Inc.')).toBeInTheDocument();
  });

  it('shows noResults when search returns nothing', async () => {
    const user = userEvent.setup();
    listWatchlists.mockResolvedValue([makeWatchlist()]);
    renderPage();
    await screen.findByText('Tech');

    await user.click(screen.getByRole('button', { name: /Add asset/i }));
    await user.type(await screen.findByPlaceholderText('e.g. AAPL'), 'ZZZZ');
    searchAssets.mockResolvedValue([]);
    await user.click(screen.getByRole('button', { name: 'Search' }));

    expect(await screen.findByText('No assets matched your search.')).toBeInTheDocument();
  });

  it('removes an asset after Popconfirm', async () => {
    const user = userEvent.setup();
    const watchlist = makeWatchlist({
      items: [makeItem({ asset_id: 'a-1', symbol: 'AAPL', name: 'Apple Inc.' })],
    });
    listWatchlists.mockResolvedValue([watchlist]);
    renderPage();
    await screen.findByText('Apple Inc.');

    removeWatchlistAsset.mockResolvedValue(undefined);
    await user.click(screen.getByRole('button', { name: /Remove/i }));
    await user.click(await screen.findByRole('button', { name: 'OK' }));

    await waitFor(() => expect(removeWatchlistAsset).toHaveBeenCalledWith('wl-1', 'a-1'));
    await waitFor(() => expect(screen.queryByText('Apple Inc.')).toBeNull());
  });

  it('shows the unauthorized message (not the backend detail) on 401', async () => {
    listWatchlists.mockRejectedValue(new ApiError('unauthorized', 401, 'secret detail'));
    renderPage();
    expect(await screen.findByText(/not authorized/)).toBeInTheDocument();
    // The raw backend detail must never leak.
    expect(screen.queryByText('secret detail')).toBeNull();
  });

  it('switches language instantly without re-fetching', async () => {
    listWatchlists.mockResolvedValue([]);
    renderPage();
    await screen.findByText(/You have no watchlists/);
    const callsBefore = listWatchlists.mock.calls.length;

    await act(async () => {
      await i18n.changeLanguage('zh-CN');
    });
    expect(screen.getByText(/您还没有自选股列表/)).toBeInTheDocument();
    expect(screen.queryByText(/You have no watchlists/)).toBeNull();

    await act(async () => {
      await i18n.changeLanguage('en');
    });
    expect(screen.getByText(/You have no watchlists/)).toBeInTheDocument();

    // No extra fetches from language switching.
    expect(listWatchlists.mock.calls.length).toBe(callsBefore);
  });

  it('renders two assets with the same symbol but different asset_ids', async () => {
    const watchlist = makeWatchlist({
      items: [
        makeItem({ asset_id: 'a-1', symbol: 'AAPL', exchange: 'NASDAQ', name: 'Apple NASDAQ' }),
        makeItem({ asset_id: 'a-2', symbol: 'AAPL', exchange: 'NYSE', name: 'Apple NYSE' }),
      ],
    });
    listWatchlists.mockResolvedValue([watchlist]);
    renderPage();
    // Both rows render — proves the React key is asset_id, not symbol.
    expect(await screen.findByText('Apple NASDAQ')).toBeInTheDocument();
    expect(screen.getByText('Apple NYSE')).toBeInTheDocument();
  });

  it('writes the selection to the store on "view in dashboard"', async () => {
    const user = userEvent.setup();
    const watchlist = makeWatchlist({
      items: [
        makeItem({ asset_id: 'a-1', symbol: 'AAPL', exchange: 'NASDAQ', name: 'Apple Inc.' }),
      ],
    });
    listWatchlists.mockResolvedValue([watchlist]);
    renderPage();
    await screen.findByText('Apple Inc.');

    await user.click(screen.getByRole('button', { name: /View in dashboard/i }));

    await waitFor(() => {
      expect(useSelectionStore.getState().selectedAssetId).toBe('a-1');
    });
    expect(useSelectionStore.getState().selectedAsset?.symbol).toBe('AAPL');
  });
});
