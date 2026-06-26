/**
 * Factor research page (FRA-58) — configure → trigger → poll → visualize.
 *
 * One config form (universe via watchlist + factor + window) feeds three
 * research actions on tabs:
 *  - IC (sync `GET /factors/{name}/ic`): per-period IC bars + summary cards.
 *  - Ranking (sync `GET /factors/{name}/snapshot`): raw values + rank/z-score/bucket.
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
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  Card,
  Col,
  DatePicker,
  Empty,
  Row,
  Space,
  Spin,
  Statistic,
  Table,
  Tabs,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';

import {
  enqueueFactorSensitivity,
  enqueueQuantileBacktest,
  getFactorIC,
  getFactorJob,
  getFactorRankingSnapshot,
} from '@/api/factors';
import { ApiError } from '@/api/client';
import { fetchQuality } from '@/api/quality';
import { useWatchlists } from '@/hooks/useWatchlists';
import { PreflightSyncModal, type MissingAsset } from '@/components/backtest/PreflightSyncModal';
import { FactorChart } from '@/components/factor/FactorChart';
import { FactorConfigForm } from '@/components/factor/FactorConfigForm';
import { factorTypeOf, type FactorFormValues } from '@/components/factor/factorMeta';
import { ICSummaryCards } from '@/components/factor/ICSummaryCards';
import { buildHeatmapOption } from '@/components/factor/heatmapOption';
import { buildICOption } from '@/components/factor/icChartOption';
import { buildQuantileOption } from '@/components/factor/quantileChartOption';
import { SiderLayout } from '@/components/layout/SiderLayout';
import type {
  FactorRankingSnapshotItem,
  FactorRankingSnapshotResponse,
  ICResult,
  QuantileResult,
  SensitivitySummary,
} from '@/types/api';

const { Title, Text } = Typography;

/** Milliseconds between polls (async quantile / sensitivity jobs). */
const POLL_INTERVAL_MS = 1500;
/** Hard ceiling on poll count (~3 min) before we stop auto-refreshing. */
const MAX_POLLS = 120;
/** Forward-return horizon (days) for the IC evaluation. */
const HORIZON = 5;
/** Coverage below which the preflight flags an asset as needing sync (FRA-43). */
const COVERAGE_THRESHOLD = 0.9;

