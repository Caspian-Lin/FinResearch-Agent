/**
 * Generic curve chart for backtest results (FRA-38).
 *
 * Wraps `echarts-for-react` with the loading / empty / error states shared by
 * the equity and drawdown views. The option is built by a pure builder passed
 * in (the `buildPriceChartOption` pattern, FRA-11/24); `key={language}` remounts
 * on language change so freshly-translated legend / axis / tooltip labels take
 * effect (echarts otherwise keeps the first option's strings).
 */
import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import ReactECharts from 'echarts-for-react';
import { Alert, Empty, Spin } from 'antd';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';

import type { EquityCurvePointRead } from '@/types/api';
import { useLanguage } from '@/i18n/useLanguage';
import { useResearchTheme, type ChartTheme } from '@/theme';

interface BacktestCurveChartProps {
  points: EquityCurvePointRead[];
  loading: boolean;
  /** Stable ApiError code (e.g. "notFound"); the backend detail is never shown. */
  errorCode: string | null;
  /** Pure builder: points + t → EChartsOption. */
  buildOption: (points: EquityCurvePointRead[], t: TFunction, theme: ChartTheme) => EChartsOption;
  /** i18n key for the empty-state description. */
  emptyKey: string;
  /** Chart height in px (loading placeholder matches so toggles don't jump). */
  height?: number;
}

export function BacktestCurveChart({
  points,
  loading,
  errorCode,
  buildOption,
  emptyKey,
  height = 360,
}: BacktestCurveChartProps) {
  const { t } = useTranslation();
  const { language } = useLanguage();
  const { palette } = useResearchTheme();

  const option = useMemo(
    () => buildOption(points, t, palette.chart),
    [points, t, buildOption, palette.chart],
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

  if (points.length === 0) {
    return <Empty description={t(emptyKey)} />;
  }

  return <ReactECharts key={language} option={option} style={{ height }} notMerge />;
}

export default BacktestCurveChart;
