/**
 * Backtest history route tests (FRA-64).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import BacktestHistoryPage from '@/pages/BacktestHistoryPage';
import i18n from '@/i18n';
import type { BacktestDetailRead, BacktestListResponse, BacktestRunRead } from '@/types/api';

const mocks = vi.hoisted(() => ({
  getBacktest: vi.fn<(runId: string) => Promise<BacktestDetailRead>>(),
  listBacktests: vi.fn<() => Promise<BacktestListResponse>>(),
}));

vi.mock('@/api/backtest', () => ({
  getBacktest: mocks.getBacktest,
  listBacktests: mocks.listBacktests,
}));

vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echarts" />,
}));

const run: BacktestRunRead = {
  id: 'run-1',
  user_id: 'u-1',
  name: 'Momentum smoke test',
  strategy_type: 'momentum',
  config_json: { universe: ['asset-1'], strategy_params: { lookback: 63, top_k: 1 } },
  benchmark_asset_id: null,
  start_date: '2024-01-01',
  end_date: '2024-03-31',
  price_field: 'adjusted',
  status: 'success',
  error_message: null,
  run_kind: 'backtest',
  created_at: '2024-04-01T00:00:00Z',
};

const detail: BacktestDetailRead = {
  run,
  metrics: null,
  equity_curve: [],
  trades: [],
};

function renderPage(initialPath = '/backtest/history/run-1') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/backtest" element={<div>CREATE BACKTEST</div>} />
        <Route path="/backtest/history" element={<BacktestHistoryPage />} />
        <Route path="/backtest/history/:runId" element={<BacktestHistoryPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mocks.getBacktest.mockReset();
  mocks.listBacktests.mockReset();
  mocks.listBacktests.mockResolvedValue({ items: [run], total: 1 });
  mocks.getBacktest.mockResolvedValue(detail);
  void i18n.changeLanguage('en');
});

describe('BacktestHistoryPage', () => {
  it('loads a run from the history detail route and renders result sections', async () => {
    renderPage();

    expect(await screen.findByRole('heading', { name: 'Backtest History' })).toBeInTheDocument();
    expect(await screen.findByText('Momentum smoke test')).toBeInTheDocument();
    expect(await screen.findByText('Performance metrics')).toBeInTheDocument();
    expect(screen.getByText('Equity curve')).toBeInTheDocument();
    expect(screen.getByText('Drawdown')).toBeInTheDocument();
    expect(screen.getByText('Trades')).toBeInTheDocument();

    expect(mocks.listBacktests).toHaveBeenCalled();
    expect(mocks.getBacktest).toHaveBeenCalledWith('run-1');
  });

  it('navigates back to the create route from the new-run button', async () => {
    const user = userEvent.setup();
    renderPage('/backtest/history');

    const buttons = await screen.findAllByRole('button', { name: /new backtest/i });
    await user.click(buttons[buttons.length - 1]);

    await waitFor(() => expect(screen.getByText('CREATE BACKTEST')).toBeInTheDocument());
  });
});
