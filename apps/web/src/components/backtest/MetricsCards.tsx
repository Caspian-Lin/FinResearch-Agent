/**
 * Gross + net metric cards for a finished backtest (FRA-38).
 *
 * Renders the 9 metrics (annual return, volatility, sharpe, max drawdown,
 * calmar, turnover, win rate, beta, correlation) for both the gross (pre-cost)
 * and net (post-cost) sets, side by side. Null fields (e.g. beta/correlation
 * without a benchmark, or any metric while pending) render as "—". Percent-typed
 * metrics are shown ×100; ratios keep their natural scale.
 */
import { Card, Col, Row, Statistic, Typography } from 'antd';
import { useTranslation } from 'react-i18next';

import type { BacktestMetricsRead } from '@/types/api';

const { Text } = Typography;

/** One metric definition: field suffix + whether it is a percent (×100). */
interface MetricDef {
  key: string;
  percent: boolean;
}

const METRICS: MetricDef[] = [
  { key: 'annual_return', percent: true },
  { key: 'volatility', percent: true },
  { key: 'sharpe_ratio', percent: false },
  { key: 'max_drawdown', percent: true },
  { key: 'calmar_ratio', percent: false },
  { key: 'turnover', percent: true },
  { key: 'win_rate', percent: true },
  { key: 'beta', percent: false },
  { key: 'correlation', percent: false },
];

function readMetric(
  metrics: BacktestMetricsRead,
  prefix: 'gross' | 'net',
  key: string,
): number | null {
  // The only non-numeric field is `backtest_run_id`; our keys never hit it.
  const field = `${prefix}_${key}` as keyof BacktestMetricsRead;
  const v = metrics[field];
  return typeof v === 'number' ? v : null;
}

function formatMetric(value: number | null, percent: boolean): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return percent ? `${(value * 100).toFixed(2)}%` : value.toFixed(3);
}

function MetricColumn({
  title,
  metrics,
  prefix,
}: {
  title: string;
  metrics: BacktestMetricsRead | null;
  prefix: 'gross' | 'net';
}) {
  const { t } = useTranslation();
  return (
    <Col xs={24} lg={12}>
      <Text strong>{title}</Text>
      <Row gutter={[16, 16]} style={{ marginTop: 12 }}>
        {METRICS.map((m) => (
          <Col xs={12} md={8} key={m.key}>
            <Statistic
              title={t(`backtest:metrics.${m.key}`)}
              value={formatMetric(metrics ? readMetric(metrics, prefix, m.key) : null, m.percent)}
            />
          </Col>
        ))}
      </Row>
    </Col>
  );
}

interface MetricsCardsProps {
  metrics: BacktestMetricsRead | null;
}

export function MetricsCards({ metrics }: MetricsCardsProps) {
  const { t } = useTranslation();
  return (
    <Card title={t('backtest:metrics.title')} size="small">
      <Row gutter={[24, 24]}>
        <MetricColumn title={t('backtest:metrics.gross')} metrics={metrics} prefix="gross" />
        <MetricColumn title={t('backtest:metrics.net')} metrics={metrics} prefix="net" />
      </Row>
    </Card>
  );
}

export default MetricsCards;
