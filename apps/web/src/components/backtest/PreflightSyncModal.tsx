/**
 * Pre-backtest data preflight modal (FRA-43).
 *
 * When the backtest config's universe / benchmark assets have insufficient
 * price coverage in the window (coverage < threshold), this modal lists them
 * and, on confirm, syncs each from the data source (yfinance) in parallel,
 * polling all jobs to terminal. On full success it tells the user to re-run the
 * backtest (the page does NOT auto-run — the user re-triggers manually, per the
 * chosen flow); on any failure it shows which asset failed and why, and does
 * NOT proceed.
 *
 * Reuses the FRA-8 sync endpoints (enqueueSync + getSyncJob) and the SyncControl
 * setTimeout-poll pattern (clean stop on terminal / cap / unmount). enqueueSync
 * uses Promise.allSettled so one failing enqueue doesn't discard the rest.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Modal, Progress, Typography, message } from 'antd';
import { useTranslation } from 'react-i18next';

import { enqueueSync, getSyncJob } from '@/api/sync';
import { ApiError } from '@/api/client';
import type { SyncJobStatus } from '@/types/api';

const { Text } = Typography;

/** Milliseconds between polls. */
const POLL_INTERVAL_MS = 1500;
/** Hard ceiling on poll count (~3 min). */
const MAX_POLLS = 120;

export interface MissingAsset {
  assetId: string;
  symbol: string;
  coverage: number;
}

interface PreflightSyncModalProps {
  open: boolean;
  missing: MissingAsset[];
  source: string;
  start: string;
  end: string;
  /**
   * i18n namespace whose `prefflight.*` subtree holds the copy (default
   * `'backtest'`). The factor page passes `'factor'` so the re-run hint says
   * "analysis" rather than "backtest"; the sync machinery is otherwise identical.
   */
  ns?: string;
  /** Close (cancel / done / failed) — parent closes the modal + resets phase. */
  onCancel: () => void;
}

type Phase = 'confirm' | 'syncing' | 'done' | 'failed';

interface JobState {
  assetId: string;
  symbol: string;
  status: SyncJobStatus | null;
  error: string | null;
}

