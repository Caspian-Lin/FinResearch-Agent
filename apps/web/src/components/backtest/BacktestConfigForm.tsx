/**
 * Backtest configuration form (FRA-38).
 *
 * Selects a watchlist as the universe (= all of its assets), a registered
 * strategy (+ its params), a date window, and an optional benchmark asset; on
 * submit it builds a `BacktestCreateRequest` for POST /backtest. Strategy params
 * render dynamically (ma_crossover → fast/slow, momentum → lookback/top_k,
 * reversal → lookback/bottom_k); buy_hold/equal_weight take none. Benchmark uses
 * the asset search endpoint (debounced) so QQQ/SPY etc. are selectable beyond
 * the universe.
 */
import { useCallback, useRef, useState } from 'react';
import {
  Button,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Typography,
} from 'antd';
import { useTranslation } from 'react-i18next';
import type { Dayjs } from 'dayjs';
import dayjs from 'dayjs';

import { searchAssets } from '@/api/assets';
import type {
  AssetRead,
  BacktestCreateRequest,
  BacktestPriceField,
  BacktestStrategyName,
  RebalanceFreq,
  WatchlistRead,
} from '@/types/api';

const { RangePicker } = DatePicker;
const { Text } = Typography;

const STRATEGIES: BacktestStrategyName[] = [
  'buy_hold',
  'equal_weight',
  'ma_crossover',
  'momentum',
  'reversal',
];

/** Per-strategy numeric params rendered in the form (defaults match the backend). */
const STRATEGY_PARAMS: Record<
  BacktestStrategyName,
  { key: string; labelKey: string; def: number; min: number; max: number }[]
> = {
  buy_hold: [],
  equal_weight: [],
  ma_crossover: [
    { key: 'fast', labelKey: 'backtest:strategy.params.fast', def: 5, min: 1, max: 1000 },
    { key: 'slow', labelKey: 'backtest:strategy.params.slow', def: 20, min: 2, max: 1000 },
  ],
  momentum: [
    { key: 'lookback', labelKey: 'backtest:strategy.params.lookback', def: 63, min: 1, max: 1000 },
    { key: 'top_k', labelKey: 'backtest:strategy.params.topK', def: 1, min: 1, max: 1000 },
  ],
  reversal: [
    { key: 'lookback', labelKey: 'backtest:strategy.params.lookback', def: 63, min: 1, max: 1000 },
    { key: 'bottom_k', labelKey: 'backtest:strategy.params.bottomK', def: 1, min: 1, max: 1000 },
  ],
};

interface FormValues {
  name: string;
  watchlistId: string;
  strategy: BacktestStrategyName;
  range: [Dayjs, Dayjs];
  benchmarkAssetId?: string;
  initialCapital: number;
  costBps: number;
  rebalance: RebalanceFreq;
  priceField: BacktestPriceField;
  // Dynamic strategy params are stored as `param_<key>` (index signature below).
  [paramKey: string]: unknown;
}

interface BacktestConfigFormProps {
  watchlists: WatchlistRead[];
  submitting: boolean;
  onSubmit: (req: BacktestCreateRequest, symbolByAsset: Record<string, string>) => void;
}

