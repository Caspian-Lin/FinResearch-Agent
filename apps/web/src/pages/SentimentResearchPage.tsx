/**
 * Sentiment research page (FRA-72) — configure → trigger → poll → visualize.
 *
 * One shared config form (universe via watchlist + date range + model name +
 * provider + classifier) feeds four research tabs:
 *  - News (sync `POST /sentiment/news/sync`): fetch news via provider + view table.
 *  - Scores (sync `POST /sentiment/score`): batch classify news + view scores table.
 *  - Factor (sync `GET /sentiment/factor`): daily mean-score time series chart.
 *  - Comparison (async `POST /backtest/comparison` → poll `GET /backtest/comparison/{id}`):
 *    technical-only vs technical+sentiment metrics + equity curves side-by-side.
 *
 * The async comparison action reuses the BacktestPage poll pattern (FRA-38):
 * a setTimeout chain polls until terminal (success/failed) or the ~3-min cap.
 * Errors map to `t('errors:<code>')`; the failed job's own `error_message` is
 * shown verbatim. This page only *displays*; the worker does all computation.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Empty,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { Dayjs } from 'dayjs';
import dayjs from 'dayjs';

import {
  classifyNews,
  computeSentimentFactor,
  createComparison,
  getComparison,
  getSentimentFactor,
  getSentimentJob,
  listNews,
  listSentimentScores,
  syncNews,
} from '@/api/sentiment';
import { ApiError } from '@/api/client';
import { ToggleSelect } from '@/components/ui/ToggleSelect';
import { FactorChart } from '@/components/factor/FactorChart';
import { SiderLayout } from '@/components/layout/SiderLayout';
import { buildSentimentFactorOption } from '@/components/sentiment/sentimentFactorOption';
import { useWatchlists } from '@/hooks/useWatchlists';
import type {
  BacktestPriceField,
  ComparisonCreateRequest,
  ComparisonDetailRead,
  ComparisonMode,
  ComparisonTechnicalFactor,
  NewsItemRead,
  RebalanceFreq,
  SentimentFactorResponse,
  SentimentScoreRead,
} from '@/types/api';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

const POLL_INTERVAL_MS = 1500;
const MAX_POLLS = 120;

/** Shared config values emitted by the form (start/end as YYYY-MM-DD). */
interface SentimentFormValues {
  name: string;
  universe: string[];
  start: string;
  end: string;
  modelName: string;
  provider: string;
  classifier: string;
}

/** Raw form values (range as Dayjs tuple). */
interface RawFormValues {
  name: string;
  watchlistId: string;
  range: [Dayjs, Dayjs];
  modelName: string;
  provider: string;
  classifier: string;
}

type Tab = 'news' | 'scores' | 'factor' | 'comparison';
type Phase = 'idle' | 'polling' | 'success' | 'failed' | 'timeout';

/** Reusable status tag color for sentiment labels. */
function labelColor(label: string): string {
  if (label === 'positive') return 'green';
  if (label === 'negative') return 'red';
  return 'default';
}

