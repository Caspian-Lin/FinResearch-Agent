/**
 * Backtest page (FRA-38) — configure → trigger → poll → visualize.
 *
 * Flow mirrors the FRA-8 sync trigger+poll pattern: the config form POSTs
 * `/backtest` (202 → run_id), then a setTimeout chain polls `GET /backtest/{id}`
 * every 1.5s until terminal (success/failed) or the ~3-min cap, then renders
 * metrics (gross/net), the strategy-vs-benchmark equity curve, the drawdown
 * curve, and the trade-detail table. A recent-runs list lets the user reopen
 * past results. Polling always terminates (terminal / cap / unmount cleanup).
 *
 * Errors map to `t('errors:<code>')` and never surface the backend `detail`,
 * except the run's own `error_message` on a failed run (a short backend message).
 * This page only *displays* results; the worker does all computation (FRA-37).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, Card, Col, Empty, Row, Spin, Table, Typography, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';

import { createBacktest, getBacktest, listBacktests } from '@/api/backtest';
import { ApiError } from '@/api/client';
import { useWatchlists } from '@/hooks/useWatchlists';
import { BacktestConfigForm } from '@/components/backtest/BacktestConfigForm';
import { BacktestCurveChart } from '@/components/backtest/BacktestCurveChart';
import { MetricsCards } from '@/components/backtest/MetricsCards';
import { TradesTable } from '@/components/backtest/TradesTable';
import {
  buildDrawdownOption,
  buildEquityCurveOption,
} from '@/components/backtest/equityChartOption';
import type { BacktestCreateRequest, BacktestDetailRead, BacktestRunRead } from '@/types/api';

const { Title, Text } = Typography;

/** Milliseconds between polls. */
const POLL_INTERVAL_MS = 1500;
/** Hard ceiling on poll count (~3 min) before we stop auto-refreshing. */
const MAX_POLLS = 120;

type Phase = 'idle' | 'polling' | 'success' | 'failed' | 'timeout';

