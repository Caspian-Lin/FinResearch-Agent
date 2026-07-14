/**
 * Sentiment API client tests (FRA-72) — mock the `apiClient` layer (one level
 * down) and assert each function hits the right URL with the right
 * payload/params and returns the backend body. Mirrors `factors.test.ts`.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/api/client', () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

import { apiClient } from '@/api/client';
import {
  classifyNews,
  computeSentimentFactor,
  createComparison,
  enqueueClassifyNews,
  enqueueNewsSync,
  enqueueSentimentFactor,
  getComparison,
  getSentimentFactor,
  getSentimentJob,
  getSentimentSummaries,
  listNews,
  listSentimentScores,
  syncNews,
} from '@/api/sentiment';

/* eslint-disable @typescript-eslint/unbound-method */
const mockGet = vi.mocked(apiClient.get);
const mockPost = vi.mocked(apiClient.post);
/* eslint-enable @typescript-eslint/unbound-method */

const baseUniverse = ['a-1', 'a-2'];
const baseWindow = { start: '2024-01-01', end: '2024-03-01' };

describe('sentiment api client', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
  });

  // --- news sync -----------------------------------------------------------

  it('syncNews POSTs /sentiment/news/sync and returns body', async () => {
    mockPost.mockResolvedValueOnce({ data: { status: 'success', fetched: 10 } });
    const res = await syncNews({
      universe: baseUniverse,
      start: baseWindow.start,
      end: baseWindow.end,
    });
    expect(mockPost).toHaveBeenCalledWith('/sentiment/news/sync', expect.any(Object));
    expect(res.fetched).toBe(10);
  });

  it('enqueueNewsSync POSTs /sentiment/news/sync-async', async () => {
    mockPost.mockResolvedValueOnce({ data: { run_id: 'r1', run_kind: 'sentiment_sync_news' } });
    const res = await enqueueNewsSync({
      universe: baseUniverse,
      start: baseWindow.start,
      end: baseWindow.end,
    });
    expect(mockPost).toHaveBeenCalledWith('/sentiment/news/sync-async', expect.any(Object));
    expect(res.run_kind).toBe('sentiment_sync_news');
  });

  // --- news list -----------------------------------------------------------

  it('listNews GETs /sentiment/news with query params', async () => {
    mockGet.mockResolvedValueOnce({ data: { items: [], total: 0 } });
    await listNews({ asset_id: 'a-1', limit: 50 });
    expect(mockGet).toHaveBeenCalledWith('/sentiment/news', {
      params: { asset_id: 'a-1', limit: 50 },
    });
  });

  // --- classify ------------------------------------------------------------

  it('classifyNews POSTs /sentiment/score and returns body', async () => {
    mockPost.mockResolvedValueOnce({ data: { classified: 5, news: 10 } });
    const res = await classifyNews({
      universe: baseUniverse,
      start: baseWindow.start,
      end: baseWindow.end,
    });
    expect(mockPost).toHaveBeenCalledWith('/sentiment/score', expect.any(Object));
    expect(res.classified).toBe(5);
  });

  it('enqueueClassifyNews POSTs /sentiment/score-async', async () => {
    mockPost.mockResolvedValueOnce({ data: { run_id: 'r2', run_kind: 'sentiment_classify' } });
    const res = await enqueueClassifyNews({
      universe: baseUniverse,
      start: baseWindow.start,
      end: baseWindow.end,
    });
    expect(mockPost).toHaveBeenCalledWith('/sentiment/score-async', expect.any(Object));
    expect(res.run_kind).toBe('sentiment_classify');
  });

  // --- scores list ---------------------------------------------------------

  it('listSentimentScores GETs /sentiment/scores with query params', async () => {
    mockGet.mockResolvedValueOnce({ data: { items: [], total: 0 } });
    await listSentimentScores({ model_name: 'gpt-4o-mini' });
    expect(mockGet).toHaveBeenCalledWith('/sentiment/scores', {
      params: { model_name: 'gpt-4o-mini' },
    });
  });

  // --- factor --------------------------------------------------------------

  it('getSentimentFactor GETs /sentiment/factor with query params', async () => {
    mockGet.mockResolvedValueOnce({ data: { items: [], model_name: 'gpt-4o-mini' } });
    const res = await getSentimentFactor({
      universe: baseUniverse,
      start: baseWindow.start,
      end: baseWindow.end,
      model_name: 'gpt-4o-mini',
    });
    expect(mockGet).toHaveBeenCalledWith('/sentiment/factor', {
      params: {
        universe: baseUniverse,
        start: baseWindow.start,
        end: baseWindow.end,
        model_name: 'gpt-4o-mini',
      },
    });
    expect(res.model_name).toBe('gpt-4o-mini');
  });

  it('computeSentimentFactor POSTs /sentiment/factor/compute', async () => {
    mockPost.mockResolvedValueOnce({ data: { rows_written: 42 } });
    const res = await computeSentimentFactor({
      universe: baseUniverse,
      start: baseWindow.start,
      end: baseWindow.end,
      model_name: 'gpt-4o-mini',
    });
    expect(mockPost).toHaveBeenCalledWith('/sentiment/factor/compute', expect.any(Object));
    expect(res.rows_written).toBe(42);
  });

  it('enqueueSentimentFactor POSTs /sentiment/factor/compute-async', async () => {
    mockPost.mockResolvedValueOnce({ data: { run_id: 'r3', run_kind: 'sentiment_factor' } });
    const res = await enqueueSentimentFactor({
      universe: baseUniverse,
      start: baseWindow.start,
      end: baseWindow.end,
      model_name: 'gpt-4o-mini',
    });
    expect(mockPost).toHaveBeenCalledWith('/sentiment/factor/compute-async', expect.any(Object));
    expect(res.run_kind).toBe('sentiment_factor');
  });

  // --- summaries -----------------------------------------------------------

  it('getSentimentSummaries GETs /sentiment/summaries', async () => {
    mockGet.mockResolvedValueOnce({ data: { items: [], total: 0 } });
    await getSentimentSummaries({
      universe: baseUniverse,
      start: baseWindow.start,
      end: baseWindow.end,
      model_name: 'gpt-4o-mini',
      window_days: 7,
    });
    expect(mockGet).toHaveBeenCalledWith('/sentiment/summaries', {
      params: {
        universe: baseUniverse,
        start: baseWindow.start,
        end: baseWindow.end,
        model_name: 'gpt-4o-mini',
        window_days: 7,
      },
    });
  });

  // --- job poll ------------------------------------------------------------

  it('getSentimentJob GETs /sentiment/jobs/{run_id}', async () => {
    mockGet.mockResolvedValueOnce({ data: { run_id: 'r1', status: 'success' } });
    const res = await getSentimentJob('r1');
    expect(mockGet).toHaveBeenCalledWith('/sentiment/jobs/r1');
    expect(res.status).toBe('success');
  });

  // --- comparison ----------------------------------------------------------

  it('createComparison POSTs /backtest/comparison', async () => {
    mockPost.mockResolvedValueOnce({ data: { run_id: 'rc1', status: 'pending' } });
    const res = await createComparison({
      name: 'test',
      universe: baseUniverse,
      start: baseWindow.start,
      end: baseWindow.end,
      model_name: 'gpt-4o-mini',
    });
    expect(mockPost).toHaveBeenCalledWith('/backtest/comparison', expect.any(Object));
    expect(res.run_id).toBe('rc1');
  });

  it('getComparison GETs /backtest/comparison/{run_id}', async () => {
    mockGet.mockResolvedValueOnce({ data: { run: {}, children: [] } });
    await getComparison('rc1');
    expect(mockGet).toHaveBeenCalledWith('/backtest/comparison/rc1');
  });
});
