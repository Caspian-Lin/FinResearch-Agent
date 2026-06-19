/**
 * OHLCV sync control (FRA-11).
 *
 * On click: pre-validate the window (≤1825 days, start ≤ end), enqueue a sync
 * job, then poll its status every 1.5s until terminal (success/failed) or the
 * 60-poll cap (~90s) is hit.
 *
 * Polling MUST terminate on every exit path:
 *  - terminal status (success/success_no_data/failed) → stop + surface result
 *  - poll cap reached → stop + timeout message
 *  - component unmount → clearTimeout in the effect cleanup
 *
 * On success and success_no_data the parent's `onSuccess` refetches ohlcv +
 * quality. A no-data terminal state is shown as a warning so provider
 * rate-limits / empty responses are not reported as successful data ingestion.
 * On failure we show the job's sanitized `error.message`.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Spin, Typography, message } from 'antd';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';

import { enqueueSync, getSyncJob } from '@/api/sync';
import { ApiError } from '@/api/client';
import type { SyncJobStatus } from '@/types/api';

/** Milliseconds between polls. */
const POLL_INTERVAL_MS = 1500;
/** Hard ceiling on poll count (~90s) before we give up. */
const MAX_POLLS = 60;
/** Maximum sync window the backend accepts, in days. */
const MAX_WINDOW_DAYS = 1825;

const { Text } = Typography;

interface SyncControlProps {
  assetId: string | null;
  source: string;
  start: string;
  end: string;
  /** Called after a successful sync so the parent can refetch ohlcv + quality. */
  onSuccess: () => void;
}

type Phase = 'idle' | 'polling' | 'success' | 'failed' | 'timeout';

export function SyncControl({ assetId, source, start, end, onSuccess }: SyncControlProps) {
  const { t } = useTranslation();
  const [messageApi, messageContext] = message.useMessage();
  const [phase, setPhase] = useState<Phase>('idle');
  const [status, setStatus] = useState<SyncJobStatus | null>(null);

  // The pending timeout id; cleared on cleanup / terminal / timeout so the
  // poll loop cannot survive unmount.
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Latest onSuccess ref so the poll loop always calls the freshest callback
  // without re-subscribing on every parent render.
  const onSuccessRef = useRef(onSuccess);
  onSuccessRef.current = onSuccess;

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // Cancel any in-flight poll when the component unmounts.
  useEffect(() => clearTimer, [clearTimer]);

  const handleSync = useCallback(async () => {
    if (!assetId) return;

    // --- Front-end pre-validation (immediate feedback, no 422 round-trip) ---
    const startD = dayjs(start);
    const endD = dayjs(end);
    if (!startD.isValid() || !endD.isValid() || endD.isBefore(startD)) {
      messageApi.error(t('errors:validation'));
      return;
    }
    if (endD.diff(startD, 'day') > MAX_WINDOW_DAYS) {
      messageApi.error(t('dashboard:sync.limit.window'));
      return;
    }

    setPhase('polling');
    setStatus(null);

    let jobId: string;
    try {
      const enqueued = await enqueueSync({ asset_id: assetId, start, end, source });
      jobId = enqueued.job_id;
    } catch (err) {
      if (err instanceof ApiError) {
        messageApi.error(t(`errors:${err.code}`));
      }
      setPhase('idle');
      return;
    }

    // Recursive poll via setTimeout so we can stop cleanly on terminal/cap.
    let polls = 0;

    const scheduleNext = () => {
      if (timerRef.current !== null) return; // already stopped
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        poll();
      }, POLL_INTERVAL_MS);
    };

    const poll = () => {
      polls += 1;

      getSyncJob(jobId)
        .then((job) => {
          setStatus(job.status);
          if (job.status === 'success') {
            setPhase('success');
            clearTimer();
            messageApi.success(t('dashboard:sync.status.success'));
            onSuccessRef.current();
          } else if (job.status === 'success_no_data') {
            setPhase('success');
            clearTimer();
            messageApi.warning(t('dashboard:sync.status.success_no_data'));
            onSuccessRef.current();
          } else if (job.status === 'failed') {
            setPhase('failed');
            clearTimer();
            messageApi.error(job.error?.message ?? t('dashboard:sync.status.failed'));
          } else if (polls >= MAX_POLLS) {
            // Still not terminal after the cap: give up.
            setPhase('timeout');
            clearTimer();
            messageApi.warning(t('dashboard:sync.timeout'));
          } else {
            scheduleNext();
          }
        })
        .catch(() => {
          // A transient poll failure shouldn't kill the whole job; retry once
          // more if under the cap, else stop with the timeout message.
          if (polls >= MAX_POLLS) {
            setPhase('timeout');
            clearTimer();
            messageApi.warning(t('dashboard:sync.timeout'));
          } else {
            scheduleNext();
          }
        });
    };

    poll();
  }, [assetId, source, start, end, t, messageApi, clearTimer]);

  const disabled = !assetId || phase === 'polling';

  return (
    <div>
      {messageContext}
      <Button onClick={() => void handleSync()} disabled={disabled} loading={phase === 'polling'}>
        {t('dashboard:sync.button')}
      </Button>

      {phase === 'polling' && status && (
        <span style={{ marginLeft: 12 }}>
          <Spin size="small" /> <Text type="secondary">{t(`dashboard:sync.status.${status}`)}</Text>
        </span>
      )}
    </div>
  );
}

export default SyncControl;
