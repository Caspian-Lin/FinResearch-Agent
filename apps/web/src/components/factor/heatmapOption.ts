/**
 * Sensitivity-heatmap chart option builder (FRA-58).
 *
 * Renders the FRA-54 sweep summary as a window × cost_bps grid of a chosen
 * metric (default net Sharpe). `metric_table` rows are `{params:{factor,window,
 * top_k/quantile,…}, cost_bps, net_sharpe, gross_sharpe, …}`; multiple rows at
 * the same (window, cost_bps) (e.g. different top_k) are averaged. The diverging
 * `HEATMAP_COLORS` scale (red→green) is colorblind-safe and the value is always
 * shown in the tooltip / a sibling table, so meaning never rests on color alone.
 */
import type { EChartsOption } from 'echarts';
import type { TFunction } from 'i18next';

import type { ChartTheme } from '@/theme';
import { DEFAULT_FACTOR_CHART_THEME, HEATMAP_COLORS } from './defaultChartTheme';

interface HeatmapCell {
  window: number;
  cost: number;
  value: number;
}

function extractCells(
  rows: Record<string, unknown>[],
  valueKey: string,
): HeatmapCell[] {
  const cells: HeatmapCell[] = [];
  for (const r of rows) {
    const params = (r.params ?? {}) as Record<string, unknown>;
    const window = Number(params.window);
    const cost = Number(r.cost_bps);
    const value = Number(r[valueKey]);
    if (Number.isFinite(window) && Number.isFinite(cost) && Number.isFinite(value)) {
      cells.push({ window, cost, value });
    }
  }
  return cells;
}

export function buildHeatmapOption(
  rows: Record<string, unknown>[],
  t: TFunction,
  theme: ChartTheme = DEFAULT_FACTOR_CHART_THEME,
  valueKey: string = 'net_sharpe',
): EChartsOption {
  const cells = extractCells(rows, valueKey);
  const windows = [...new Set(cells.map((c) => c.window))].sort((a, b) => a - b);
  const costs = [...new Set(cells.map((c) => c.cost))].sort((a, b) => a - b);

  // Aggregate (window, cost) → mean value (multiple top_k/factor rows collapse).
  const agg = new Map<string, { sum: number; n: number }>();
  for (const c of cells) {
    const key = `${c.window}|${c.cost}`;
    const e = agg.get(key) ?? { sum: 0, n: 0 };
    e.sum += c.value;
    e.n += 1;
    agg.set(key, e);
  }
  const winIdx = new Map(windows.map((w, i) => [w, i]));
  const costIdx = new Map(costs.map((c, i) => [c, i]));
  const heat = [...agg.entries()].map(([key, { sum, n }]) => {
    const [w, c] = key.split('|').map(Number);
    return [winIdx.get(w)!, costIdx.get(c)!, sum / n];
  });
  const values = heat.map((h) => h[2]);
  const vmin = values.length > 0 ? Math.min(...values) : 0;
  const vmax = values.length > 0 ? Math.max(...values) : 1;

  return {
    tooltip: {
      position: 'top',
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text },
      formatter: (params: unknown) => {
        // heatmap series points carry [xIdx, yIdx, value]; echarts' param type is
        // a broad union, so we narrow manually (value is always a 3-tuple here).
        const value = (params as { value: number[] }).value;
        const [wi, ci, v] = value;
        return `${t('factor:heatmap.window')}: ${windows[wi] ?? '—'}<br/>${t(
          'factor:heatmap.cost',
        )}: ${costs[ci] ?? '—'} bps<br/>${t(`factor:heatmap.metric.${valueKey}`) ?? valueKey}: ${
          Number.isFinite(v) ? v.toFixed(3) : '—'
        }`;
      },
    },
    grid: { left: 72, right: 24, top: 24, bottom: 40 },
    xAxis: {
      type: 'category',
      name: t('factor:heatmap.window'),
      nameLocation: 'middle',
      nameGap: 28,
      nameTextStyle: { color: theme.mutedText },
      data: windows.map((w) => String(w)),
      axisLabel: { color: theme.mutedText },
      axisLine: { lineStyle: { color: theme.axisLine } },
      splitArea: { show: true },
    },
    yAxis: {
      type: 'category',
      name: t('factor:heatmap.cost'),
      nameLocation: 'middle',
      nameGap: 52,
      nameTextStyle: { color: theme.mutedText },
      data: costs.map((c) => String(c)),
      axisLabel: { color: theme.mutedText },
      splitArea: { show: true },
    },
    visualMap: {
      min: vmin,
      max: vmax === vmin ? vmin + 1 : vmax,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      textStyle: { color: theme.mutedText },
      inRange: { color: HEATMAP_COLORS },
    },
    series: [
      {
        name: t(`factor:heatmap.metric.${valueKey}`) ?? valueKey,
        type: 'heatmap',
        data: heat,
        label: { show: false },
        emphasis: { itemStyle: { borderColor: theme.text, borderWidth: 1 } },
      },
    ],
  };
}
