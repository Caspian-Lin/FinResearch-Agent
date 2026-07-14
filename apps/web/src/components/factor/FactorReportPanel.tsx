/**
 * One-page factor performance report panel (FRA-77).
 *
 * Aggregates the page's existing research results (IC / quantile /
 * sensitivity) plus the current config form values into a single readable
 * report: a configuration & assumptions snapshot, a performance summary (IC
 * stats, quantile monotonicity + long−short ending value, best/worst net
 * Sharpe + high-impact params), and a fixed limitations / disclaimer block.
 * Supports JSON (reproducible snapshot) and Markdown (human-readable) export
 * via the pure builders in `factorReport.ts`.
 *
 * Read-only and fully client-side — it never triggers compute. Any not-yet-run
 * research action degrades to a "—" / "not run" placeholder rather than hiding
 * its section, so the report always shows what was and wasn't computed.
 */
import { DownloadOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Col, Descriptions, Row, Space, Statistic, Tag, Typography } from 'antd';
import { useTranslation } from 'react-i18next';

import {
  buildFactorReportJson,
  buildFactorReportMarkdown,
  downloadText,
  highImpactParams,
  topMinusBottomEndingValue,
  type FactorReportConfig,
  type FactorReportInput,
  type FactorReportLabels,
} from './factorReport';
import { ICSummaryCards } from './ICSummaryCards';
import type { ICResult, QuantileResult, SensitivitySummary } from '@/types/api';

const { Text } = Typography;

interface FactorReportPanelProps {
  config: FactorReportConfig | null;
  icResult: ICResult | null;
  qResult: QuantileResult | null;
  sResult: SensitivitySummary | null;
}

/** Format a nullable/NaN number to fixed digits, or an em dash when absent. */
function fmt(v: number | null | undefined, digits: number): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return v.toFixed(digits);
}

