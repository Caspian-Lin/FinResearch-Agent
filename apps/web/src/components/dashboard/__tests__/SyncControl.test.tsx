/**
 * SyncControl component tests (FRA-11).
 *
 * Focus: the polling lifecycle terminates on every exit path. We use fake timers
 * + mocked api/sync and flush microtasks with `advanceTimersByTimeAsync`. antd's
 * `message` API renders via the component's own context, so success/failure text
 * appears in the DOM.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';

import { SyncControl } from '@/components/dashboard/SyncControl';
import i18n from '@/i18n';
import type { SyncEnqueueResponse, SyncJob } from '@/types/api';

const mocks = vi.hoisted(() => ({
  enqueueSync:
    vi.fn<
      (p: {
        asset_id: string;
        start: string;
        end: string;
        source: string;
      }) => Promise<SyncEnqueueResponse>
    >(),
  getSyncJob: vi.fn<(jobId: string) => Promise<SyncJob>>(),
}));

vi.mock('@/api/sync', () => ({
  enqueueSync: mocks.enqueueSync,
  getSyncJob: mocks.getSyncJob,
}));

const { enqueueSync, getSyncJob } = mocks;

function makeJob(overrides: Partial<SyncJob> = {}): SyncJob {
  return {
    job_id: 'job-1',
    status: 'pending',
    asset_id: 'a-1',
    start: '2024-01-01',
    end: '2024-01-31',
    source: 'yfinance',
    inserted: 0,
    updated: 0,
    total_bars: 0,
    warning: null,
    error: null,
    ...overrides,
  };
}

function defaultProps(overrides: Partial<React.ComponentProps<typeof SyncControl>> = {}) {
  return {
    assetId: 'a-1',
    source: 'yfinance',
    start: '2024-01-01',
    end: '2024-01-31',
    onSuccess: vi.fn(),
    ...overrides,
  };
}

beforeEach(async () => {
  vi.useFakeTimers();
  await i18n.changeLanguage('en');
  enqueueSync.mockReset();
  getSyncJob.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

function clickSync() {
  // fireEvent (not userEvent): under fake timers, userEvent's internal
  // pointer-move delays never flush and the click never lands. The button's
  // onClick is a plain handler, so a direct click is sufficient.
  act(() => {
    fireEvent.click(screen.getByRole('button', { name: /sync data/i }));
  });
}

describe('SyncControl', () => {
  it('enqueues, polls pending then success, stops polling and calls onSuccess', async () => {
    enqueueSync.mockResolvedValue({
      job_id: 'job-1',
      status: 'pending',
      asset_id: 'a-1',
      start: '2024-01-01',
      end: '2024-01-31',
      source: 'yfinance',
    });
    // First poll: pending; second poll: success.
    getSyncJob.mockResolvedValueOnce(makeJob({ status: 'pending' }));
    getSyncJob.mockResolvedValueOnce(makeJob({ status: 'success', inserted: 10 }));

    const onSuccess = vi.fn();
    render(<SyncControl {...defaultProps({ onSuccess })} />);

    clickSync();
    expect(enqueueSync).toHaveBeenCalledTimes(1);

    // Drive the timer forward in poll-interval steps until the success state
    // is reached. Microtask vs macrotask ordering under fake timers makes a
    // precise per-advance call-count fragile, so we assert on the end state
    // (terminal + stopped) instead.
    for (let i = 0; i < 5 && !onSuccess.mock.calls.length; i += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1500);
      });
    }

    // Success message surfaced and onSuccess invoked exactly once.
    expect(screen.getByText(/sync complete/i)).toBeInTheDocument();
    expect(onSuccess).toHaveBeenCalledTimes(1);

    // Polling stopped: advancing further makes no extra getSyncJob calls.
    const callsAtTerminal = getSyncJob.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(getSyncJob.mock.calls.length).toBe(callsAtTerminal);
  });

  it('stops polling on failed and surfaces the sanitized error.message', async () => {
    enqueueSync.mockResolvedValue({
      job_id: 'job-1',
      status: 'pending',
      asset_id: 'a-1',
      start: '2024-01-01',
      end: '2024-01-31',
      source: 'yfinance',
    });
    getSyncJob.mockResolvedValueOnce(
      makeJob({ status: 'failed', error: { type: 'x', message: 'sanitized failure reason' } }),
    );

    render(<SyncControl {...defaultProps()} />);
    clickSync();

    // Step until the failed message appears.
    let msg: ReturnType<typeof screen.queryByText> = null;
    for (let i = 0; i < 5 && !msg; i += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1500);
      });
      msg = screen.queryByText('sanitized failure reason');
    }
    expect(msg).not.toBeNull();
    // Polling stopped after the terminal failure.
    const callsAtTerminal = getSyncJob.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(getSyncJob.mock.calls.length).toBe(callsAtTerminal);
  });

  it('stops polling on success_no_data, warns, and still refreshes', async () => {
    enqueueSync.mockResolvedValue({
      job_id: 'job-1',
      status: 'pending',
      asset_id: 'a-1',
      start: '2024-01-01',
      end: '2024-01-31',
      source: 'yfinance',
    });
    getSyncJob.mockResolvedValueOnce(makeJob({ status: 'success_no_data', total_bars: 0 }));

    const onSuccess = vi.fn();
    render(<SyncControl {...defaultProps({ onSuccess })} />);
    clickSync();

    let msg: ReturnType<typeof screen.queryByText> = null;
    for (let i = 0; i < 5 && !msg; i += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1500);
      });
      msg = screen.queryByText(/data source returned no bars/i);
    }
    expect(msg).not.toBeNull();
    expect(onSuccess).toHaveBeenCalledTimes(1);

    const callsAtTerminal = getSyncJob.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(getSyncJob.mock.calls.length).toBe(callsAtTerminal);
  });

  it('rejects a window > 1825 days with the limit message and never enqueues', () => {
    // 1826 days apart (2024-01-01 → 2029-01-01 ≈ 1826 days).
    const onSuccess = vi.fn();
    render(
      <SyncControl
        assetId="a-1"
        source="yfinance"
        start="2024-01-01"
        end="2029-01-01"
        onSuccess={onSuccess}
      />,
    );
    clickSync();
    expect(screen.getByText(/1825-day sync limit/i)).toBeInTheDocument();
    expect(enqueueSync).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it('rejects start>end with the validation message and never enqueues', () => {
    const onSuccess = vi.fn();
    render(
      <SyncControl
        assetId="a-1"
        source="yfinance"
        start="2024-06-01"
        end="2024-01-01"
        onSuccess={onSuccess}
      />,
    );
    clickSync();
    expect(screen.getByText(/some fields are invalid/i)).toBeInTheDocument();
    expect(enqueueSync).not.toHaveBeenCalled();
  });

  it('stops polling when the component unmounts (cleanup clears the timer)', async () => {
    enqueueSync.mockResolvedValue({
      job_id: 'job-1',
      status: 'pending',
      asset_id: 'a-1',
      start: '2024-01-01',
      end: '2024-01-31',
      source: 'yfinance',
    });
    // Always pending so the only thing that can stop polling is the cap/unmount.
    getSyncJob.mockResolvedValue(makeJob({ status: 'pending' }));

    const { unmount } = render(<SyncControl {...defaultProps()} />);
    clickSync();

    // Run one poll to arm the next timer.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    const callsBeforeUnmount = getSyncJob.mock.calls.length;
    expect(callsBeforeUnmount).toBeGreaterThanOrEqual(1);

    unmount();

    // No further polls should fire after unmount.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(getSyncJob.mock.calls.length).toBe(callsBeforeUnmount);
  });

  it('gives up with the timeout message after the 60-poll cap (always pending)', async () => {
    enqueueSync.mockResolvedValue({
      job_id: 'job-1',
      status: 'pending',
      asset_id: 'a-1',
      start: '2024-01-01',
      end: '2024-01-31',
      source: 'yfinance',
    });
    getSyncJob.mockResolvedValue(makeJob({ status: 'pending' }));

    render(<SyncControl {...defaultProps()} />);
    clickSync();

    // Run every scheduled timer + microtask to completion. With getSyncJob
    // always pending, the poll loop keeps scheduling 1500ms timers until the
    // 60-poll cap is reached; runAllTimersAsync drains them and the cap's
    // `.then` (which sets phase=timeout + messageApi.warning).
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(screen.getByText(/taking longer than expected/i)).toBeInTheDocument();
    // Exactly MAX_POLLS (60) polls fired before giving up.
    expect(getSyncJob.mock.calls.length).toBe(60);

    // No further polls after the cap.
    const capped = getSyncJob.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(getSyncJob.mock.calls.length).toBe(capped);
  });

  it('switches language: the pending status label becomes zh-CN while polling', async () => {
    enqueueSync.mockResolvedValue({
      job_id: 'job-1',
      status: 'pending',
      asset_id: 'a-1',
      start: '2024-01-01',
      end: '2024-01-31',
      source: 'yfinance',
    });
    getSyncJob.mockResolvedValue(makeJob({ status: 'pending' }));

    render(<SyncControl {...defaultProps()} />);
    clickSync();

    // First poll resolves pending → status label shown.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(screen.getByText('Queued…')).toBeInTheDocument();

    await act(async () => {
      await i18n.changeLanguage('zh-CN');
    });
    expect(screen.getByText('排队中…')).toBeInTheDocument();
  });
});
