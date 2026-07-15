/**
 * RunTimeline — step-by-step execution timeline with nested tool calls.
 *
 * Displays the ordered steps from `GET /agent/runs/{id}/trace`. Each step
 * shows its agent role, status badge, duration, and expandable tool calls.
 * Tool call args/results are pre-sanitized server-side; we display them as
 * formatted JSON snippets without exposing secrets, Authorization headers,
 * or raw tracebacks.
 *
 * The cancel button is shown only for non-terminal runs.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  Button,
  Collapse,
  Modal,
  Progress,
  Space,
  Tag,
  Typography,
} from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  LoadingOutlined,
  MinusCircleOutlined,
  StopOutlined,
} from '@ant-design/icons';

import type { AgentRunDetail, AgentTraceResponse, StepTrace, ToolCallTrace } from '@/types/api';
import { TERMINAL_RUN_STATUSES } from '@finresearch/shared';

const { Text, Paragraph } = Typography;

interface RunTimelineProps {
  run: AgentRunDetail;
  trace: AgentTraceResponse | null;
  traceLoading: boolean;
  canceling: boolean;
  onCancel: () => void;
}

function statusColor(status: string): string {
  switch (status) {
    case 'succeeded':
      return 'success';
    case 'failed':
      return 'error';
    case 'running':
      return 'processing';
    case 'canceled':
      return 'default';
    default:
      return 'wait';
  }
}

function statusIcon(status: string) {
  switch (status) {
    case 'succeeded':
      return <CheckCircleOutlined />;
    case 'failed':
      return <CloseCircleOutlined />;
    case 'running':
      return <LoadingOutlined />;
    case 'canceled':
      return <MinusCircleOutlined />;
    default:
      return <ClockCircleOutlined />;
  }
}

function isTerminal(status: string): boolean {
  return TERMINAL_RUN_STATUSES.has(status as never);
}

function ToolCallItem({ tc, t }: { tc: ToolCallTrace; t: (k: string) => string }) {
  const hasDetails = tc.args || tc.result || tc.error;
  const items = [
    tc.args && {
      key: 'args',
      label: t('trace.args'),
      children: (
        <pre className="agent-trace-json">
          {JSON.stringify(tc.args, null, 2)}
        </pre>
      ),
    },
    tc.result && {
      key: 'result',
      label: t('trace.result'),
      children: (
        <pre className="agent-trace-json">
          {JSON.stringify(tc.result, null, 2)}
        </pre>
      ),
    },
    tc.error && {
      key: 'error',
      label: t('trace.error'),
      children: <Text type="danger">{tc.error}</Text>,
    },
  ].filter(Boolean) as { key: string; label: string; children: React.ReactNode }[];

  return (
    <div className="agent-tool-call">
      <div className="agent-tool-call-header">
        <Tag color={statusColor(tc.status)} icon={statusIcon(tc.status)}>
          {tc.tool_name}
        </Tag>
        {tc.duration_ms !== null && (
          <Text type="secondary" className="agent-tool-duration">
            {tc.duration_ms}ms
          </Text>
        )}
        {tc.error_code && <Tag color="red">{tc.error_code}</Tag>}
      </div>
      {hasDetails && items.length > 0 && (
        <Collapse
          size="small"
          ghost
          items={items}
          className="agent-tool-collapse"
        />
      )}
      {tc.evidence_refs && tc.evidence_refs.length > 0 && (
        <div className="agent-tool-evidence">
          <Text type="secondary" className="agent-tool-evidence-label">
            {t('trace.evidence')} ({tc.evidence_refs.length})
          </Text>
        </div>
      )}
    </div>
  );
}

function StepItem({
  step,
  t,
}: {
  step: StepTrace;
  t: (k: string, opts?: Record<string, unknown>) => string;
}) {
  const roleLabel = t(`steps.${step.agent_role}`);
  const status = step.status;

  return (
    <div className="agent-step">
      <div className="agent-step-header">
        <Tag color={statusColor(status)} icon={statusIcon(status)}>
          {roleLabel}
        </Tag>
        {step.duration_ms !== null && (
          <Text type="secondary">{step.duration_ms}ms</Text>
        )}
        <Text type="secondary" className="agent-step-kind">
          {step.kind}
        </Text>
      </div>
      {step.error && (
        <Alert type="error" showIcon message={step.error} className="agent-alert" />
      )}
      {step.tool_calls.length > 0 && (
        <div className="agent-step-tools">
          <Text type="secondary" className="agent-step-tools-label">
            {t('trace.toolCalls')} ({step.tool_calls.length})
          </Text>
          {step.tool_calls.map((tc) => (
            <ToolCallItem key={tc.id} tc={tc} t={t} />
          ))}
        </div>
      )}
    </div>
  );
}

function RunTimeline({ run, trace, traceLoading, canceling, onCancel }: RunTimelineProps) {
  const { t } = useTranslation('agent');
  const [cancelModalOpen, setCancelModalOpen] = useState(false);

  const terminal = isTerminal(run.status);
  const percent =
    run.step_count > 0 ? Math.round((run.completed_steps / run.step_count) * 100) : 0;

  const handleCancel = () => {
    setCancelModalOpen(false);
    onCancel();
  };

  const currentStepLabel = run.current_step ? t(`steps.${run.current_step}`) : null;

  return (
    <div className="agent-run-timeline">
      <div className="agent-run-header">
        <Space>
          <Tag color={statusColor(run.status)} icon={statusIcon(run.status)}>
            {t(`run.${run.status}`, run.status)}
          </Tag>
          {currentStepLabel && !terminal && (
            <Text type="secondary">
              {t('run.currentStep')}: {currentStepLabel}
            </Text>
          )}
          {run.step_count > 0 && (
            <Text type="secondary">
              {t('run.progress', { done: run.completed_steps, total: run.step_count })}
            </Text>
          )}
        </Space>

        {!terminal && (
          <Button
            danger
            icon={<StopOutlined />}
            loading={canceling}
            onClick={() => setCancelModalOpen(true)}
          >
            {canceling ? t('run.canceling') : t('run.cancel')}
          </Button>
        )}
      </div>

      {run.step_count > 0 && (
        <Progress percent={percent} status={run.status === 'failed' ? 'exception' : undefined} />
      )}

      {run.error_summary && terminal && run.status === 'failed' && (
        <Alert
          type="error"
          showIcon
          message={t('run.errorSummary')}
          description={run.error_summary}
          className="agent-alert"
        />
      )}

      {traceLoading && !trace && (
        <Text type="secondary">{t('common:actions.loading')}</Text>
      )}

      {trace && trace.steps.length > 0 ? (
        <div className="agent-steps-container">
          <Text strong className="agent-trace-title">
            {t('trace.title')}
          </Text>
          {trace.steps.map((step) => (
            <StepItem key={step.id} step={step} t={t} />
          ))}
        </div>
      ) : trace && trace.steps.length === 0 ? (
        <Text type="secondary">{t('trace.noTrace')}</Text>
      ) : null}

      <Modal
        title={t('run.cancel')}
        open={cancelModalOpen}
        onOk={handleCancel}
        onCancel={() => setCancelModalOpen(false)}
        okText={t('run.cancelYes')}
        cancelText={t('run.cancelNo')}
        okButtonProps={{ danger: true }}
      >
        <Paragraph>{t('run.cancelConfirm')}</Paragraph>
      </Modal>
    </div>
  );
}

export { RunTimeline };
export type { RunTimelineProps };
export { RunTimeline as default };
