/**
 * QuestionComposer — the NL hypothesis input and plan-generation trigger.
 *
 * Submitting calls `createAgentPlan()` which hits `POST /agent/plans` — a
 * side-effect-free endpoint that returns a plan draft. No sync, backtest,
 * or any tool fires here. The parent page owns the plan state and decides
 * whether to show the PlanReview panel.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, Button, Input, Space, Typography } from 'antd';
import { RocketOutlined } from '@ant-design/icons';

const { Text } = Typography;
const { TextArea } = Input;

interface QuestionComposerProps {
  loading: boolean;
  error: string | null;
  onSubmit: (hypothesis: string) => void;
  examples: readonly string[];
}

function QuestionComposer({ loading, error, onSubmit, examples }: QuestionComposerProps) {
  const { t } = useTranslation('agent');
  const [value, setValue] = useState('');

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || loading) return;
    onSubmit(trimmed);
  };

  return (
    <div className="agent-composer">
      <div className="agent-composer-header">
        <Text strong>{t('composer.title')}</Text>
        <Text type="secondary" className="agent-composer-hint">
          {t('composer.hint')}
        </Text>
      </div>

      <TextArea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={t('composer.placeholder')}
        autoSize={{ minRows: 3, maxRows: 8 }}
        maxLength={500}
        showCount
        disabled={loading}
        onPressEnter={(e) => {
          if (e.ctrlKey || e.metaKey) handleSubmit();
        }}
      />

      <div className="agent-composer-actions">
        <Button
          type="primary"
          icon={<RocketOutlined />}
          loading={loading}
          disabled={!value.trim()}
          onClick={handleSubmit}
        >
          {loading ? t('composer.generating') : t('composer.submit')}
        </Button>
      </div>

      {error && <Alert type="error" showIcon message={error} className="agent-alert" />}

      {!loading && !error && (
        <div className="agent-examples">
          <Text type="secondary" className="agent-examples-label">
            {t('composer.examples')}
          </Text>
          <Space direction="vertical" className="agent-examples-list">
            {examples.map((ex) => (
              <Button
                key={ex}
                type="dashed"
                size="small"
                block
                onClick={() => setValue(ex)}
                className="agent-example-btn"
              >
                {ex}
              </Button>
            ))}
          </Space>
        </div>
      )}
    </div>
  );
}

export { QuestionComposer };
export type { QuestionComposerProps };
export { QuestionComposer as default };
