/**
 * Generic ECharts wrapper for the factor research charts (FRA-58).
 *
 * Mirrors `BacktestCurveChart` (FRA-38): a pure `buildOption(data, t, theme)`
 * builder supplied by the caller, `key={language}` remount so translated
 * legend/axis/tooltip labels refresh (echarts otherwise keeps the first
 * option's strings), and shared loading / error / empty states. Generic in the
 * data type so the IC bar series, the quantile multi-line, and the sensitivity
 * heatmap all reuse one shell.
 */
import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import ReactECharts from 'echarts-for-react';
import { Alert, Empty, Spin } from 'antd';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';

import { useLanguage } from '@/i18n/useLanguage';
import { useResearchTheme, type ChartTheme } from '@/theme';

interface FactorChartProps<D> {
  data: D;
  loading: boolean;
  /** Stable ApiError code (e.g. "validation"); the backend detail is never shown. */
  errorCode: string | null;
  /** True when the computation succeeded but produced no plottable data. */
  isEmpty: boolean;
  /** Pure builder: data + t → EChartsOption. */
  buildOption: (data: D, t: TFunction, theme: ChartTheme) => EChartsOption;
  /** i18n key for the empty-state description. */
  emptyKey: string;
  /** Chart height in px (loading placeholder matches so toggles don't jump). */
  height?: number;
}

export function FactorChart<D>({
  data,
  loading,
  errorCode,
  isEmpty,
  buildOption,
  emptyKey,
  height = 360,
}: FactorChartProps<D>) {
  const { t } = useTranslation();
  const { language } = useLanguage();
  const { palette } = useResearchTheme();

  const option = useMemo(
    () => buildOption(data, t, palette.chart),
    [data, t, buildOption, palette.chart],
  );

  if (loading) {
    return (
      <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin tip={t('common:actions.loading')}>
          <div style={{ height: 48, width: 48 }} />
        </Spin>
      </div>
    );
  }

  if (errorCode) {
    return <Alert type="error" showIcon message={t(`errors:${errorCode}`)} />;
  }

  if (isEmpty) {
    return <Empty description={t(emptyKey)} />;
  }

  return <ReactECharts key={language} option={option} style={{ height }} notMerge />;
}

export default FactorChart;
