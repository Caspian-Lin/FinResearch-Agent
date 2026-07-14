/**
 * Backtest history page.
 *
 * Owns recent-run loading and historical detail inspection. Pending/running
 * runs are polled to terminal status when opened, matching the create page's
 * lifecycle handling without mixing the create form into this route.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, Button, Empty, Spin, Typography, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';

import { getBacktest, listBacktests } from '@/api/backtest';
import { ApiError } from '@/api/client';
import { BacktestHistorySidebar } from '@/components/backtest/BacktestHistorySidebar';
import { BacktestResultDetail } from '@/components/backtest/BacktestResultDetail';
import { SiderLayout } from '@/components/layout/SiderLayout';
import type { BacktestDetailRead, BacktestRunRead } from '@/types/api';

const { Title, Text } = Typography;

const POLL_INTERVAL_MS = 1500;
const MAX_POLLS = 120;

type Phase = 'idle' | 'loading' | 'polling' | 'success' | 'failed' | 'timeout';

function BacktestHistoryPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { runId } = useParams<{ runId: string }>();
  const [messageApi, messageContext] = message.useMessage();

  const [history, setHistory] = useState<BacktestRunRead[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [detail, setDetail] = useState<BacktestDetailRead | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(runId ?? null);
  const [phase, setPhase] = useState<Phase>(runId ? 'loading' : 'idle');

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);
  useEffect(() => clearTimer, [clearTimer]);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const res = await listBacktests({ limit: 20 });
      setHistory(res.items);
    } catch (err) {
      if (err instanceof ApiError) messageApi.error(t(`errors:${err.code}`));
    } finally {
      setHistoryLoading(false);
    }
  }, [messageApi, t]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  const startPolling = useCallback(
    (id: string) => {
      let polls = 0;
      const scheduleNext = () => {
        if (timerRef.current !== null) return;
        timerRef.current = setTimeout(() => {
          timerRef.current = null;
          doPoll();
        }, POLL_INTERVAL_MS);
      };
      const doPoll = () => {
        polls += 1;
        getBacktest(id)
          .then((d) => {
            setDetail(d);
            setSelectedRunId(d.run.id);
            if (d.run.status === 'success') {
              setPhase('success');
              clearTimer();
              void loadHistory();
            } else if (d.run.status === 'failed') {
              setPhase('failed');
              clearTimer();
              void loadHistory();
            } else if (polls >= MAX_POLLS) {
              setPhase('timeout');
              clearTimer();
              messageApi.warning(t('backtest:run.timeout'));
            } else {
              setPhase('polling');
              scheduleNext();
            }
          })
          .catch(() => {
            if (polls >= MAX_POLLS) {
              setPhase('timeout');
              clearTimer();
              messageApi.warning(t('backtest:run.timeout'));
            } else {
              scheduleNext();
            }
          });
      };
      doPoll();
    },
    [clearTimer, loadHistory, messageApi, t],
  );

  const openRun = useCallback(
    async (id: string, replace = false) => {
      clearTimer();
      setSelectedRunId(id);
      setPhase('loading');
      if (runId !== id) {
        navigate(`/backtest/history/${id}`, { replace });
      }
      try {
        const d = await getBacktest(id);
        setDetail(d);
        setSelectedRunId(d.run.id);
        if (d.run.status === 'success') {
          setPhase('success');
        } else if (d.run.status === 'failed') {
          setPhase('failed');
        } else {
          setPhase('polling');
          startPolling(id);
        }
      } catch (err) {
        if (err instanceof ApiError) messageApi.error(t(`errors:${err.code}`));
        setDetail(null);
        setPhase('idle');
      }
    },
    [clearTimer, messageApi, navigate, runId, startPolling, t],
  );

  useEffect(() => {
    if (runId) {
      void openRun(runId, true);
    }
  }, [openRun, runId]);

  return (
    <SiderLayout
      sidebar={
        <BacktestHistorySidebar
          history={history}
          loading={historyLoading}
          activeKey="history"
          selectedRunId={selectedRunId}
          onOpenRun={(id) => void openRun(id)}
          onNewRun={() => navigate('/backtest')}
          onOpenHistory={() => navigate('/backtest/history')}
        />
      }
    >
      <div className="page">
        {messageContext}
        <div className="page-header">
          <div>
            <Title level={2} className="page-title">
              {t('backtest:historyPage.title')}
            </Title>
            <Text type="secondary" className="page-description">
              {t('backtest:historyPage.description')}
            </Text>
          </div>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/backtest')}>
            {t('backtest:run.new')}
          </Button>
        </div>

        {(phase === 'loading' || phase === 'polling') && (
          <div className="loading-block">
            <Spin
              tip={phase === 'polling' ? t('backtest:run.polling') : t('common:actions.loading')}
            >
              <div style={{ height: 48 }} />
            </Spin>
          </div>
        )}

        {phase === 'timeout' && (
          <Alert type="warning" showIcon message={t('backtest:run.timeout')} />
        )}

        {phase === 'failed' && detail && (
          <Alert
            type="error"
            showIcon
            message={t('backtest:run.failed')}
            description={detail.run.error_message ?? undefined}
          />
        )}

        {detail && (phase === 'success' || phase === 'failed') && (
          <BacktestResultDetail detail={detail} />
        )}

        {phase === 'idle' && !detail && <Empty description={t('backtest:historyPage.empty')} />}
      </div>
    </SiderLayout>
  );
}

export default BacktestHistoryPage;
