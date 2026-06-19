/**
 * DashboardPage component tests (FRA-11).
 *
 * The API layer (`@/api/ohlcv`, `@/api/quality`) is mocked at the module
 * boundary; the selection store is driven directly via its getState setter.
 * MemoryRouter wraps the page so the `<Link to="/watchlist">` renders.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

import DashboardPage from '@/pages/DashboardPage';
import { useSelectionStore } from '@/store/selection';
import { ApiError } from '@/api/client';
import i18n from '@/i18n';
import type { OhlcvRead, QualityReport } from '@/types/api';

const mocks = vi.hoisted(() => ({
  fetchOhlcv:
    vi.fn<
      (p: { asset_id: string; source: string; start: string; end: string }) => Promise<OhlcvRead[]>
    >(),
  fetchQuality:
    vi.fn<
      (p: {
        asset_id: string;
        source: string;
        start: string;
        end: string;
      }) => Promise<QualityReport>
    >(),
}));

vi.mock('@/api/ohlcv', () => ({ fetchOhlcv: mocks.fetchOhlcv }));
vi.mock('@/api/quality', () => ({ fetchQuality: mocks.fetchQuality }));

// The sidebar lifts useWatchlists; mock it so no real request fires and the
// empty-selection case stays controllable (empty list → auto-select inert).
const watchlistsMock = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/useWatchlists', () => ({ useWatchlists: watchlistsMock }));

// Stub echarts-for-react so DashboardPage's PriceChart never touches canvas in
// jsdom (the real renderer throws on null canvas context). We only need the
// chart presence as a signal, not its internals.
vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echarts" />,
}));

const { fetchOhlcv, fetchQuality } = mocks;

function makeBar(overrides: Partial<OhlcvRead> = {}): OhlcvRead {
  return {
    asset_id: 'a-1',
    time: '2024-01-02T00:00:00Z',
    source: 'yfinance',
    open: 10,
    high: 11,
    low: 9,
    close: 10,
    adjusted_close: 10,
    volume: 1000,
    ...overrides,
  };
}

function makeReport(overrides: Partial<QualityReport> = {}): QualityReport {
  return {
    asset_id: 'a-1',
    source: 'yfinance',
    start: '2024-01-01',
    end: '2024-01-31',
    expected_sessions: 22,
    observed_sessions: 20,
    missing_sessions_count: 2,
    coverage: 0.875,
    missing_sessions: ['2024-01-15'],
    anomalies: [],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <Routes>
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/watchlist" element={<div>WATCHLIST PAGE</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  fetchOhlcv.mockReset();
  fetchQuality.mockReset();
  useSelectionStore.getState().clearSelection();
  watchlistsMock.mockReset();
  // Default: no watchlists → sidebar empty, auto-select stays inert.
  watchlistsMock.mockReturnValue({ watchlists: [], loading: false, error: null });
  void i18n.changeLanguage('en');
});

describe('DashboardPage', () => {
  it('shows the empty-selection state with a link to the watchlist when nothing is selected', () => {
    renderPage();
    expect(
      screen.getByText('Select an asset from your watchlist to view its dashboard.'),
    ).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Go to watchlist' });
    expect(link).toHaveAttribute('href', '/watchlist');
    // No fetches fire without a selection.
    expect(fetchOhlcv).not.toHaveBeenCalled();
    expect(fetchQuality).not.toHaveBeenCalled();
  });

  it('fetches ohlcv + quality and renders chart, panel, sync control on success', async () => {
    useSelectionStore.getState().setSelectedAsset({
      asset_id: 'a-1',
      symbol: 'AAPL',
      exchange: 'NASDAQ',
      name: 'Apple Inc.',
    });
    fetchOhlcv.mockResolvedValue([makeBar(), makeBar({ time: '2024-01-03T00:00:00Z' })]);
    fetchQuality.mockResolvedValue(makeReport());

    renderPage();

    // Header shows the selected asset identity.
    expect(await screen.findByText(/Apple Inc\./)).toBeInTheDocument();
    // PriceChart fallback note + coverage appear.
    expect(
      await screen.findByText('Adjusted close, falling back to close when missing.'),
    ).toBeInTheDocument();
    expect(screen.getByText('87.5%')).toBeInTheDocument();
    // Sync button + data-limit notice present.
    expect(screen.getByRole('button', { name: /sync data/i })).toBeInTheDocument();
    expect(screen.getByText('Data limitations')).toBeInTheDocument();

    expect(fetchOhlcv).toHaveBeenCalledTimes(1);
    expect(fetchQuality).toHaveBeenCalledTimes(1);
  });

  it('shows partial results: ohlcv succeeds while quality fails with its error code', async () => {
    useSelectionStore.getState().setSelectedAsset({
      asset_id: 'a-1',
      symbol: 'AAPL',
      exchange: 'NASDAQ',
      name: 'Apple Inc.',
    });
    fetchOhlcv.mockResolvedValue([makeBar()]);
    fetchQuality.mockRejectedValue(new ApiError('server', 500, 'internal leak'));

    renderPage();

    // PriceChart shows data.
    expect(
      await screen.findByText('Adjusted close, falling back to close when missing.'),
    ).toBeInTheDocument();
    // QualityPanel shows the server error, not the raw detail.
    await waitFor(() => {
      expect(
        screen.getByText('Server error. We have been notified. Please retry later.'),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText('internal leak')).toBeNull();
  });

  it('never surfaces the backend detail on an ohlcv failure', async () => {
    useSelectionStore.getState().setSelectedAsset({
      asset_id: 'a-1',
      symbol: 'AAPL',
      exchange: 'NASDAQ',
      name: 'Apple Inc.',
    });
    fetchOhlcv.mockRejectedValue(new ApiError('notFound', 404, 'SECRET'));
    fetchQuality.mockResolvedValue(makeReport());

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('The requested resource was not found.')).toBeInTheDocument();
    });
    expect(screen.queryByText('SECRET')).toBeNull();
  });

  it('shows the loading state while ohlcv is pending', async () => {
    useSelectionStore.getState().setSelectedAsset({
      asset_id: 'a-1',
      symbol: 'AAPL',
      exchange: 'NASDAQ',
      name: 'Apple Inc.',
    });
    let resolveOhlcv!: (v: OhlcvRead[]) => void;
    let resolveQuality!: (v: QualityReport) => void;
    fetchOhlcv.mockReturnValue(
      new Promise((res) => {
        resolveOhlcv = res;
      }),
    );
    fetchQuality.mockReturnValue(
      new Promise((res) => {
        resolveQuality = res;
      }),
    );

    renderPage();
    // Both the price chart and the quality panel show their loading Spin copy.
    expect((await screen.findAllByText('Loading…')).length).toBeGreaterThanOrEqual(1);

    // Resolve to unmount cleanly.
    act(() => {
      resolveOhlcv([makeBar()]);
      resolveQuality(makeReport());
    });
  });

  it('does not re-fetch when only the language changes', async () => {
    useSelectionStore.getState().setSelectedAsset({
      asset_id: 'a-1',
      symbol: 'AAPL',
      exchange: 'NASDAQ',
      name: 'Apple Inc.',
    });
    fetchOhlcv.mockResolvedValue([makeBar()]);
    fetchQuality.mockResolvedValue(makeReport());

    renderPage();
    // Wait for the initial fetch round to settle.
    await screen.findByText('Adjusted close, falling back to close when missing.');

    const ohlcvCallsBefore = fetchOhlcv.mock.calls.length;
    const qualityCallsBefore = fetchQuality.mock.calls.length;

    await act(async () => {
      await i18n.changeLanguage('zh-CN');
    });
    // Labels re-render in Chinese but data is not refetched.
    expect(screen.getByText('使用复权收盘价,缺失时回退到收盘价。')).toBeInTheDocument();
    expect(fetchOhlcv.mock.calls.length).toBe(ohlcvCallsBefore);
    expect(fetchQuality.mock.calls.length).toBe(qualityCallsBefore);
  });

  it('auto-selects the first asset of the first watchlist on entry', async () => {
    watchlistsMock.mockReturnValue({
      watchlists: [
        {
          watchlist_id: 'wl-1',
          name: 'Tech',
          created_at: '',
          items: [
            {
              asset_id: 'a-1',
              symbol: 'AAPL',
              exchange: 'NASDAQ',
              name: 'Apple Inc.',
              added_at: '',
            },
            {
              asset_id: 'a-2',
              symbol: 'NVDA',
              exchange: 'NASDAQ',
              name: 'NVIDIA',
              added_at: '',
            },
          ],
        },
      ],
      loading: false,
      error: null,
    });
    fetchOhlcv.mockResolvedValue([makeBar()]);
    fetchQuality.mockResolvedValue(makeReport());

    renderPage();

    // First asset auto-selected → the data fetch fires for its asset_id and the
    // main area renders (the data-limit notice only shows with a selection).
    await waitFor(() => {
      expect(fetchOhlcv).toHaveBeenCalledWith(expect.objectContaining({ asset_id: 'a-1' }));
    });
    expect(await screen.findByText('Data limitations')).toBeInTheDocument();
  });
});
