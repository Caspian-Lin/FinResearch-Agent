/**
 * Factor research page (FRA-58) — configure → trigger → poll → visualize.
 *
 * One config form (universe via watchlist + factor + window) feeds three
 * research actions on tabs:
 *  - IC (sync `GET /factors/{name}/ic`): per-period IC bars + summary cards.
 *  - Quantile (async `POST /quantile-backtest-async` → poll `GET /factors/jobs/{id}`):
 *    N bucket equity curves + top−bottom spread + monotonicity.
 *  - Sensitivity (async `POST /sensitivity-async` → poll): window × cost heatmap
 *    of net Sharpe + best/worst markers.
 *
 * The async actions reuse the BacktestPage poll pattern (FRA-38): a setTimeout
 * chain polls until terminal (success/failed) or the ~3-min cap; IC is an instant
 * GET. Errors map to `t('errors:<code>')`; the failed job's own `error_message`
 * is shown verbatim (a short backend message). This page only *displays*; the
 * worker does all computation (FRA-57).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, Card, Col, Empty, Row, Spin, Statistic, Tabs, Typography, message } from 'antd';

import { enqueueFactorSensitivity, enqueueQuantileBacktest, getFactorIC, getFactorJob } from '@/api/factors';
import { ApiError } from '@/api/client';
import { useWatchlists } from '@/hooks/useWatchlists';
import { FactorChart } from '@/components/factor/FactorChart';
import { FactorConfigForm } from '@/components/factor/FactorConfigForm';
import { factorTypeOf, type FactorFormValues } from '@/components/factor/factorMeta';
import { ICSummaryCards } from '@/components/factor/ICSummaryCards';
import { buildHeatmapOption } from '@/components/factor/heatmapOption';
import { buildICOption } from '@/components/factor/icChartOption';
import { buildQuantileOption } from '@/components/factor/quantileChartOption';
import { SiderLayout } from '@/components/layout/SiderLayout';
import type { ICResult, QuantileResult, SensitivitySummary } from '@/types/api';

const { Title, Text } = Typography;

/** Milliseconds between polls (async quantile / sensitivity jobs). */
const POLL_INTERVAL_MS = 1500;
/** Hard ceiling on poll count (~3 min) before we stop auto-refreshing. */
const MAX_POLLS = 120;
/** Forward-return horizon (days) for the IC evaluation. */
const HORIZON = 5;

type Tab = 'ic' | 'quantile' | 'sensitivity';
type Phase = 'idle' | 'polling' | 'success' | 'failed' | 'timeout';