export function FactorReportPanel({ config, icResult, qResult, sResult }: FactorReportPanelProps) {
  const { t } = useTranslation();

  // Markdown copy injected from i18n so the pure builder stays deterministic.
  // IC stat labels reuse the existing `factor:ic.*` keys (no duplication).
  const labels: FactorReportLabels = {
    title: t('factor:report.title'),
    configHeading: t('factor:report.headings.config'),
    metricsHeading: t('factor:report.headings.metrics'),
    limitationsHeading: t('factor:report.headings.limitations'),
    configFactor: t('factor:report.config.factor'),
    configSource: t('factor:report.config.source'),
    configWindow: t('factor:report.config.window'),
    configUniverse: t('factor:report.config.universe'),
    configHorizon: t('factor:report.config.horizon'),
    configNQuantiles: t('factor:report.config.nQuantiles'),
    configPriceField: t('factor:report.config.priceField'),
    configCostBands: t('factor:report.config.costBands'),
    icSummary: t('factor:report.metrics.icSummary'),
    quantileHeading: t('factor:report.metrics.quantile'),
    sensitivityHeading: t('factor:report.metrics.sensitivity'),
    quantileMonotonicity: t('factor:report.metrics.monotonicity'),
    tmbEnding: t('factor:report.metrics.tmbEnding'),
    bestSharpe: t('factor:report.metrics.bestSharpe'),
    worstSharpe: t('factor:report.metrics.worstSharpe'),
    highImpactParams: t('factor:report.metrics.highImpactParams'),
    icMean: t('factor:ic.mean'),
    icIcir: t('factor:ic.icir'),
    icTStat: t('factor:ic.tStat'),
    icPValue: t('factor:ic.pValue'),
    icN: t('factor:ic.n'),
    icPositiveRate: t('factor:ic.positiveRate'),
    notRun: t('factor:report.notRun'),
    none: t('factor:report.none'),
    limitations: [
      t('factor:report.limitations.icNotAlpha'),
      t('factor:report.limitations.shortWindow'),
      t('factor:report.limitations.singleSource'),
      t('factor:report.limitations.survivorship'),
      t('factor:report.limitations.lookAhead'),
    ],
    disclaimer: t('factor:report.limitations.disclaimer'),
  };

  const input: FactorReportInput = { config, ic: icResult, quantile: qResult, sensitivity: sResult };
  const baseName = config?.factor ?? 'factor';

  const handleExportJson = () => {
    const json = JSON.stringify(buildFactorReportJson(input), null, 2);
    downloadText(`factor-report-${baseName}.json`, json, 'application/json');
  };
  const handleExportMarkdown = () => {
    const md = buildFactorReportMarkdown(input, labels);
    downloadText(`factor-report-${baseName}.md`, md, 'text/markdown');
  };

  const tmbEnding = topMinusBottomEndingValue(qResult);
  const hiParams = highImpactParams(sResult);

  return (
    <Card
      title={t('factor:report.title')}
      size="small"
      className="panel"
      extra={
        <Space>
          <Button size="small" icon={<DownloadOutlined />} onClick={handleExportJson}>
            {t('factor:report.export.json')}
          </Button>
          <Button size="small" icon={<DownloadOutlined />} onClick={handleExportMarkdown}>
            {t('factor:report.export.markdown')}
          </Button>
        </Space>
      }
    >
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
        {t('factor:report.intro')}
      </Text>

      {/* Configuration & assumptions */}
      <Card
        size="small"
        type="inner"
        title={t('factor:report.headings.config')}
        style={{ marginBottom: 16 }}
      >
        {config ? (
          <Descriptions size="small" column={{ xs: 1, sm: 2, md: 4 }} bordered>
            <Descriptions.Item label={t('factor:report.config.factor')}>
              {t(`factor:factors.${config.factor}`, { defaultValue: config.factor })}
            </Descriptions.Item>
            <Descriptions.Item label={t('factor:report.config.source')}>{config.source}</Descriptions.Item>
            <Descriptions.Item label={t('factor:report.config.window')}>
              {config.start} → {config.end}
            </Descriptions.Item>
            <Descriptions.Item label={t('factor:report.config.universe')}>{config.universeSize}</Descriptions.Item>
            <Descriptions.Item label={t('factor:report.config.horizon')}>{config.horizon}</Descriptions.Item>
            <Descriptions.Item label={t('factor:report.config.nQuantiles')}>{config.nQuantiles}</Descriptions.Item>
            <Descriptions.Item label={t('factor:report.config.priceField')}>
              {t(`factor:priceField.${config.priceField}`, { defaultValue: config.priceField })}
            </Descriptions.Item>
            <Descriptions.Item label={t('factor:report.config.costBands')}>
              {config.costBands.join(', ')}
            </Descriptions.Item>
          </Descriptions>
        ) : (
          <Text type="secondary">{t('factor:report.notRun')}</Text>
        )}
      </Card>

      {/* Performance summary */}
      <Card
        size="small"
        type="inner"
        title={t('factor:report.headings.metrics')}
        style={{ marginBottom: 16 }}
      >
        <Text strong style={{ display: 'block', marginBottom: 8 }}>
          {t('factor:report.metrics.icSummary')}
        </Text>
        {icResult ? <ICSummaryCards summary={icResult.summary} /> : (
          <Text type="secondary">{t('factor:report.notRun')}</Text>
        )}

        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col xs={12} md={6}>
            <Statistic title={t('factor:report.metrics.monotonicity')} value={fmt(qResult?.monotonicity, 3)} />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title={t('factor:report.metrics.tmbEnding')} value={fmt(tmbEnding, 4)} />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title={t('factor:report.metrics.bestSharpe')}
              value={fmt(sResult?.best_net_sharpe, 3)}
            />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title={t('factor:report.metrics.worstSharpe')}
              value={fmt(sResult?.worst_net_sharpe, 3)}
            />
          </Col>
        </Row>

        <div style={{ marginTop: 16 }}>
          <Text strong style={{ marginRight: 8 }}>
            {t('factor:report.metrics.highImpactParams')}:
          </Text>
          {sResult ? (
            hiParams.length > 0 ? (
              hiParams.map((p) => <Tag key={p}>{p}</Tag>)
            ) : (
              <Text type="secondary">{t('factor:report.metrics.noHighImpact')}</Text>
            )
          ) : (
            <Text type="secondary">{t('factor:report.notRun')}</Text>
          )}
        </div>
      </Card>

      {/* Limitations & disclaimer */}
      <Alert
        type="warning"
        showIcon
        message={t('factor:report.limitations.title')}
        description={
          <>
            <ul style={{ margin: '0 0 8px', paddingLeft: 20 }}>
              {labels.limitations.map((lim, i) => (
                <li key={i}>{lim}</li>
              ))}
            </ul>
            <Text strong>{labels.disclaimer}</Text>
          </>
        }
      />
    </Card>
  );
}

export default FactorReportPanel;
