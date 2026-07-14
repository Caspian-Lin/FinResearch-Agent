/**
 * Default `ChartTheme` fallback for the factor option builders (FRA-58).
 *
 * The live theme comes from `useResearchTheme().palette.chart` at render time;
 * this constant only backs the builders' default parameter so pure-function
 * unit tests can call them with `(data, t)` and still get a sane, non-empty
 * palette. Mirrors the `DEFAULT_CHART_THEME` in `backtest/equityChartOption.ts`.
 */
import type { ChartTheme } from '@/theme';

export const DEFAULT_FACTOR_CHART_THEME: ChartTheme = {
  text: '#252833',
  mutedText: '#667085',
  gridLine: '#e7e9ef',
  axisLine: '#c9ced8',
  surface: '#ffffff',
  tooltipBg: 'rgba(255, 255, 255, 0.98)',
  tooltipBorder: '#d9dee8',
  primary: '#b85033',
  primarySoft: 'rgba(184, 80, 51, 0.16)',
  quality: '#16877d',
  warning: '#b27a00',
  danger: '#c94135',
  ma5: '#b98500',
  ma20: '#7357b8',
  volume: 'rgba(22, 135, 125, 0.34)',
};

/**
 * Colorblind-safe discrete palette (Okabe–Ito) for quantile curves — distinguishable
 * for deuteranopia/protanopia/tritanopia (PRODUCT.md / WCAG color-not-alone rule).
 * Ordered low→high so quantile 1 (lowest factor value) starts at index 0.
 */
export const QUANTILE_PALETTE = [
  '#0072b2',
  '#56b4e9',
  '#009e73',
  '#e69f00',
  '#d55e00',
  '#cc79a7',
  '#756bb1',
  '#999999',
];

/**
 * Diverging color scale (red→amber→green) for the sensitivity heatmap value
 * (net Sharpe). Colorblind-safe and encodes sign (negative = red). Pairs with a
 * textual value tooltip so meaning never rests on color alone (WCAG).
 */
export const HEATMAP_COLORS = ['#c94135', '#e69f00', '#f0e442', '#16877d'];
