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
import { Alert, Card, Col, Empty, Row, Spin, Typography, message } from 'antd';

import { createBacktest, getBacktest, listBacktests } from '@/api/backtest';
import { ApiError } from '@/api/client';
import { fetchQuality } from '@/api/quality';
import { useWatchlists } from '@/hooks/useWatchlists';
import { BacktestConfigForm } from '@/components/backtest/BacktestConfigForm';
import { BacktestCurveChart } from '@/components/backtest/BacktestCurveChart';
import { BacktestHistorySidebar } from '@/components/backtest/BacktestHistorySidebar';
import { MetricsCards } from '@/components/backtest/MetricsCards';
import { PreflightSyncModal, type MissingAsset } from '@/components/backtest/PreflightSyncModal';
import { TradesTable } from '@/components/backtest/TradesTable';
import {
  buildDrawdownOption,
  buildEquityCurveOption,
} from '@/components/backtest/equityChartOption';
import { SiderLayout } from '@/components/layout/SiderLayout';
import type { BacktestCreateRequest, BacktestDetailRead, BacktestRunRead } from '@/types/api';

const { Title, Text } = Typography;

/** Milliseconds between polls. */
const POLL_INTERVAL_MS = 1500;
/** Hard ceiling on poll count (~3 min) before we stop auto-refreshing. */
const MAX_POLLS = 120;
/** Coverage below which the preflight flags an asset as needing sync (FRA-43). */
const COVERAGE_THRESHOLD = 0.9;
/** Data source for both the preflight quality check and the backtest. */
const SOURCE = 'yfinance';

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
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [preflightMissing, setPreflightMissing] = useState<MissingAsset[]>([]);
  const [preflightWindow, setPreflightWindow] = useState({ source: SOURCE, start: '', end: '' });

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
            setSelectedRunId(d.run.id);
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
        // FRA-43 preflight: verify universe + benchmark coverage before running.
        // Any asset below the threshold (incl. no data) opens the sync modal
        // instead of backtesting; the user re-runs after sync completes.
        const checkIds = [...req.universe];
        if (req.benchmark_asset_id) checkIds.push(req.benchmark_asset_id);
        const missing: MissingAsset[] = [];
        await Promise.all(
          checkIds.map(async (id) => {
            const symbol = symbols[id] ?? id.slice(0, 8);
            try {
              const q = await fetchQuality({
                asset_id: id,
                source: SOURCE,
                start: req.start,
                end: req.end,
              });
              if (q.coverage < COVERAGE_THRESHOLD) {
                missing.push({ assetId: id, symbol, coverage: q.coverage });
              }
            } catch {
              // quality unavailable (404/422) → treat as no data.
              missing.push({ assetId: id, symbol, coverage: 0 });
            }
          }),
        );
        if (missing.length > 0) {
          setPreflightMissing(missing);
          setPreflightWindow({ source: SOURCE, start: req.start, end: req.end });
          return;
        }
        // data complete → enqueue backtest + poll.
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
        setSelectedRunId(d.run.id);
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

  return (
    <SiderLayout
      sidebar={
        <BacktestHistorySidebar
          history={history}
          loading={false}
          selectedRunId={selectedRunId}
          onOpenRun={(id) => void handleOpenHistory(id)}
          onNewRun={() =>
            document.getElementById('backtest-config')?.scrollIntoView({ behavior: 'smooth' })
          }
        />
      }
    >
      <div className="page">
        {messageContext}
        <div className="page-header">
          <div>
            <Title level={2} className="page-title">
              {t('backtest:page.title')}
            </Title>
            <Text type="secondary" className="page-description">
              {t('backtest:page.description')}
            </Text>
          </div>
        </div>

        <Card id="backtest-config" title={t('backtest:form.title')} size="small" className="panel">
          <BacktestConfigForm
            watchlists={watchlists}
            submitting={submitting}
            onSubmit={(req, symbols) => void handleRun(req, symbols)}
          />
        </Card>

        {phase === 'polling' && (
          <div className="loading-block">
            <Spin tip={t('backtest:run.polling')}>
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
          <Row gutter={[16, 16]}>
            <Col span={24}>
              <MetricsCards metrics={detail.metrics} />
            </Col>
            <Col xs={24} lg={12}>
              <Card title={t('backtest:equity.title')} size="small" className="panel">
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
              <Card title={t('backtest:drawdown.title')} size="small" className="panel">
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
              <Card title={t('backtest:trades.title')} size="small" className="panel">
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

        <PreflightSyncModal
          open={preflightMissing.length > 0}
          missing={preflightMissing}
          source={preflightWindow.source}
          start={preflightWindow.start}
          end={preflightWindow.end}
          onCancel={() => setPreflightMissing([])}
        />
      </div>
    </SiderLayout>
  );
}

export default BacktestPage;
