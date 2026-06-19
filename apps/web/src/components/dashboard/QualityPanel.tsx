/**
 * Data-quality panel (FRA-11).
 *
 * Surfaces a QualityReport: coverage (Progress), expected/observed/missing
 * session counts, the list of missing session dates (truncated past 20), and
 * detected anomalies (rule name translated, detail shown verbatim).
 *
 * Numbers and dates are locale-formatted at the view layer. Anomaly `rule` is
 * mapped through i18n (`dashboard:quality.rules.<rule>`); `detail` is backend
 * freeform text shown untranslated.
 */
import { Alert, Empty, Progress, Spin, Typography } from 'antd';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';

import type { QualityReport } from '@/types/api';
import { useLanguage } from '@/i18n/useLanguage';

/** Show at most this many missing-session dates; collapse the rest. */
const MISSING_PREVIEW = 20;

const { Title, Text } = Typography;

interface QualityPanelProps {
  report: QualityReport | null;
  loading: boolean;
  /** Stable ApiError code; backend detail is never shown. */
  errorCode: string | null;
}

export function QualityPanel({ report, loading, errorCode }: QualityPanelProps) {
  const { t } = useTranslation();
  const { language } = useLanguage();

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 24 }}>
        <Spin tip={t('dashboard:loading')}>
          <div style={{ height: 48 }} />
        </Spin>
      </div>
    );
  }

  if (errorCode) {
    return <Alert type="error" showIcon message={t(`errors:${errorCode}`)} />;
  }

  if (!report) {
    return <Empty />;
  }

  const lang = language === 'zh-CN' ? 'zh-CN' : 'en-US';
  const coveragePct = report.coverage * 100;
  const coverageLabel = `${coveragePct.toLocaleString(lang, { maximumFractionDigits: 1 })}%`;

  const missingPreview = report.missing_sessions.slice(0, MISSING_PREVIEW);
  const missingHidden = Math.max(0, report.missing_sessions.length - MISSING_PREVIEW);

  return (
    <div>
      <Title level={5} style={{ marginTop: 0 }}>
        {t('dashboard:quality.title')}
      </Title>

      <div style={{ marginBottom: 8 }}>
        <Text type="secondary">{t('dashboard:quality.coverage')}: </Text>
        <Text strong>{coverageLabel}</Text>
      </div>
      <Progress percent={Math.round(coveragePct)} status="active" style={{ marginBottom: 16 }} />

      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', marginBottom: 16 }}>
        <div>
          <Text type="secondary">{t('dashboard:quality.expected')}: </Text>
          <Text strong>{report.expected_sessions.toLocaleString(lang)}</Text>
        </div>
        <div>
          <Text type="secondary">{t('dashboard:quality.observed')}: </Text>
          <Text strong>{report.observed_sessions.toLocaleString(lang)}</Text>
        </div>
      </div>

      <Title level={5}>{t('dashboard:quality.missing.title')}</Title>
      {report.missing_sessions.length === 0 ? (
        <Text type="secondary">0</Text>
      ) : (
        <div style={{ marginBottom: 16 }}>
          {missingPreview.map((iso) => (
            <div key={iso}>{dayjs(iso).format('LL')}</div>
          ))}
          {missingHidden > 0 && (
            <Text type="secondary">{t('dashboard:quality.missing.more', { count: missingHidden })}</Text>
          )}
        </div>
      )}

      <Title level={5}>
        {t('dashboard:quality.anomalies.title')}
        {report.anomalies.length > 0 && (
          <Text type="secondary" style={{ fontWeight: 'normal', marginLeft: 8 }}>
            {t('dashboard:quality.anomalies.count', { count: report.anomalies.length })}
          </Text>
        )}
      </Title>
      {report.anomalies.length === 0 ? (
        <Text type="secondary">{t('dashboard:quality.anomalies.empty')}</Text>
      ) : (
        <ul style={{ paddingLeft: 20, margin: 0 }}>
          {report.anomalies.map((a, idx) => (
            <li key={`${a.time}-${idx}`}>
              <Text>{dayjs(a.time).format('LL')}</Text>
              {' · '}
              <Text strong>{t(`dashboard:quality.rules.${a.rule}`)}</Text>
              {a.detail ? (
                <>
                  {' · '}
                  <Text type="secondary">{a.detail}</Text>
                </>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default QualityPanel;