function SentimentResearchPage() {
  const { t } = useTranslation();
  const [messageApi, messageContext] = message.useMessage();
  const { watchlists } = useWatchlists();

  const [activeTab, setActiveTab] = useState<Tab>('news');
  const [formValues, setFormValues] = useState<SentimentFormValues | null>(null);

  // News tab state.
  const [newsItems, setNewsItems] = useState<NewsItemRead[]>([]);
  const [newsLoading, setNewsLoading] = useState(false);
  const [newsSynced, setNewsSynced] = useState(false);

  // Scores tab state.
  const [scoreItems, setScoreItems] = useState<SentimentScoreRead[]>([]);
  const [scoresLoading, setScoresLoading] = useState(false);
  const [scoresClassified, setScoresClassified] = useState(false);

  // Factor tab state.
  const [factorLoading, setFactorLoading] = useState(false);
  const [factorResult, setFactorResult] = useState<SentimentFactorResponse | null>(null);
  const [factorError, setFactorError] = useState<string | null>(null);

  // Comparison tab state.
  const [cmpPhase, setCmpPhase] = useState<Phase>('idle');
  const [cmpResult, setCmpResult] = useState<ComparisonDetailRead | null>(null);
  const [cmpError, setCmpError] = useState<string | null>(null);

  // Comparison strategy params (form-local).
  const [cmpParams, setCmpParams] = useState({
    technicalFactor: 'momentum' as ComparisonTechnicalFactor,
    window: 63,
    topK: 3,
    mode: 'overlay' as ComparisonMode,
    sentimentThreshold: 0.0,
    sentimentWeight: 0.5,
    includeSentimentOnly: false,
  });
  const [cmpAdvanced, setCmpAdvanced] = useState({
    initialCapital: 100_000,
    costBps: 0,
    rebalance: 'daily' as RebalanceFreq,
    priceField: 'adjusted' as BacktestPriceField,
  });

  // Asset-id → symbol map (for scores/comparison display).
  const symbolByAsset = useMemo(() => {
    const m: Record<string, string> = {};
    for (const wl of watchlists) {
      for (const it of wl.items) m[it.asset_id] = it.symbol;
    }
    return m;
  }, [watchlists]);

  // --- timer for async comparison polling --------------------------------
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);
  useEffect(() => clearTimer, [clearTimer]);

  // --- form submit handler -----------------------------------------------
  const handleFormSubmit = (raw: RawFormValues) => {
    const wl = watchlists.find((w) => w.watchlist_id === raw.watchlistId);
    const universe = wl ? wl.items.map((it) => it.asset_id) : [];
    if (universe.length === 0) {
      messageApi.error(t('errors:validation'));
      return;
    }
    const values: SentimentFormValues = {
      name: raw.name,
      universe,
      start: raw.range[0].format('YYYY-MM-DD'),
      end: raw.range[1].format('YYYY-MM-DD'),
      modelName: raw.modelName,
      provider: raw.provider,
      classifier: raw.classifier,
    };
    setFormValues(values);
  };

  // --- news: sync + list -------------------------------------------------
  const handleSyncNews = async () => {
    if (!formValues) return;
    setNewsLoading(true);
    try {
      const res = await syncNews({
        name: formValues.name,
        universe: formValues.universe,
        start: formValues.start,
        end: formValues.end,
        provider: formValues.provider || undefined,
      });
      messageApi.success(
        t('sentiment:news.result', {
          fetched: res.fetched,
          inserted: res.inserted,
          updated: res.updated,
          status: res.status,
        }),
      );
      setNewsSynced(true);
      // Auto-refresh the news list.
      const list = await listNews({
        start: formValues.start,
        end: formValues.end,
        limit: 1000,
      });
      setNewsItems(list.items);
    } catch (err) {
      if (err instanceof ApiError) messageApi.error(err.detail || t(`errors:${err.code}`));
    } finally {
      setNewsLoading(false);
    }
  };

  const handleListNews = async () => {
    if (!formValues) return;
    setNewsLoading(true);
    try {
      const list = await listNews({
        start: formValues.start,
        end: formValues.end,
        limit: 1000,
      });
      setNewsItems(list.items);
    } catch (err) {
      if (err instanceof ApiError) messageApi.error(err.detail || t(`errors:${err.code}`));
    } finally {
      setNewsLoading(false);
    }
  };

  // --- scores: classify + list -------------------------------------------
  const handleClassify = async () => {
    if (!formValues) return;
    setScoresLoading(true);
    try {
      const res = await classifyNews({
        name: formValues.name,
        universe: formValues.universe,
        start: formValues.start,
        end: formValues.end,
        classifier: formValues.classifier || undefined,
      });
      messageApi.success(
        t('sentiment:scores.result', {
          classified: res.classified,
          news: res.news,
          inserted: res.inserted,
          updated: res.updated,
        }),
      );
      setScoresClassified(true);
      // Auto-refresh the scores list.
      const list = await listSentimentScores({
        model_name: formValues.modelName,
        start: formValues.start,
        end: formValues.end,
        limit: 1000,
      });
      setScoreItems(list.items);
    } catch (err) {
      if (err instanceof ApiError) messageApi.error(err.detail || t(`errors:${err.code}`));
    } finally {
      setScoresLoading(false);
    }
  };

  const handleListScores = async () => {
    if (!formValues) return;
    setScoresLoading(true);
    try {
      const list = await listSentimentScores({
        model_name: formValues.modelName,
        start: formValues.start,
        end: formValues.end,
        limit: 1000,
      });
      setScoreItems(list.items);
    } catch (err) {
      if (err instanceof ApiError) messageApi.error(err.detail || t(`errors:${err.code}`));
    } finally {
      setScoresLoading(false);
    }
  };

  // --- factor: compute ---------------------------------------------------
  const handleComputeFactor = async () => {
    if (!formValues) return;
    setFactorLoading(true);
    setFactorError(null);
    setFactorResult(null);
    try {
      // Compute (sync) — persists the factor to factor_values.
      await computeSentimentFactor({
        name: formValues.name,
        universe: formValues.universe,
        start: formValues.start,
        end: formValues.end,
        model_name: formValues.modelName,
      });
      messageApi.success(t('sentiment:run.success'));
      // Then fetch the computed factor for display.
      const res = await getSentimentFactor({
        universe: formValues.universe,
        start: formValues.start,
        end: formValues.end,
        model_name: formValues.modelName,
      });
      setFactorResult(res);
    } catch (err) {
      if (err instanceof ApiError) setFactorError(err.detail || t('errors:validation'));
    } finally {
      setFactorLoading(false);
    }
  };

  // --- comparison: async create + poll -----------------------------------
  const startCmpPolling = useCallback(
    (runId: string) => {
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
        // Poll the comparison endpoint directly (it returns parent + children).
        getComparison(runId)
          .then((detail) => {
            const status = detail.run.status;
            if (status === 'success') {
              setCmpPhase('success');
              clearTimer();
              setCmpResult(detail);
              messageApi.success(t('sentiment:run.success'));
            } else if (status === 'failed') {
              setCmpPhase('failed');
              setCmpError(detail.run.error_message || t('sentiment:run.failed'));
              clearTimer();
              messageApi.error(t('sentiment:run.failed'));
            } else if (polls >= MAX_POLLS) {
              setCmpPhase('timeout');
              clearTimer();
              messageApi.warning(t('sentiment:run.timeout'));
            } else {
              scheduleNext();
            }
          })
          .catch(() => {
            // On transient errors, try to poll the sentiment job endpoint as fallback.
            getSentimentJob(runId)
              .then(() => scheduleNext())
              .catch(() => {
                if (polls >= MAX_POLLS) {
                  setCmpPhase('timeout');
                  clearTimer();
                  messageApi.warning(t('sentiment:run.timeout'));
                } else {
                  scheduleNext();
                }
              });
          });
      };
      doPoll();
    },
    [clearTimer, messageApi, t],
  );

  const handleRunComparison = async () => {
    if (!formValues) return;
    setCmpPhase('polling');
    setCmpResult(null);
    setCmpError(null);
    try {
      const payload: ComparisonCreateRequest = {
        name: formValues.name,
        universe: formValues.universe,
        start: formValues.start,
        end: formValues.end,
        model_name: formValues.modelName,
        initial_capital: cmpAdvanced.initialCapital,
        cost_bps: cmpAdvanced.costBps,
        rebalance: cmpAdvanced.rebalance,
        price_field: cmpAdvanced.priceField,
        strategy_params: {
          technical_factor: cmpParams.technicalFactor,
          window: cmpParams.window,
          top_k: cmpParams.topK,
          mode: cmpParams.mode,
          sentiment_threshold: cmpParams.sentimentThreshold,
          sentiment_weight: cmpParams.sentimentWeight,
        },
        include_sentiment_only: cmpParams.includeSentimentOnly,
      };
      const enq = await createComparison(payload);
      messageApi.info(t('sentiment:run.triggered'));
      startCmpPolling(enq.run_id);
    } catch (err) {
      if (err instanceof ApiError) setCmpError(err.detail || t('errors:validation'));
      setCmpPhase('idle');
    }
  };

  // --- table column definitions -----------------------------------------
  const newsColumns: ColumnsType<NewsItemRead> = useMemo(
    () => [
      {
        title: t('sentiment:news.columns.publishedAt'),
        dataIndex: 'published_at',
        key: 'published_at',
        width: 120,
        render: (v: string) => dayjs(v).format('YYYY-MM-DD'),
        sorter: (a, b) => a.published_at.localeCompare(b.published_at),
      },
      {
        title: t('sentiment:news.columns.source'),
        dataIndex: 'source',
        key: 'source',
        width: 100,
      },
      {
        title: t('sentiment:news.columns.headline'),
        dataIndex: 'headline',
        key: 'headline',
        ellipsis: true,
      },
      {
        title: t('sentiment:news.columns.summary'),
        dataIndex: 'summary',
        key: 'summary',
        ellipsis: true,
        render: (v: string | null) => v ?? '—',
      },
    ],
    [t],
  );

  const scoreColumns: ColumnsType<SentimentScoreRead> = useMemo(
    () => [
      {
        title: t('sentiment:scores.columns.publishedAt'),
        dataIndex: 'published_at',
        key: 'published_at',
        width: 120,
        render: (v: string) => dayjs(v).format('YYYY-MM-DD'),
        sorter: (a, b) => a.published_at.localeCompare(b.published_at),
      },
      {
        title: t('sentiment:scores.columns.asset'),
        dataIndex: 'asset_id',
        key: 'asset_id',
        width: 100,
        render: (id: string) => symbolByAsset[id] ?? id.slice(0, 8),
      },
      {
        title: t('sentiment:scores.columns.headline'),
        dataIndex: 'headline',
        key: 'headline',
        ellipsis: true,
      },
      {
        title: t('sentiment:scores.columns.label'),
        dataIndex: 'label',
        key: 'label',
        width: 90,
        render: (v: string) => (
          <Tag color={labelColor(v)}>
            {t(`sentiment:scores.label.${v}` as const)}
          </Tag>
        ),
        filters: [
          { text: t('sentiment:scores.label.positive'), value: 'positive' },
          { text: t('sentiment:scores.label.negative'), value: 'negative' },
          { text: t('sentiment:scores.label.neutral'), value: 'neutral' },
        ],
        onFilter: (value, record) => record.label === value,
      },
      {
        title: t('sentiment:scores.columns.score'),
        dataIndex: 'score',
        key: 'score',
        width: 80,
        align: 'right' as const,
        sorter: (a, b) => a.score - b.score,
        render: (v: number) => v.toFixed(4),
      },
      {
        title: t('sentiment:scores.columns.confidence'),
        dataIndex: 'confidence',
        key: 'confidence',
        width: 90,
        align: 'right' as const,
        render: (v: number | null) => (v !== null ? v.toFixed(4) : '—'),
      },
    ],
    [t, symbolByAsset],
  );

  const watchlistOptions = watchlists.map((w) => ({
    value: w.watchlist_id,
    label: `${w.name} (${w.items.length})`,
  }));

  // --- comparison metrics table data ------------------------------------
  const comparisonMetricsData = useMemo(() => {
    if (!cmpResult) return [];
    const metricKeys = [
      'annual_return',
      'volatility',
      'sharpe_ratio',
      'max_drawdown',
      'calmar_ratio',
      'turnover',
      'win_rate',
    ];
    return metricKeys.map((key) => {
      const row: Record<string, string | number> = {
        key,
        metric: t(`backtest:metrics.${key}`),
      };
      for (const child of cmpResult.children) {
        if (!child.metrics) {
          row[child.role] = '—';
          continue;
        }
        const field = `net_${key}` as keyof typeof child.metrics;
        const v: unknown = child.metrics[field];
        if (typeof v === 'number' && Number.isFinite(v)) {
          row[child.role] =
            key === 'sharpe_ratio' || key === 'calmar_ratio'
              ? v.toFixed(3)
              : `${(v * 100).toFixed(2)}%`;
        } else {
          row[child.role] = '—';
        }
      }
      return row;
    });
  }, [cmpResult, t]);

  const comparisonMetricsColumns: ColumnsType<Record<string, string | number>> = useMemo(() => {
    if (!cmpResult) return [];
    const roles = cmpResult.children.map((c) => c.role);
    return [
      {
        title: t('sentiment:comparison.metricsTable.metric'),
        dataIndex: 'metric',
        key: 'metric',
        width: 140,
      },
      ...roles.map((role) => ({
        title: t(`sentiment:comparison.role.${role}` as const),
        dataIndex: role,
        key: role,
        align: 'right' as const,
      })),
    ];
  }, [cmpResult, t]);

  return (
    <SiderLayout
      sidebar={
        <Card size="small" className="panel" title={t('sentiment:page.title')}>
          <Text type="secondary">{t('sentiment:page.description')}</Text>
        </Card>
      }
    >
      <div className="page">
        {messageContext}
        <div className="page-header">
          <div>
            <Title level={2} className="page-title">
              {t('sentiment:page.title')}
            </Title>
            <Text type="secondary" className="page-description">
              {t('sentiment:page.description')}
            </Text>
          </div>
        </div>

        {/* --- shared config form --- */}
        <Card title={t('sentiment:page.title')} size="small" className="panel">
          <SentimentConfigForm
            watchlistOptions={watchlistOptions}
            onSubmit={handleFormSubmit}
          />
          <Space style={{ width: '100%', justifyContent: 'flex-end', marginTop: 8 }}>
            <Text type="secondary">{t('sentiment:form.hint')}</Text>
          </Space>
        </Card>

        <Tabs
          activeKey={activeTab}
          onChange={(k) => setActiveTab(k as Tab)}
          items={[
            {
              key: 'news',
              label: t('sentiment:tabs.news'),
              children: (
                <Row gutter={[16, 16]}>
                  <Col span={24}>
                    <Space>
                      <Button
                        type="primary"
                        onClick={() => void handleSyncNews()}
                        loading={newsLoading}
                        disabled={!formValues}
                      >
                        {t('sentiment:news.sync')}
                      </Button>
                      <Button
                        onClick={() => void handleListNews()}
                        disabled={!formValues}
                      >
                        {t('common:actions.refresh')}
                      </Button>
                    </Space>
                  </Col>
                  <Col span={24}>
                    <Card title={t('sentiment:news.title')} size="small" className="panel">
                      <Table<NewsItemRead>
                        rowKey="id"
                        columns={newsColumns}
                        dataSource={newsItems}
                        loading={newsLoading}
                        size="small"
                        pagination={{ pageSize: 10, showSizeChanger: false }}
                        locale={{
                          emptyText: newsSynced
                            ? t('sentiment:news.noData')
                            : t('sentiment:page.empty'),
                        }}
                      />
                    </Card>
                  </Col>
                </Row>
              ),
            },
            {
              key: 'scores',
              label: t('sentiment:tabs.scores'),
              children: (
                <Row gutter={[16, 16]}>
                  <Col span={24}>
                    <Space>
                      <Button
                        type="primary"
                        onClick={() => void handleClassify()}
                        loading={scoresLoading}
                        disabled={!formValues}
                      >
                        {t('sentiment:scores.classify')}
                      </Button>
                      <Button
                        onClick={() => void handleListScores()}
                        disabled={!formValues}
                      >
                        {t('common:actions.refresh')}
                      </Button>
                    </Space>
                  </Col>
                  <Col span={24}>
                    <Card title={t('sentiment:scores.title')} size="small" className="panel">
                      <Table<SentimentScoreRead>
                        rowKey="id"
                        columns={scoreColumns}
                        dataSource={scoreItems}
                        loading={scoresLoading}
                        size="small"
                        pagination={{ pageSize: 10, showSizeChanger: false }}
                        locale={{
                          emptyText: scoresClassified
                            ? t('sentiment:scores.noData')
                            : t('sentiment:page.empty'),
                        }}
                      />
                    </Card>
                  </Col>
                </Row>
              ),
            },
            {
              key: 'factor',
              label: t('sentiment:tabs.factor'),
              children: (
                <Row gutter={[16, 16]}>
                  <Col span={24}>
                    <Space>
                      <Button
                        type="primary"
                        onClick={() => void handleComputeFactor()}
                        loading={factorLoading}
                        disabled={!formValues}
                      >
                        {t('sentiment:factor.compute')}
                      </Button>
                    </Space>
                  </Col>
                  {factorError && (
                    <Col span={24}>
                      <Alert type="error" showIcon message={factorError} />
                    </Col>
                  )}
                  {factorLoading && (
                    <Col span={24}>
                      <div className="loading-block">
                        <Spin tip={t('common:actions.loading')}>
                          <div style={{ height: 48 }} />
                        </Spin>
                      </div>
                    </Col>
                  )}
                  {factorResult && !factorLoading && (
                    <Col span={24}>
                      <Card title={t('sentiment:factor.title')} size="small" className="panel">
                        <FactorChart
                          data={factorResult.items}
                          loading={false}
                          errorCode={null}
                          isEmpty={factorResult.items.length === 0}
                          buildOption={(d, tt, th) =>
                            buildSentimentFactorOption(d, tt, th)
                          }
                          emptyKey="sentiment:factor.noData"
                          height={400}
                        />
                      </Card>
                    </Col>
                  )}
                  {!factorResult && !factorLoading && !factorError && (
                    <Col span={24}>
                      <Empty description={t('sentiment:factor.noData')} />
                    </Col>
                  )}
                </Row>
              ),
            },
            {
              key: 'comparison',
              label: t('sentiment:tabs.comparison'),
              children: (
                <Row gutter={[16, 16]}>
                  {/* --- comparison strategy params form --- */}
                  <Col span={24}>
                    <Card
                      title={t('sentiment:comparison.params')}
                      size="small"
                      className="panel"
                    >
                      <Row gutter={16}>
                        <Col xs={24} md={6}>
                          <label>{t('sentiment:comparison.technicalFactor')}</label>
                          <Select<ComparisonTechnicalFactor>
                            value={cmpParams.technicalFactor}
                            onChange={(v) =>
                              setCmpParams((p) => ({ ...p, technicalFactor: v }))
                            }
                            style={{ width: '100%', marginTop: 4 }}
                            options={[
                              { value: 'momentum', label: 'Momentum' },
                              { value: 'reversal', label: 'Reversal' },
                              { value: 'rsi', label: 'RSI' },
                              { value: 'volatility', label: 'Volatility' },
                            ]}
                          />
                        </Col>
                        <Col xs={12} md={4}>
                          <label>{t('sentiment:comparison.window')}</label>
                          <InputNumber
                            min={1}
                            max={252}
                            value={cmpParams.window}
                            onChange={(v) =>
                              setCmpParams((p) => ({ ...p, window: v ?? 63 }))
                            }
                            style={{ width: '100%', marginTop: 4 }}
                          />
                        </Col>
                        <Col xs={12} md={4}>
                          <label>{t('sentiment:comparison.topK')}</label>
                          <InputNumber
                            min={1}
                            max={50}
                            value={cmpParams.topK}
                            onChange={(v) => setCmpParams((p) => ({ ...p, topK: v ?? 3 }))}
                            style={{ width: '100%', marginTop: 4 }}
                          />
                        </Col>
                        <Col xs={12} md={5}>
                          <label>{t('sentiment:comparison.modeLabel')}</label>
                          <ToggleSelect
                            value={cmpParams.mode}
                            onChange={(v) =>
                              setCmpParams((p) => ({ ...p, mode: v as ComparisonMode }))
                            }
                            options={[
                              {
                                value: 'overlay',
                                label: t('sentiment:comparison.mode.overlay'),
                              },
                              {
                                value: 'combined',
                                label: t('sentiment:comparison.mode.combined'),
                              },
                            ]}
                            width="100%"
                          />
                        </Col>
                        <Col xs={12} md={5}>
                          <label>{t('sentiment:comparison.sentimentThreshold')}</label>
                          <InputNumber
                            min={-1}
                            max={1}
                            step={0.1}
                            value={cmpParams.sentimentThreshold}
                            onChange={(v) =>
                              setCmpParams((p) => ({ ...p, sentimentThreshold: v ?? 0 }))
                            }
                            style={{ width: '100%', marginTop: 4 }}
                          />
                        </Col>
                      </Row>
                      <Row gutter={16} style={{ marginTop: 12 }}>
                        <Col xs={12} md={4}>
                          <label>{t('sentiment:comparison.sentimentWeight')}</label>
                          <InputNumber
                            min={0}
                            max={1}
                            step={0.1}
                            value={cmpParams.sentimentWeight}
                            onChange={(v) =>
                              setCmpParams((p) => ({ ...p, sentimentWeight: v ?? 0.5 }))
                            }
                            style={{ width: '100%', marginTop: 4 }}
                          />
                        </Col>
                        <Col xs={12} md={5}>
                          <label>{t('sentiment:comparison.costBps')}</label>
                          <InputNumber
                            min={0}
                            step={5}
                            value={cmpAdvanced.costBps}
                            onChange={(v) =>
                              setCmpAdvanced((p) => ({ ...p, costBps: v ?? 0 }))
                            }
                            style={{ width: '100%', marginTop: 4 }}
                          />
                        </Col>
                        <Col xs={12} md={5}>
                          <label>{t('sentiment:comparison.initialCapital')}</label>
                          <InputNumber
                            min={1}
                            value={cmpAdvanced.initialCapital}
                            onChange={(v) =>
                              setCmpAdvanced((p) => ({
                                ...p,
                                initialCapital: v ?? 100_000,
                              }))
                            }
                            style={{ width: '100%', marginTop: 4 }}
                          />
                        </Col>
                        <Col xs={12} md={5}>
                          <label>{t('sentiment:comparison.rebalance')}</label>
                          <ToggleSelect
                            value={cmpAdvanced.rebalance}
                            onChange={(v) =>
                              setCmpAdvanced((p) => ({
                                ...p,
                                rebalance: v as RebalanceFreq,
                              }))
                            }
                            options={[
                              { value: 'daily', label: t('backtest:rebalance.daily') },
                              { value: 'weekly', label: t('backtest:rebalance.weekly') },
                              { value: 'monthly', label: t('backtest:rebalance.monthly') },
                            ]}
                            width="100%"
                          />
                        </Col>
                        <Col xs={12} md={5}>
                          <label>{t('sentiment:comparison.includeSentimentOnly')}</label>
                          <ToggleSelect
                            value={String(cmpParams.includeSentimentOnly)}
                            onChange={(v) =>
                              setCmpParams((p) => ({
                                ...p,
                                includeSentimentOnly: v === 'true',
                              }))
                            }
                            options={[
                              { value: 'false', label: t('common:actions.close') },
                              { value: 'true', label: t('common:actions.confirm') },
                            ]}
                            width="100%"
                          />
                        </Col>
                      </Row>
                    </Card>
                  </Col>

                  <Col span={24}>
                    <Space>
                      <Button
                        type="primary"
                        onClick={() => void handleRunComparison()}
                        loading={cmpPhase === 'polling'}
                        disabled={!formValues}
                      >
                        {t('sentiment:comparison.run')}
                      </Button>
                    </Space>
                  </Col>

                  {cmpError && (
                    <Col span={24}>
                      <Alert type="error" showIcon message={cmpError} />
                    </Col>
                  )}
                  {cmpPhase === 'timeout' && (
                    <Col span={24}>
                      <Alert type="warning" showIcon message={t('sentiment:run.timeout')} />
                    </Col>
                  )}
                  {cmpPhase === 'polling' && (
                    <Col span={24}>
                      <div className="loading-block">
                        <Spin tip={t('sentiment:run.polling')}>
                          <div style={{ height: 48 }} />
                        </Spin>
                      </div>
                    </Col>
                  )}
                  {cmpResult && cmpPhase === 'success' && (
                    <Col span={24}>
                      <Card
                        title={t('sentiment:comparison.metricsTable.title')}
                        size="small"
                        className="panel"
                      >
                        <Table<Record<string, string | number>>
                          rowKey="key"
                          columns={comparisonMetricsColumns}
                          dataSource={comparisonMetricsData}
                          pagination={false}
                          size="small"
                        />
                      </Card>
                    </Col>
                  )}
                  {!cmpResult && cmpPhase === 'idle' && !cmpError && (
                    <Col span={24}>
                      <Empty description={t('sentiment:comparison.noData')} />
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

// --- standalone config form component ---------------------------------------

interface SentimentConfigFormProps {
  watchlistOptions: { value: string; label: string }[];
  onSubmit: (values: RawFormValues) => void;
}

function SentimentConfigForm({ watchlistOptions, onSubmit }: SentimentConfigFormProps) {
  const { t } = useTranslation();
  const [form] = Form.useForm<RawFormValues>();

  return (
    <Form<RawFormValues>
      form={form}
      layout="vertical"
      initialValues={{
        name: '',
        modelName: 'gpt-4o-mini',
        provider: '',
        classifier: '',
        range: [dayjs().subtract(1, 'year'), dayjs()],
      }}
      onFinish={(v) => onSubmit(v)}
    >
      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Form.Item
            name="watchlistId"
            label={t('sentiment:form.watchlist')}
            rules={[{ required: true, message: t('errors:validation') }]}
          >
            <ToggleSelect
              options={watchlistOptions}
              placeholder={t('sentiment:form.watchlistPlaceholder')}
              width="100%"
            />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item
            name="range"
            label={t('sentiment:form.dateRange')}
            rules={[{ required: true, message: t('errors:validation') }]}
          >
            <RangePicker allowClear={false} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Form.Item
            name="modelName"
            label={t('sentiment:form.modelName')}
            rules={[{ required: true, message: t('errors:validation') }]}
          >
            <Input placeholder={t('sentiment:form.modelNamePlaceholder')} />
          </Form.Item>
        </Col>
        <Col xs={12} md={8}>
          <Form.Item name="provider" label={t('sentiment:form.provider')}>
            <Input placeholder={t('sentiment:form.providerPlaceholder')} />
          </Form.Item>
        </Col>
        <Col xs={12} md={8}>
          <Form.Item name="classifier" label={t('sentiment:form.classifier')}>
            <Input placeholder={t('sentiment:form.classifierPlaceholder')} />
          </Form.Item>
        </Col>
      </Row>
    </Form>
  );
}

export default SentimentResearchPage;
