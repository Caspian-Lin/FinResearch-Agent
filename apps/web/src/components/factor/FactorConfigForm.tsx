/**
 * Factor research configuration form (FRA-58).
 *
 * Picks a watchlist (universe = all of its assets), a registered factor, a date
 * window, the price field, source, and the quantile count; on submit it emits a
 * parsed `FactorFormValues` (start/end as `YYYY-MM-DD`) the page turns into an
 * IC / quantile / sensitivity request. Mirrors `BacktestConfigForm` (FRA-38):
 * ToggleSelect for watchlist + enumerated fields, antd RangePicker for dates.
 *
 * The factor list mirrors the backend `FACTOR_REGISTRY` (FRA-55). Sensitivity
 * supports the factor *types* momentum/rsi/volatility (not reversal/MACD); the page
 * derives the type from the chosen factor name and disables the sweep action for
 * unsupported factors.
 */
import { Button, Col, DatePicker, Form, Input, InputNumber, Row, Select, Space, Typography } from 'antd';
import { useTranslation } from 'react-i18next';
import type { Dayjs } from 'dayjs';
import dayjs from 'dayjs';

import { ToggleSelect } from '@/components/ui/ToggleSelect';
import { FACTOR_NAMES, type FactorFormValues } from './factorMeta';
import type { FactorPriceField, WatchlistRead } from '@/types/api';

const { RangePicker } = DatePicker;
const { Text } = Typography;

interface RawFormValues {
  name: string;
  watchlistId: string;
  factor: string;
  range: [Dayjs, Dayjs];
  source: string;
  nQuantiles: number;
  priceField: FactorPriceField;
}

interface FactorConfigFormProps {
  watchlists: WatchlistRead[];
  submitting: boolean;
  onSubmit: (values: FactorFormValues) => void;
}

export function FactorConfigForm({ watchlists, submitting, onSubmit }: FactorConfigFormProps) {
  const { t } = useTranslation();
  const [form] = Form.useForm<RawFormValues>();

  const watchlistOptions = watchlists.map((w) => ({
    value: w.watchlist_id,
    label: `${w.name} (${w.items.length})`,
  }));

  const handleFinish = (values: RawFormValues) => {
    const wl = watchlists.find((w) => w.watchlist_id === values.watchlistId);
    const universe = wl ? wl.items.map((it) => it.asset_id) : [];
    onSubmit({
      name: values.name,
      universe,
      source: values.source,
      start: values.range[0].format('YYYY-MM-DD'),
      end: values.range[1].format('YYYY-MM-DD'),
      priceField: values.priceField,
      factor: values.factor,
      nQuantiles: values.nQuantiles,
    });
  };

  return (
    <Form<RawFormValues>
      form={form}
      layout="vertical"
      initialValues={{
        factor: 'momentum_21',
        source: 'yfinance',
        nQuantiles: 5,
        priceField: 'adjusted',
        range: [dayjs().subtract(1, 'year'), dayjs()],
      }}
      onFinish={(v) => handleFinish(v)}
    >
      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Form.Item
            name="watchlistId"
            label={t('factor:form.watchlist')}
            rules={[{ required: true, message: t('errors:validation') }]}
          >
            <ToggleSelect
              options={watchlistOptions}
              placeholder={t('factor:form.watchlistPlaceholder')}
              width="100%"
            />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item
            name="factor"
            label={t('factor:form.factor')}
            rules={[{ required: true, message: t('errors:validation') }]}
          >
            <Select
              options={FACTOR_NAMES.map((f) => ({ value: f, label: t(`factor:factors.${f}`) }))}
            />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Form.Item
            name="range"
            label={t('factor:form.dateRange')}
            rules={[{ required: true, message: t('errors:validation') }]}
          >
            <RangePicker allowClear={false} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col xs={12} md={4}>
          <Form.Item name="nQuantiles" label={t('factor:form.nQuantiles')}>
            <InputNumber min={1} max={20} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col xs={12} md={4}>
          <Form.Item name="source" label={t('factor:form.source')}>
            <Input />
          </Form.Item>
        </Col>
        <Col xs={12} md={4}>
          <Form.Item name="priceField" label={t('factor:form.priceField')}>
            <ToggleSelect
              options={(['adjusted', 'raw'] as FactorPriceField[]).map((p) => ({
                value: p,
                label: t(`factor:priceField.${p}`),
              }))}
              width="100%"
            />
          </Form.Item>
        </Col>
      </Row>

      <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
        <Text type="secondary">{t('factor:form.hint')}</Text>
        <Button type="primary" htmlType="submit" loading={submitting}>
          {t('factor:form.run')}
        </Button>
      </Space>
    </Form>
  );
}

export default FactorConfigForm;
