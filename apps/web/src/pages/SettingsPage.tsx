/**
 * Settings page — per-user LLM configuration (FRA-93).
 *
 * Single form: provider, API key, base URL, model, temperature.
 * The API key is encrypted server-side and never returned after being set.
 * Empty key field = keep existing key unchanged.
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, Button, Card, Form, Input, Select, Slider, Space, Spin, Typography, message } from 'antd';
import { SaveOutlined, LockOutlined } from '@ant-design/icons';

import { ApiError } from '@/api/client';
import { getLLMConfig, updateLLMConfig } from '@/api/settings';
import { SiderLayout } from '@/components/layout/SiderLayout';
import type { LLMConfigRead } from '@/types/api';

const { Title, Text } = Typography;

function SettingsPage() {
  const { t } = useTranslation('settings');
  const [messageApi, messageContext] = message.useMessage();
  const [form] = Form.useForm();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [config, setConfig] = useState<LLMConfigRead | null>(null);

  const loadConfig = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getLLMConfig();
      setConfig(res);
      form.setFieldsValue({
        provider: res.provider,
        base_url: res.base_url ?? '',
        model: res.model ?? '',
        temperature: res.temperature ?? 0.0,
      });
    } catch (err) {
      if (err instanceof ApiError) {
        messageApi.error(t('llm.loadFailed'));
      }
    } finally {
      setLoading(false);
    }
  }, [form, messageApi, t]);

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  const handleSave = async () => {
    try {
      const raw: unknown = await form.validateFields();
      const values = raw as {
        provider?: string;
        api_key?: string;
        base_url?: string;
        model?: string;
        temperature?: number;
      };
      const provider = values.provider ?? 'fixture';
      const baseUrl = values.base_url ?? '';
      const model = values.model ?? '';
      const temperature = typeof values.temperature === 'number' ? values.temperature : undefined;
      const apiKey = values.api_key ?? '';

      setSaving(true);
      const payload: Record<string, unknown> = {
        provider,
        base_url: baseUrl || null,
        model: model || null,
      };
      if (temperature !== undefined) {
        payload.temperature = temperature;
      }
      if (apiKey) {
        payload.api_key = apiKey;
      }
      const res = await updateLLMConfig(payload);
      setConfig(res);
      form.setFieldValue('api_key', '');
      messageApi.success(t('llm.saved'));
    } catch (err) {
      if (err instanceof ApiError) {
        messageApi.error(t('llm.saveFailed'));
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <SiderLayout sidebar={<div />}>
      <div className="page">
        {messageContext}
        <div className="page-header">
          <div>
            <Title level={2} className="page-title">
              {t('llm.title')}
            </Title>
            <Text type="secondary" className="page-description">
              {t('llm.description')}
            </Text>
          </div>
        </div>

        {loading ? (
          <div className="loading-block">
            <Spin>
              <div style={{ height: 48 }} />
            </Spin>
          </div>
        ) : (
          <Card className="settings-card" style={{ maxWidth: 640 }}>
            <Form form={form} layout="vertical" initialValues={{ provider: 'fixture', temperature: 0.0 }}>
              <Form.Item name="provider" label={t('llm.provider')}>
                <Select
                  options={[
                    { value: 'fixture', label: t('llm.providerFixture') },
                    { value: 'openai', label: t('llm.providerOpenai') },
                  ]}
                />
              </Form.Item>

              <Form.Item
                name="api_key"
                label={
                  <Space>
                    <LockOutlined />
                    {t('llm.apiKey')}
                  </Space>
                }
                extra={
                  <span>
                    {config?.has_api_key
                      ? t('llm.apiKeySet', { last4: config.api_key_last4 ?? '••••' })
                      : t('llm.apiKeyHint')}
                  </span>
                }
              >
                <Input.Password placeholder={t('llm.apiKeyPlaceholder')} autoComplete="off" />
              </Form.Item>

              <Form.Item name="base_url" label={t('llm.baseUrl')}>
                <Input placeholder="https://api.openai.com/v1" />
              </Form.Item>

              <Form.Item name="model" label={t('llm.model')}>
                <Input placeholder="gpt-4o-mini" />
              </Form.Item>

              <Form.Item name="temperature" label={t('llm.temperature')}>
                <Slider min={0} max={2} step={0.1} />
              </Form.Item>

              <Alert type="info" showIcon message={t('llm.securityNote')} style={{ marginBottom: 16 }} />

              <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={() => void handleSave()}>
                {saving ? t('llm.saving') : t('llm.save')}
              </Button>
            </Form>
          </Card>
        )}
      </div>
    </SiderLayout>
  );
}

export default SettingsPage;