type Tab = 'ic' | 'ranking' | 'quantile' | 'sensitivity';
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

  // Ranking snapshot (sync GET).
  const [rankingLoading, setRankingLoading] = useState(false);
  const [rankingResult, setRankingResult] = useState<FactorRankingSnapshotResponse | null>(null);
  const [rankingError, setRankingError] = useState<string | null>(null);
  const [rankingDate, setRankingDate] = useState<string | null>(null);

  // Quantile (async job).
  const [qPhase, setQPhase] = useState<Phase>('idle');
  const [qResult, setQResult] = useState<QuantileResult | null>(null);
  const [qError, setQError] = useState<string | null>(null);

  // Sensitivity (async job).
  const [sPhase, setSPhase] = useState<Phase>('idle');
  const [sResult, setSResult] = useState<SensitivitySummary | null>(null);
  const [sError, setSError] = useState<string | null>(null);

  // FRA-43 preflight: assets flagged as needing sync before compute runs.
  const [preflightMissing, setPreflightMissing] = useState<MissingAsset[]>([]);
  const [preflightWindow, setPreflightWindow] = useState({ source: '', start: '', end: '' });
  // universe arrives as asset UUIDs; the sync modal shows symbols, so map them.
  const symbolByAsset = useMemo(() => {
    const m: Record<string, string> = {};
    for (const wl of watchlists) {
      for (const it of wl.items) m[it.asset_id] = it.symbol;
    }
    return m;
  }, [watchlists]);

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
        // Surface the backend's specific reason (e.g. "insufficient price data:
        // … field='adjusted'") instead of the generic "validation" label. A 422
        // here is almost always a data/shape issue the user can act on (sync
        // data, switch price field, widen the window) — not a malformed field.
        if (err instanceof ApiError) setIcError(err.detail || t('errors:validation'));
      } finally {
        setIcLoading(false);
        setSubmitting(false);
      }
    },
    [t],
  );

  // --- async job poller (quantile / sensitivity share one timer) --------
  const startPolling = useCallback(
    (jobId: string, kind: 'quantile' | 'sweep') => {
      let polls = 0;
      const setPhase = kind === 'quantile' ? setQPhase : setSPhase;
      const setError = kind === 'quantile' ? setQError : setSError;
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
              // Show the worker's specific failure reason (e.g. insufficient
              // price data) rather than just "run failed".
              setError(job.error_message || t('factor:run.failed'));
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
        if (err instanceof ApiError) setQError(err.detail || t('errors:validation'));
        setQPhase('idle');
      } finally {
        setSubmitting(false);
      }
    },
    [startPolling, messageApi, t],
  );

  const runRankingSnapshot = useCallback(
    async (v: FactorFormValues) => {
      setRankingLoading(true);
      setRankingError(null);
      setRankingResult(null);
      try {
        const res = await getFactorRankingSnapshot(v.factor, {
          universe: v.universe,
          source: v.source,
          start: v.start,
          end: v.end,
          snapshot_date: rankingDate ?? undefined,
          n_quantiles: Math.min(v.nQuantiles, v.universe.length),
          price_field: v.priceField,
        });
        setRankingResult(res);
      } catch (err) {
        if (err instanceof ApiError) setRankingError(err.detail || t('errors:validation'));
      } finally {
        setRankingLoading(false);
        setSubmitting(false);
      }
    },
    [rankingDate, t],
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
        if (err instanceof ApiError) setSError(err.detail || t('errors:validation'));
        setSPhase('idle');
      } finally {
        setSubmitting(false);
      }
    },
    [startPolling, messageApi, t],
  );

  const handleSubmit = useCallback(
    async (v: FactorFormValues) => {
      if (v.universe.length === 0) {
        messageApi.error(t('errors:validation'));
        return;
      }
      // IC is a cross-sectional rank correlation and needs ≥ 2 assets (the
      // backend uses Query(min_length=2)). Fail fast with a clear message
      // instead of letting the API reject it as a generic 422.
      if (activeTab === 'ic' && v.universe.length < 2) {
        messageApi.error(t('factor:ic.minUniverse'));
        return;
      }
      if (activeTab === 'ranking' && v.universe.length < 2) {
        messageApi.error(t('factor:ranking.minUniverse'));
        return;
      }
      setSubmitting(true);
      try {
        // FRA-43 preflight: verify universe coverage before computing. Any asset
        // below the threshold (incl. no data at all) opens the sync modal rather
        // than hitting the API — otherwise load_prices raises and the 422 surfaces
        // as the misleading "Some fields are invalid".
        const missing: MissingAsset[] = [];
        await Promise.all(
          v.universe.map(async (id) => {
            const symbol = symbolByAsset[id] ?? id.slice(0, 8);
            try {
              const q = await fetchQuality({
                asset_id: id,
                source: v.source,
                start: v.start,
                end: v.end,
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
          setPreflightWindow({ source: v.source, start: v.start, end: v.end });
          return;
        }
        if (activeTab === 'ic') void runIC(v);
        else if (activeTab === 'ranking') void runRankingSnapshot(v);
        else if (activeTab === 'quantile') void runQuantile(v);
        else void runSensitivity(v);
      } catch (err) {
        if (err instanceof ApiError) messageApi.error(t(`errors:${err.code}`));
      } finally {
        setSubmitting(false);
      }
    },
    [
      activeTab,
      runIC,
      runRankingSnapshot,
      runQuantile,
      runSensitivity,
      messageApi,
      t,
      symbolByAsset,
    ],
  );

  const rankingColumns: ColumnsType<FactorRankingSnapshotItem> = useMemo(
    () => [
      {
        title: t('factor:ranking.columns.symbol'),
        dataIndex: 'symbol',
        key: 'symbol',
        sorter: (a, b) => a.symbol.localeCompare(b.symbol),
      },
      {
        title: t('factor:ranking.columns.value'),
        dataIndex: 'factor_value',
        key: 'factor_value',
        align: 'right',
        sorter: (a, b) => a.factor_value - b.factor_value,
        render: (v: number) => v.toFixed(4),
      },
      {
        title: t('factor:ranking.columns.rank'),
        dataIndex: 'rank_pct',
        key: 'rank_pct',
        align: 'right',
        defaultSortOrder: 'descend',
        sorter: (a, b) => a.rank_pct - b.rank_pct,
        render: (v: number) => `${(v * 100).toFixed(1)}%`,
      },
      {
        title: t('factor:ranking.columns.zScore'),
        dataIndex: 'z_score',
        key: 'z_score',
        align: 'right',
        sorter: (a, b) => (a.z_score ?? 0) - (b.z_score ?? 0),
        render: (v: number | null) => (v === null ? '—' : v.toFixed(3)),
      },
      {
        title: t('factor:ranking.columns.bucket'),
        dataIndex: 'quantile_bucket',
        key: 'quantile_bucket',
        align: 'right',
        sorter: (a, b) => a.quantile_bucket - b.quantile_bucket,
      },
    ],
    [t],
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
            onSubmit={(v) => void handleSubmit(v)}
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
                      <Alert type="error" showIcon message={icError} />
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
              key: 'ranking',
              label: t('factor:tabs.ranking'),
              children: (
                <Row gutter={[16, 16]}>
                  <Col span={24}>
                    <Card
                      title={t('factor:ranking.title')}
                      size="small"
                      className="panel"
                      extra={
                        <Space>
                          <Text type="secondary">{t('factor:ranking.snapshotDate')}</Text>
                          <DatePicker
                            allowClear
                            value={rankingDate ? dayjs(rankingDate) : null}
                            onChange={(d) => setRankingDate(d ? d.format('YYYY-MM-DD') : null)}
                            placeholder={t('factor:ranking.latestValid')}
                          />
                        </Space>
                      }
                    >
                      {rankingError && (
                        <Alert
                          type="error"
                          showIcon
                          message={rankingError}
                          style={{ marginBottom: 16 }}
                        />
                      )}
                      {rankingResult?.snapshot_time && (
                        <Text type="secondary">
                          {t('factor:ranking.snapshotTime', {
                            date: rankingResult.snapshot_time.slice(0, 10),
                          })}
                        </Text>
                      )}
                      <Table<FactorRankingSnapshotItem>
                        rowKey="asset_id"
                        columns={rankingColumns}
                        dataSource={rankingResult?.items ?? []}
                        loading={rankingLoading}
                        pagination={false}
                        size="small"
                        locale={{
                          emptyText:
                            rankingResult || rankingError
                              ? t('factor:ranking.noData')
                              : t('factor:page.empty'),
                        }}
                      />
                    </Card>
                  </Col>
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
                      <Alert type="error" showIcon message={qError} />
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
                      <Alert type="error" showIcon message={sError} />
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

        <PreflightSyncModal
          open={preflightMissing.length > 0}
          missing={preflightMissing}
          source={preflightWindow.source}
          start={preflightWindow.start}
          end={preflightWindow.end}
          ns="factor"
          onCancel={() => setPreflightMissing([])}
        />
      </div>
    </SiderLayout>
  );
}

export default FactorResearchPage;