export function BacktestConfigForm({ watchlists, submitting, onSubmit }: BacktestConfigFormProps) {
  const { t } = useTranslation();
  const [form] = Form.useForm<FormValues>();
  const [strategy, setStrategy] = useState<BacktestStrategyName>('buy_hold');
  const [benchmarkOptions, setBenchmarkOptions] = useState<AssetRead[]>([]);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const watchlistOptions = watchlists.map((w) => ({
    value: w.watchlist_id,
    label: `${w.name} (${w.items.length})`,
  }));

  const handleBenchmarkSearch = useCallback((symbol: string) => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => {
      const q = symbol.trim().toUpperCase();
      if (!q) {
        setBenchmarkOptions([]);
        return;
      }
      searchAssets({ symbol: q })
        .then(setBenchmarkOptions)
        .catch(() => setBenchmarkOptions([]));
    }, 300);
  }, []);

  const handleFinish = (values: FormValues) => {
    const wl = watchlists.find((w) => w.watchlist_id === values.watchlistId);
    const universe = wl ? wl.items.map((it) => it.asset_id) : [];

    const strategyParams: Record<string, number> = {};
    for (const def of STRATEGY_PARAMS[strategy]) {
      const v = values[`param_${def.key}`];
      if (typeof v === 'number') strategyParams[def.key] = v;
    }

    const symbolByAsset: Record<string, string> = {};
    if (wl) for (const it of wl.items) symbolByAsset[it.asset_id] = it.symbol;

    onSubmit(
      {
        name: values.name,
        strategy_name: strategy,
        universe,
        start: values.range[0].format('YYYY-MM-DD'),
        end: values.range[1].format('YYYY-MM-DD'),
        benchmark_asset_id: values.benchmarkAssetId || null,
        initial_capital: values.initialCapital,
        cost_bps: values.costBps,
        rebalance: values.rebalance,
        price_field: values.priceField,
        strategy_params: strategyParams,
      },
      symbolByAsset,
    );
  };

  return (
    <Form<FormValues>
      form={form}
      layout="vertical"
      initialValues={{
        strategy: 'buy_hold',
        initialCapital: 100000,
        costBps: 0,
        rebalance: 'daily',
        priceField: 'adjusted',
        range: [dayjs().subtract(1, 'year'), dayjs()],
      }}
      onFinish={(v) => handleFinish(v)}
    >
      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Form.Item
            name="name"
            label={t('backtest:form.name')}
            rules={[{ required: true, message: t('errors:validation') }]}
          >
            <Input maxLength={255} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item
            name="watchlistId"
            label={t('backtest:form.watchlist')}
            rules={[{ required: true, message: t('errors:validation') }]}
          >
            <Select
              options={watchlistOptions}
              placeholder={t('backtest:form.watchlistPlaceholder')}
            />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Form.Item
            name="strategy"
            label={t('backtest:form.strategy')}
            rules={[{ required: true, message: t('errors:validation') }]}
          >
            <Select
              options={STRATEGIES.map((s) => ({ value: s, label: t(`backtest:strategy.${s}`) }))}
              onChange={(v: BacktestStrategyName) => setStrategy(v)}
            />
          </Form.Item>
        </Col>
        {STRATEGY_PARAMS[strategy].map((def) => (
          <Col xs={24} md={8} key={def.key}>
            <Form.Item
              name={`param_${def.key}`}
              label={t(def.labelKey)}
              initialValue={def.def}
              rules={[{ required: true, message: t('errors:validation') }]}
            >
              <InputNumber min={def.min} max={def.max} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
        ))}
      </Row>

      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Form.Item
            name="range"
            label={t('backtest:form.dateRange')}
            rules={[{ required: true, message: t('errors:validation') }]}
          >
            <RangePicker allowClear={false} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name="benchmarkAssetId" label={t('backtest:form.benchmark')}>
            <Select
              showSearch
              allowClear
              placeholder={t('backtest:form.benchmarkPlaceholder')}
              filterOption={false}
              onSearch={handleBenchmarkSearch}
              options={benchmarkOptions.map((a) => ({
                value: a.asset_id,
                label: `${a.symbol} · ${a.exchange}`,
              }))}
            />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col xs={12} md={6}>
          <Form.Item name="initialCapital" label={t('backtest:form.initialCapital')}>
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col xs={12} md={6}>
          <Form.Item name="costBps" label={t('backtest:form.costBps')}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col xs={12} md={6}>
          <Form.Item name="rebalance" label={t('backtest:form.rebalance')}>
            <Select
              options={(['daily', 'weekly', 'monthly'] as RebalanceFreq[]).map((r) => ({
                value: r,
                label: t(`backtest:rebalance.${r}`),
              }))}
            />
          </Form.Item>
        </Col>
        <Col xs={12} md={6}>
          <Form.Item name="priceField" label={t('backtest:form.priceField')}>
            <Select
              options={(['adjusted', 'raw'] as BacktestPriceField[]).map((p) => ({
                value: p,
                label: t(`backtest:priceField.${p}`),
              }))}
            />
          </Form.Item>
        </Col>
      </Row>

      <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
        <Text type="secondary">{t('backtest:form.hint')}</Text>
        <Button type="primary" htmlType="submit" loading={submitting}>
          {t('backtest:form.run')}
        </Button>
      </Space>
    </Form>
  );
}

export default BacktestConfigForm;
