/**
 * Shared backtest result renderer.
 *
 * Keeps metrics, curves, and trades in one place so the create and history
 * routes can diverge in workflow without duplicating result presentation.
 */
import { Card, Col, Empty, Row } from 'antd';
import { useTranslation } from 'react-i18next';

import { BacktestCurveChart } from '@/components/backtest/BacktestCurveChart';
import { MetricsCards } from '@/components/backtest/MetricsCards';
import { TradesTable } from '@/components/backtest/TradesTable';
import {
  buildDrawdownOption,
  buildEquityCurveOption,
} from '@/components/backtest/equityChartOption';
import type { BacktestDetailRead } from '@/types/api';

interface BacktestResultDetailProps {
  detail: BacktestDetailRead;
  symbolByAsset?: Record<string, string>;
}

export function BacktestResultDetail({ detail, symbolByAsset = {} }: BacktestResultDetailProps) {
  const { t } = useTranslation();

  return (
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
  );
}

export default BacktestResultDetail;
