/**
 * RunResult — research synthesis display.
 *
 * Renders the synthesis dict produced by the Report Agent: scope, key
 * observations (with citation refs), risk findings, limitations,
 * assumptions, data gaps, and the mandatory disclaimer. The restricted
 * banner is shown when the synthesis was produced with risk-check
 * failures — no affirmative conclusions are displayed in that case.
 *
 * All text comes from the backend synthesis dict; no client-side LLM
 * generation occurs. The disclaimer is always visible, regardless of
 * restricted status.
 */
import { useTranslation } from 'react-i18next';
import { Alert, Card, Descriptions, Empty, List, Space, Tag, Typography } from 'antd';
import {
  ExclamationCircleOutlined,
  FileSearchOutlined,
  WarningOutlined,
} from '@ant-design/icons';

const { Text, Paragraph, Title } = Typography;

/** Safely coerce an unknown synthesis field to display string. */
function str(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  return JSON.stringify(v);
}

interface RunResultProps {
  synthesis: Record<string, unknown> | null;
  restricted: boolean;
}

interface KeyObservation {
  metric: string;
  value: string;
  interpretation: string;
  citation?: {
    ref_type: string;
    ref_id: string;
    field?: string | null;
  };
  window?: string | null;
}

function RunResult({ synthesis, restricted }: RunResultProps) {
  const { t } = useTranslation('agent');

  if (!synthesis) {
    return <Empty description={t('result.noResult')} />;
  }

  const scope = (synthesis.scope ?? {}) as Record<string, unknown>;
  const methodology = (synthesis.methodology ?? {}) as Record<string, unknown>;
  const observations = (synthesis.key_observations ?? []) as KeyObservation[];
  const riskFindings = (synthesis.risk_findings_summary ?? []) as Record<string, unknown>[];
  const limitations = (synthesis.limitations ?? []) as string[];
  const assumptions = (synthesis.assumptions ?? []) as string[];
  const dataGaps = (synthesis.data_gaps ?? []) as string[];
  const citedRefs = (synthesis.cited_refs ?? []) as string[];
  const provenance = (synthesis.provenance ?? {}) as Record<string, unknown>;
  const disclaimer = (synthesis.disclaimer as string) ?? '';
  const researchQuestion = (synthesis.research_question as string) ?? '';


  return (
    <div className="agent-run-result">
      {restricted && (
        <Alert
          type="warning"
          showIcon
          icon={<WarningOutlined />}
          message={t('result.restricted')}
          className="agent-alert"
        />
      )}

      <Title level={4}>{t('result.title')}</Title>
      <Paragraph strong>{researchQuestion}</Paragraph>

      {/* Scope */}
      <Card size="small" title={t('result.scope')} className="agent-result-card">
        <Descriptions column={1} size="small">
          <Descriptions.Item label={t('result.window')}>
            {str(scope.window)}
          </Descriptions.Item>
          <Descriptions.Item label={t('result.universeLabel')}>
            {Array.isArray(scope.universe) ? (scope.universe as string[]).join(', ') : '—'}
          </Descriptions.Item>
          <Descriptions.Item label={t('result.benchmarkLabel')}>
            {str(scope.benchmark)}
          </Descriptions.Item>
          <Descriptions.Item label={t('result.dataSource')}>
            {str(scope.data_source)}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* Methodology */}
      <Card size="small" title={t('result.methodology')} className="agent-result-card">
        <Descriptions column={1} size="small">
          <Descriptions.Item label={t('result.strategyLabel')}>
            {str(methodology.strategy)}
          </Descriptions.Item>
          <Descriptions.Item label={t('result.rebalance')}>
            {str(methodology.rebalance)}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* Key Observations */}
      {!restricted && observations.length > 0 && (
        <Card
          size="small"
          title={<Space><FileSearchOutlined /> {t('result.keyObservations')}</Space>}
          className="agent-result-card"
        >
          <List
            dataSource={observations}
            renderItem={(obs, idx) => (
              <List.Item key={idx}>
                <div className="agent-observation">
                  <div className="agent-observation-header">
                    <Text strong>{obs.metric}</Text>
                    <Tag color="blue">{obs.value}</Tag>
                    {obs.window && <Tag>{obs.window}</Tag>}
                  </div>
                  <Paragraph className="agent-observation-text">{obs.interpretation}</Paragraph>
                  {obs.citation && (
                    <div className="agent-observation-citation">
                      <Tag color="default">
                        {obs.citation.ref_type}: {obs.citation.ref_id}
                        {obs.citation.field ? `.${obs.citation.field}` : ''}
                      </Tag>
                    </div>
                  )}
                </div>
              </List.Item>
            )}
          />
        </Card>
      )}

      {/* Risk Findings */}
      {riskFindings.length > 0 && (
        <Card
          size="small"
          title={<Space><ExclamationCircleOutlined /> {t('result.riskFindings')}</Space>}
          className="agent-result-card"
        >
          <List
            dataSource={riskFindings}
            renderItem={(rf, idx) => {
              const status = str(rf.status);
              const detail = rf.detail ? str(rf.detail) : null;
              return (
              <List.Item key={idx}>
                <div>
                  <Text>{str(rf.check ?? rf.name ?? rf.rule)}</Text>
                  {status !== '—' && (
                    <Tag
                      color={
                        status === 'pass'
                          ? 'success'
                          : status === 'fail'
                            ? 'error'
                            : 'warning'
                      }
                      className="agent-risk-tag"
                    >
                      {status}
                    </Tag>
                  )}
                  {detail && (
                    <Paragraph type="secondary" className="agent-risk-detail">
                      {detail}
                    </Paragraph>
                  )}
                </div>
              </List.Item>
              );
            }}
          />
        </Card>
      )}

      {/* Limitations */}
      {limitations.length > 0 && (
        <Card size="small" title={t('result.limitations')} className="agent-result-card">
          <ul className="agent-result-list">
            {limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </Card>
      )}

      {/* Assumptions */}
      {assumptions.length > 0 && (
        <Card size="small" title={t('result.assumptions')} className="agent-result-card">
          <ul className="agent-result-list">
            {assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </Card>
      )}

      {/* Data Gaps */}
      {dataGaps.length > 0 && (
        <Card size="small" title={t('result.dataGaps')} className="agent-result-card">
          <ul className="agent-result-list">
            {dataGaps.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        </Card>
      )}

      {/* Citations */}
      {citedRefs.length > 0 && (
        <Card size="small" title={t('result.citations')} className="agent-result-card">
          <Space wrap>
            {citedRefs.map((ref, i) => (
              <Text key={i} code>
                {ref}
              </Text>
            ))}
          </Space>
        </Card>
      )}

      {/* Provenance */}
      {Object.keys(provenance).length > 0 && (
        <Card size="small" title={t('result.provenance')} className="agent-result-card">
          <Descriptions column={1} size="small">
            {provenance.planner_provider ? (
              <Descriptions.Item label={t('result.plannerModel')}>
                {str(provenance.planner_provider)} / {str(provenance.planner_model)}
              </Descriptions.Item>
            ) : null}
            {provenance.report_provider ? (
              <Descriptions.Item label={t('result.reportModel')}>
                {str(provenance.report_provider)} / {str(provenance.report_model)}
              </Descriptions.Item>
            ) : null}
          </Descriptions>
        </Card>
      )}

      {/* Mandatory Disclaimer */}
      <Alert
        type="warning"
        showIcon
        className="agent-alert agent-result-disclaimer"
        message={t('result.disclaimer')}
        description={disclaimer || t('disclaimer.banner')}
      />
    </div>
  );
}

export { RunResult };
export type { RunResultProps };
export { RunResult as default };