export function PreflightSyncModal({
  open,
  missing,
  source,
  start,
  end,
  ns = 'backtest',
  onCancel,
}: PreflightSyncModalProps) {
  const { t } = useTranslation();
  const [messageApi, messageContext] = message.useMessage();
  /** Resolve a preflight copy key under the chosen namespace (`<ns>:preflight.*`).
   *  Plain fn (not memoized): handleSync below is a plain handler too, so neither
   *  sits in a useCallback dependency array that would need tp to be stable. */
  const tp = (key: string, opts?: Record<string, unknown>) => t(`${ns}:preflight.${key}`, opts);
  const [phase, setPhase] = useState<Phase>('confirm');
  const [jobs, setJobs] = useState<JobState[]>([]);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);
  useEffect(() => clearTimer, [clearTimer]);

  // Reset to the confirm screen whenever the modal opens with a fresh set.
  useEffect(() => {
    if (open) {
      setPhase('confirm');
      setJobs([]);
    }
  }, [open, missing]);

  const doneCount = jobs.filter((j) => j.status === 'success').length;
  const failedJobs = jobs.filter((j) => j.status === 'failed' || j.status === 'success_no_data');

  const handleSync = () => {
    setPhase('syncing');
    const initial: JobState[] = missing.map((m) => ({
      assetId: m.assetId,
      symbol: m.symbol,
      status: null,
      error: null,
    }));
    setJobs(initial);

    // Enqueue in parallel; allSettled so one rejection doesn't lose the rest.
    void Promise.allSettled(
      missing.map((m) => enqueueSync({ asset_id: m.assetId, start, end, source })),
    ).then((results) => {
      const next: JobState[] = initial.map((j, i) => {
        const r = results[i];
        return r.status === 'rejected'
          ? {
              ...j,
              status: 'failed',
              error:
                r.reason instanceof ApiError
                  ? (r.reason.detail ?? r.reason.code)
                  : tp('enqueueFailed'),
            }
          : j;
      });
      const enqueued: { jobId: string; idx: number }[] = [];
      results.forEach((r, i) => {
        if (r.status === 'fulfilled') enqueued.push({ jobId: r.value.job_id, idx: i });
      });
      setJobs(next);
      if (enqueued.length === 0) {
        setPhase('failed');
        messageApi.error(tp('syncFailed'));
        return;
      }

      // Recursive poll (SyncControl pattern): clean stop on terminal / cap.
      let polls = 0;
      const pollOnce = () => {
        polls += 1;
        Promise.all(enqueued.map((e) => getSyncJob(e.jobId).catch(() => null)))
          .then((snapshots) => {
            let cur = next;
            let allTerminal = true;
            snapshots.forEach((snap, i) => {
              if (snap === null) {
                allTerminal = false;
                return;
              }
              const idx = enqueued[i].idx;
              cur = cur.map((j, jidx) =>
                jidx === idx
                  ? { ...j, status: snap.status, error: snap.warning ?? snap.error?.message ?? null }
                  : j,
              );
              if (
                snap.status !== 'success' &&
                snap.status !== 'success_no_data' &&
                snap.status !== 'failed'
              ) {
                allTerminal = false;
              }
            });
            setJobs(cur);

            const allSuccess = cur.every((j) => j.status === 'success');
            const anyFailed = cur.some(
              (j) => j.status === 'failed' || j.status === 'success_no_data',
            );
            if (allSuccess) {
              clearTimer();
              setPhase('done');
              messageApi.success(tp('syncDone'));
            } else if (anyFailed && allTerminal) {
              clearTimer();
              setPhase('failed');
              messageApi.error(tp('syncFailed'));
            } else if (polls >= MAX_POLLS) {
              clearTimer();
              setPhase('failed');
              messageApi.warning(tp('syncTimeout'));
            } else {
              timerRef.current = setTimeout(() => {
                timerRef.current = null;
                pollOnce();
              }, POLL_INTERVAL_MS);
            }
          })
          .catch(() => {
            if (polls >= MAX_POLLS) {
              clearTimer();
              setPhase('failed');
              messageApi.warning(tp('syncTimeout'));
            } else {
              timerRef.current = setTimeout(() => {
                timerRef.current = null;
                pollOnce();
              }, POLL_INTERVAL_MS);
            }
          });
      };
      pollOnce();
    });
  };

  const pct = jobs.length > 0 ? Math.round((doneCount / jobs.length) * 100) : 0;
  const busy = phase === 'syncing';

  const footer = (
    <Button type="primary" onClick={busy ? undefined : onCancel} disabled={busy}>
      {phase === 'confirm' ? t('common:actions.cancel') : t('common:actions.close')}
    </Button>
  );

  return (
    <Modal
      open={open}
      title={tp('title')}
      onCancel={onCancel}
      footer={
        phase === 'confirm' ? (
          <>
            <Button onClick={onCancel}>{t('common:actions.cancel')}</Button>
            <Button type="primary" onClick={() => handleSync()}>
              {tp('syncButton')}
            </Button>
          </>
        ) : phase === 'syncing' ? null : (
          footer
        )
      }
      maskClosable={!busy}
      closable={!busy}
    >
      {messageContext}
      {phase === 'confirm' && (
        <div>
          <Text>{tp('body', { source, window: `${start} ~ ${end}` })}</Text>
          <ul style={{ marginTop: 12 }}>
            {missing.map((m) => (
              <li key={m.assetId}>
                <Text strong>{m.symbol}</Text>{' '}
                <Text type="secondary">
                  {tp('coverage', { pct: (m.coverage * 100).toFixed(0) })}
                </Text>
              </li>
            ))}
          </ul>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {tp('hint')}
          </Text>
        </div>
      )}
      {phase === 'syncing' && (
        <div>
          <Progress percent={pct} />
          <ul style={{ marginTop: 12 }}>
            {jobs.map((j) => (
              <li key={j.assetId}>
                <Text strong>{j.symbol}</Text>{' '}
                <Text type="secondary">
                  {j.status
                    ? t(`backtest:preflight.job.${j.status}`)
                    : tp('job.queued')}
                </Text>
              </li>
            ))}
          </ul>
        </div>
      )}
      {phase === 'done' && (
        <Alert
          type="success"
          showIcon
          message={tp('syncDone')}
          description={tp('rerunHint')}
        />
      )}
      {phase === 'failed' && (
        <Alert
          type="error"
          showIcon
          message={tp('syncFailed')}
          description={
            failedJobs.length > 0
              ? failedJobs.map((j) => `${j.symbol}: ${j.error ?? ''}`).join('; ')
              : tp('syncTimeout')
          }
        />
      )}
    </Modal>
  );
}

export default PreflightSyncModal;
