/**
 * Factor API client tests (FRA-58) — mock the `apiClient` layer (one level down)
 * and assert each function hits the right URL with the right payload/params and
 * returns the backend body. Mirrors `api/__tests__/watchlists.test.ts`.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/api/client', () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

import { apiClient } from '@/api/client';
import {
  computeFactors,
  enqueueFactorCompute,
  enqueueFactorSensitivity,
  enqueueQuantileBacktest,
  factorSensitivity,
  getFactorIC,
  getFactorJob,
  quantileBacktest,
} from '@/api/factors';

/* eslint-disable @typescript-eslint/unbound-method */
const mockGet = vi.mocked(apiClient.get);
const mockPost = vi.mocked(apiClient.post);
/* eslint-enable @typescript-eslint/unbound-method */

const baseReq = {
  universe: ['a-1', 'a-2'],
  source: 'yfinance',
  start: '2023-01-02',
  end: '2023-03-01',
  factor_names: ['momentum_21'],
};

describe('factor api client', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
  });

  it('computeFactors POSTs /factors/compute and returns body', async () => {
    mockPost.mockResolvedValueOnce({ data: { rows_written: 42 } });
    const res = await computeFactors(baseReq);
    expect(mockPost).toHaveBeenCalledWith('/factors/compute', baseReq);
    expect(res.rows_written).toBe(42);
  });

  it('getFactorIC GETs /factors/{name}/ic with query params', async () => {
    mockGet.mockResolvedValueOnce({ data: { factor_name: 'momentum_21' } });
    await getFactorIC('momentum_21', {
      universe: ['a-1', 'a-2'],
      source: 'yfinance',
      start: '2023-01-02',
      end: '2023-03-01',
      horizon: 5,
    });
    expect(mockGet).toHaveBeenCalledWith('/factors/momentum_21/ic', {
      params: {
        universe: ['a-1', 'a-2'],
        source: 'yfinance',
        start: '2023-01-02',
        end: '2023-03-01',
        horizon: 5,
      },
    });
  });

  it('quantileBacktest POSTs /factors/quantile-backtest', async () => {
    mockPost.mockResolvedValueOnce({ data: {} });
    await quantileBacktest({ ...baseReq, factor_name: 'momentum_21', n_quantiles: 5 });
    expect(mockPost).toHaveBeenCalledWith('/factors/quantile-backtest', expect.any(Object));
  });

  it('factorSensitivity POSTs /factors/sensitivity', async () => {
    mockPost.mockResolvedValueOnce({ data: {} });
    await factorSensitivity({ ...baseReq, factors: ['momentum'] });
    expect(mockPost).toHaveBeenCalledWith('/factors/sensitivity', expect.any(Object));
  });

  it('enqueueFactorCompute POSTs /factors/compute-async (202 job)', async () => {
    mockPost.mockResolvedValueOnce({ data: { run_id: 'r1', run_kind: 'factor_compute' } });
    const res = await enqueueFactorCompute(baseReq);
    expect(mockPost).toHaveBeenCalledWith('/factors/compute-async', baseReq);
    expect(res.run_kind).toBe('factor_compute');
  });

  it('enqueueQuantileBacktest POSTs /factors/quantile-backtest-async', async () => {
    mockPost.mockResolvedValueOnce({ data: { run_id: 'r2', run_kind: 'factor_quantile' } });
    const res = await enqueueQuantileBacktest({ ...baseReq, factor_name: 'rsi_14' });
    expect(mockPost).toHaveBeenCalledWith('/factors/quantile-backtest-async', expect.any(Object));
    expect(res.run_kind).toBe('factor_quantile');
  });

  it('enqueueFactorSensitivity POSTs /factors/sensitivity-async', async () => {
    mockPost.mockResolvedValueOnce({ data: { run_id: 'r3', run_kind: 'factor_sweep' } });
    const res = await enqueueFactorSensitivity({ ...baseReq, factors: ['rsi'] });
    expect(mockPost).toHaveBeenCalledWith('/factors/sensitivity-async', expect.any(Object));
    expect(res.run_kind).toBe('factor_sweep');
  });

  it('getFactorJob GETs /factors/jobs/{run_id}', async () => {
    mockGet.mockResolvedValueOnce({ data: { run_id: 'r1', status: 'success' } });
    const res = await getFactorJob('r1');
    expect(mockGet).toHaveBeenCalledWith('/factors/jobs/r1');
    expect(res.status).toBe('success');
  });
});