function FactorResearchPage() {
  const { t } = useTranslation();
  const [messageApi, messageContext] = message.useMessage();
  const { watchlists } = useWatchlists();

  const [activeTab, setActiveTab] = useState<Tab>('ic');
  const [submitting, setSubmitting] = useState(false);

  // IC (sync GET).
  const [icLoading, setIcLoading] = useState(false);
  const [icResult, setIcResult] = useState<ICResult | null>(null);
  const [icError, setIcError] = useState<string | null>(null);

  // Quantile (async job).
  const [qPhase, setQPhase] = useState<Phase>('idle');
  const [qResult, setQResult] = useState<QuantileResult | null>(null);
  const [qError, setQError] = useState<string | null>(null);

  // Sensitivity (async job).
  const [sPhase, setSPhase] = useState<Phase>('idle');
  const [sResult, setSResult] = useState<SensitivitySummary | null>(null);
  const [sError, setSError] = useState<string | null>(null);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);
  useEffect(() => clearTimer, [clearTimer]);

  // --- IC: synchronous GET ----------------------------------------------
  const runIC = useCallback(
    async (v: FactorFormValues) => {
      setIcLoading(true);
      setIcError(null);
      setIcResult(null);
      try {
        const res = await getFactorIC(v.factor, {
          universe: v.universe,
          source: v.source,
          start: v.start,
          end: v.end,
          horizon: HORIZON,
          price_field: v.priceField,
        });
        setIcResult(res.result);
      } catch (err) {
        if (err instanceof ApiError) setIcError(err.code);
      } finally {
        setIcLoading(false);
        setSubmitting(false);
      }
    },
    [],
  );

  // --- async job poller (quantile / sensitivity share one timer) --------
  const startPolling = useCallback(
    (jobId: string, kind: 'quantile' | 'sweep') => {
      let polls = 0;
      const setPhase = kind === 'quantile' ? setQPhase : setSPhase;
      const scheduleNext = () => {
        if (timerRef.current !== null) return; // already stopped
        timerRef.current = setTimeout(() => {
          timerRef.current = null;
          doPoll();
        }, POLL_INTERVAL_MS);
      };
      const doPoll = () => {
        polls += 1;
        getFactorJob(jobId)
          .then((job) => {
            if (job.status === 'success') {
              setPhase('success');
              clearTimer();
              messageApi.success(t('factor:run.success'));
              if (kind === 'quantile') {
                setQResult(job.result as unknown as QuantileResult);
              } else {
                setSResult(job.result as unknown as SensitivitySummary);
              }
            } else if (job.status === 'failed') {
              setPhase('failed');
              clearTimer();
              messageApi.error(t('factor:run.failed'));
            } else if (polls >= MAX_POLLS) {
              setPhase('timeout');
              clearTimer();
              messageApi.warning(t('factor:run.timeout'));
            } else {
              scheduleNext();
            }
          })
          .catch(() => {
            if (polls >= MAX_POLLS) {
              setPhase('timeout');
              clearTimer();
              messageApi.warning(t('factor:run.timeout'));
            } else {
              scheduleNext();
            }
          });
      };
      doPoll();
    },
    [clearTimer, messageApi, t],
  );

  const runQuantile = useCallback(
    async (v: FactorFormValues) => {
      setQPhase('polling');
      setQResult(null);
      setQError(null);
      try {
        const enq = await enqueueQuantileBacktest({
          name: v.name,
          universe: v.universe,
          source: v.source,
          start: v.start,
          end: v.end,
          price_field: v.priceField,
          factor_name: v.factor,
          n_quantiles: v.nQuantiles,
        });
        messageApi.info(t('factor:run.triggered'));
        startPolling(enq.run_id, 'quantile');
      } catch (err) {
        if (err instanceof ApiError) setQError(err.code);
        setQPhase('idle');
      } finally {
        setSubmitting(false);
      }
    },
    [startPolling, messageApi, t],
  );

  const runSensitivity = useCallback(
    async (v: FactorFormValues) => {
      const ftype = factorTypeOf(v.factor);
      if (ftype === null) {
        messageApi.warning(t('factor:sweepUnsupported'));
        setSubmitting(false);
        return;
      }
      setSPhase('polling');
      setSResult(null);
      setSError(null);
      try {
        const enq = await enqueueFactorSensitivity({
          name: v.name,
          universe: v.universe,
          source: v.source,
          start: v.start,
          end: v.end,
          price_field: v.priceField,
          factors: [ftype],
          top_ks: [1, 3],
          rebalances: ['daily'],
          cost_bands: [0, 5, 10, 25],
        });
        messageApi.info(t('factor:run.triggered'));
        startPolling(enq.run_id, 'sweep');
      } catch (err) {
        if (err instanceof ApiError) setSError(err.code);
        setSPhase('idle');
      } finally {
        setSubmitting(false);
      }
    },
    [startPolling, messageApi, t],
  );

  const handleSubmit = useCallback(
    (v: FactorFormValues) => {
      if (v.universe.length === 0) {
        messageApi.error(t('errors:validation'));
        return;
      }
      setSubmitting(true);
      if (activeTab === 'ic') void runIC(v);
      else if (activeTab === 'quantile') void runQuantile(v);
      else void runSensitivity(v);
    },
    [activeTab, runIC, runQuantile, runSensitivity, messageApi, t],
  );

  return (
    <SiderLayout
      sidebar={
        <Card size="small" className="panel" title={t('factor:page.title')}>
          <Text type="secondary">{t('factor:page.description')}</Text>
        </Card>
      }
    >
      <div className="page">
        {messageContext}
        <div className="page-header">
          <div>
            <Title level={2} className="page-title">
              {t('factor:page.title')}
            </Title>
            <Text type="secondary" className="page-description">
              {t('factor:page.description')}
            </Text>
          </div>
        </div>

        <Card id="factor-config" title={t('factor:form.run')} size="small" className="panel">
          <FactorConfigForm
            watchlists={watchlists}
            submitting={submitting}
            onSubmit={handleSubmit}
          />
        </Card>

        <Tabs
          activeKey={activeTab}
          onChange={(k) => setActiveTab(k as Tab)}
          items={[
            {
              key: 'ic',
              label: t('factor:tabs.ic'),
              children: (
                <Row gutter={[16, 16]}>
                  {icError && (
                    <Col span={24}>
                      <Alert type="error" showIcon message={t(`errors:${icError}`)} />
                    </Col>
                  )}
                  {icLoading && (
                    <Col span={24}>
                      <div className="loading-block">
                        <Spin tip={t('common:actions.loading')}>
                          <div style={{ height: 48 }} />
                        </Spin>
                      </div>
                    </Col>
                  )}
                  {icResult && !icLoading && (
                    <>
                      <Col span={24}>
                        <ICSummaryCards summary={icResult.summary} />
                      </Col>
                      <Col span={24}>
                        <Card title={t('factor:ic.title')} size="small" className="panel">
                          <FactorChart
                            data={icResult.series}
                            loading={false}
                            errorCode={null}
                            isEmpty={icResult.series.length === 0}
                            buildOption={buildICOption}
                            emptyKey="factor:ic.noData"
                          />
                        </Card>
                      </Col>
                    </>
                  )}
                  {!icResult && !icLoading && !icError && (
                    <Col span={24}>
                      <Empty description={t('factor:page.empty')} />
                    </Col>
                  )}
                </Row>
              ),
            },
            {
              key: 'quantile',
              label: t('factor:tabs.quantile'),
              children: (
                <Row gutter={[16, 16]}>
                  {qError && (
                    <Col span={24}>
                      <Alert type="error" showIcon message={t(`errors:${qError}`)} />
                    </Col>
                  )}
                  {qPhase === 'timeout' && (
                    <Col span={24}>
                      <Alert type="warning" showIcon message={t('factor:run.timeout')} />
                    </Col>
                  )}
                  {qPhase === 'polling' && (
                    <Col span={24}>
                      <div className="loading-block">
                        <Spin tip={t('factor:run.polling')}>
                          <div style={{ height: 48 }} />
                        </Spin>
                      </div>
                    </Col>
                  )}
                  {qResult && qPhase === 'success' && (
                    <>
                      <Col xs={24} md={8}>
                        <Card size="small" className="panel">
                          <Statistic
                            title={t('factor:quantile.monotonicity')}
                            value={qResult.monotonicity}
                            precision={3}
                          />
                        </Card>
                      </Col>
                      <Col span={24}>
                        <Card title={t('factor:quantile.title')} size="small" className="panel">
                          <FactorChart
                            data={qResult}
                            loading={false}
                            errorCode={null}
                            isEmpty={Object.keys(qResult.quantile_equity).length === 0}
                            buildOption={buildQuantileOption}
                            emptyKey="factor:quantile.noData"
                          />
                        </Card>
                      </Col>
                    </>
                  )}
                  {!qResult && qPhase === 'idle' && !qError && (
                    <Col span={24}>
                      <Empty description={t('factor:page.empty')} />
                    </Col>
                  )}
                </Row>
              ),
            },
            {
              key: 'sensitivity',
              label: t('factor:tabs.sensitivity'),
              children: (
                <Row gutter={[16, 16]}>
                  {sError && (
                    <Col span={24}>
                      <Alert type="error" showIcon message={t(`errors:${sError}`)} />
                    </Col>
                  )}
                  {sPhase === 'timeout' && (
                    <Col span={24}>
                      <Alert type="warning" showIcon message={t('factor:run.timeout')} />
                    </Col>
                  )}
                  {sPhase === 'polling' && (
                    <Col span={24}>
                      <div className="loading-block">
                        <Spin tip={t('factor:run.polling')}>
                          <div style={{ height: 48 }} />
                        </Spin>
                      </div>
                    </Col>
                  )}
                  {sResult && sPhase === 'success' && (
                    <>
                      <Col xs={12} md={6}>
                        <Card size="small" className="panel">
                          <Statistic
                            title={t('factor:heatmap.metric.net_sharpe') + ' (best)'}
                            value={sResult.best_net_sharpe ?? 0}
                            precision={3}
                          />
                        </Card>
                      </Col>
                      <Col xs={12} md={6}>
                        <Card size="small" className="panel">
                          <Statistic
                            title={t('factor:heatmap.metric.net_sharpe') + ' (worst)'}
                            value={sResult.worst_net_sharpe ?? 0}
                            precision={3}
                          />
                        </Card>
                      </Col>
                      <Col span={24}>
                        <Card title={t('factor:heatmap.title')} size="small" className="panel">
                          <FactorChart
                            data={sResult.metric_table}
                            loading={false}
                            errorCode={null}
                            isEmpty={sResult.metric_table.length === 0}
                            buildOption={(d, tt, th) => buildHeatmapOption(d, tt, th, 'net_sharpe')}
                            emptyKey="factor:heatmap.noData"
                          />
                        </Card>
                      </Col>
                    </>
                  )}
                  {!sResult && sPhase === 'idle' && !sError && (
                    <Col span={24}>
                      <Empty description={t('factor:page.empty')} />
                    </Col>
                  )}
                </Row>
              ),
            },
          ]}
        />
      </div>
    </SiderLayout>
  );
}

export default FactorResearchPage;