function BacktestPage() {
  const { t } = useTranslation();
  const [messageApi, messageContext] = message.useMessage();
  const { watchlists } = useWatchlists();

  const [submitting, setSubmitting] = useState(false);
  const [detail, setDetail] = useState<BacktestDetailRead | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [symbolByAsset, setSymbolByAsset] = useState<Record<string, string>>({});
  const [history, setHistory] = useState<BacktestRunRead[]>([]);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);
  useEffect(() => clearTimer, [clearTimer]);

  const loadHistory = useCallback(async () => {
    try {
      const res = await listBacktests({ limit: 10 });
      setHistory(res.items);
    } catch {
      // history is best-effort; a failure leaves the previous list in place.
    }
  }, []);
  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  // Recursive poll (SyncControl pattern): a setTimeout chain so we stop cleanly
  // on terminal status, the cap, or component unmount.
  const startPolling = useCallback(
    (runId: string) => {
      let polls = 0;
      const scheduleNext = () => {
        if (timerRef.current !== null) return; // already stopped
        timerRef.current = setTimeout(() => {
          timerRef.current = null;
          doPoll();
        }, POLL_INTERVAL_MS);
      };
      const doPoll = () => {
        polls += 1;
        getBacktest(runId)
          .then((d) => {
            setDetail(d);
            if (d.run.status === 'success') {
              setPhase('success');
              clearTimer();
              messageApi.success(t('backtest:run.success'));
              void loadHistory();
            } else if (d.run.status === 'failed') {
              setPhase('failed');
              clearTimer();
              messageApi.error(t('backtest:run.failed'));
              void loadHistory();
            } else if (polls >= MAX_POLLS) {
              setPhase('timeout');
              clearTimer();
              messageApi.warning(t('backtest:run.timeout'));
            } else {
              scheduleNext();
            }
          })
          .catch(() => {
            // A transient poll failure shouldn't kill the run; retry if under cap.
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
    [clearTimer, messageApi, t, loadHistory],
  );

  const handleRun = useCallback(
    async (req: BacktestCreateRequest, symbols: Record<string, string>) => {
      if (req.universe.length === 0) {
        messageApi.error(t('errors:validation'));
        return;
      }
      setSubmitting(true);
      setSymbolByAsset(symbols);
      try {
        const enqueued = await createBacktest(req);
        setDetail(null);
        setPhase('polling');
        messageApi.info(t('backtest:run.triggered'));
        startPolling(enqueued.run_id);
      } catch (err) {
        if (err instanceof ApiError) messageApi.error(t(`errors:${err.code}`));
        setPhase('idle');
      } finally {
        setSubmitting(false);
      }
    },
    [startPolling, messageApi, t],
  );

  const handleOpenHistory = useCallback(
    async (runId: string) => {
      clearTimer();
      try {
        const d = await getBacktest(runId);
        setDetail(d);
        setSymbolByAsset({});
        if (d.run.status === 'success') {
          setPhase('success');
        } else if (d.run.status === 'failed') {
          setPhase('failed');
        } else {
          // pending / running → keep polling to terminal.
          setPhase('polling');
          startPolling(runId);
        }
      } catch (err) {
        if (err instanceof ApiError) messageApi.error(t(`errors:${err.code}`));
        setPhase('idle');
      }
    },
    [clearTimer, startPolling, messageApi, t],
  );

  const historyColumns: ColumnsType<BacktestRunRead> = [
    { title: t('backtest:history.run'), dataIndex: 'name', key: 'name' },
    {
      title: t('backtest:history.strategy'),
      dataIndex: 'strategy_type',
      key: 'strategy',
      render: (s: string) => t(`backtest:strategy.${s}`, { defaultValue: s }),
    },
    {
      title: t('backtest:history.status'),
      dataIndex: 'status',
      key: 'status',
      render: (s: string) => t(`backtest:status.${s}`, { defaultValue: s }),
    },
    {
      title: t('backtest:history.created'),
      dataIndex: 'created_at',
      key: 'created_at',
      render: (c: string) => dayjs(c).format('YYYY-MM-DD HH:mm'),
    },
  ];

  return (
    <div>
      {messageContext}
      <Title level={2} style={{ marginBottom: 4 }}>
        {t('backtest:page.title')}
      </Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
        {t('backtest:page.description')}
      </Text>

      <Card title={t('backtest:form.title')} size="small" style={{ marginBottom: 16 }}>
        <BacktestConfigForm
          watchlists={watchlists}
          submitting={submitting}
          onSubmit={(req, symbols) => void handleRun(req, symbols)}
        />
      </Card>

      {phase === 'polling' && (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin tip={t('backtest:run.polling')}>
            <div style={{ height: 48 }} />
          </Spin>
        </div>
      )}

      {phase === 'timeout' && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('backtest:run.timeout')}
        />
      )}

      {phase === 'failed' && detail && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('backtest:run.failed')}
          description={detail.run.error_message ?? undefined}
        />
      )}

      {detail && (phase === 'success' || phase === 'failed') && (
        <Row gutter={[16, 16]}>
          <Col span={24}>
            <MetricsCards metrics={detail.metrics} />
          </Col>
          <Col xs={24} lg={12}>
            <Card title={t('backtest:equity.title')} size="small">
              <BacktestCurveChart
                points={detail.equity_curve}
                loading={false}
                errorCode={null}
                buildOption={buildEquityCurveOption}
                emptyKey="backtest:equity.noData"
              />
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card title={t('backtest:drawdown.title')} size="small">
              <BacktestCurveChart
                points={detail.equity_curve}
                loading={false}
                errorCode={null}
                buildOption={buildDrawdownOption}
                emptyKey="backtest:drawdown.noData"
              />
            </Card>
          </Col>
          <Col span={24}>
            <Card title={t('backtest:trades.title')} size="small">
              {detail.trades.length > 0 ? (
                <TradesTable trades={detail.trades} symbolByAsset={symbolByAsset} />
              ) : (
                <Empty description={t('backtest:trades.empty')} />
              )}
            </Card>
          </Col>
        </Row>
      )}

      {phase === 'idle' && !detail && <Empty description={t('backtest:page.empty')} />}

      <Card title={t('backtest:history.title')} size="small" style={{ marginTop: 16 }}>
        {history.length > 0 ? (
          <Table<BacktestRunRead>
            rowKey="id"
            columns={historyColumns}
            dataSource={history}
            size="small"
            pagination={{ pageSize: 5, showSizeChanger: false }}
            onRow={(record) => ({ onClick: () => void handleOpenHistory(record.id) })}
          />
        ) : (
          <Empty description={t('backtest:history.empty')} />
        )}
      </Card>
    </div>
  );
}

export default BacktestPage;
