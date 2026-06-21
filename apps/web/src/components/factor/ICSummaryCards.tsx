/**
 * IC summary statistic cards (FRA-58).
 *
 * Renders the six `ICSummary` numbers (mean / ICIR / t-stat / p-value / n /
 * positive_rate) as a compact antd `Statistic` strip. `p_value` / `positive_rate`
 * render as proportions; the rest as fixed-precision decimals. These are the
 * headline factor-quality numbers a researcher scans first (alongside the IC chart).
 */
import { Card, Col, Row, Statistic } from 'antd';
import { useTranslation } from 'react-i18next';

import type { ICSummary } from '@/types/api';

interface ICSummaryCardsProps {
  summary: ICSummary;
}

export function ICSummaryCards({ summary }: ICSummaryCardsProps) {
  const { t } = useTranslation();

  return (
    <Card size="small" className="panel">
      <Row gutter={[16, 16]}>
        <Col xs={12} md={8} lg={4}>
          <Statistic title={t('factor:ic.mean')} value={summary.mean} precision={3} />
        </Col>
        <Col xs={12} md={8} lg={4}>
          <Statistic title={t('factor:ic.icir')} value={summary.icir} precision={3} />
        </Col>
        <Col xs={12} md={8} lg={4}>
          <Statistic title={t('factor:ic.tStat')} value={summary.t_stat} precision={2} />
        </Col>
        <Col xs={12} md={8} lg={4}>
          <Statistic title={t('factor:ic.pValue')} value={summary.p_value} precision={3} />
        </Col>
        <Col xs={12} md={8} lg={4}>
          <Statistic title={t('factor:ic.n')} value={summary.n} />
        </Col>
        <Col xs={12} md={8} lg={4}>
          <Statistic
            title={t('factor:ic.positiveRate')}
            value={summary.positive_rate}
            precision={2}
            suffix=""
          />
        </Col>
      </Row>
    </Card>
  );
}

export default ICSummaryCards;
