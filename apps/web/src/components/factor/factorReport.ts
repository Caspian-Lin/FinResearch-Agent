/**
 * Factor performance report builders (FRA-77).
 *
 * Pure helpers that aggregate the page's existing research results (IC /
 * quantile / sensitivity) + the current config form values into a one-page
 * factor performance report, exportable as JSON (reproducible snapshot) or
 * Markdown (human-readable). Split out of the panel component so the
 * arithmetic / formatting is unit-testable and the panel only renders.
 *
 * Fully client-side — no backend call. The report binds the *current*
 * `FactorConfigForm` values (universe size / source / window / factor / horizon
 * / n_quantiles / price_field / cost_bands) plus whichever research actions the
 * user has already run; any not-yet-run action renders as null / "not run".
 * The backend already returns `config_snapshot` on every response, but the page
 * holds the same fields as form values, so we reuse them here for a single
 * source of truth.
 *
 * No React import → satisfies react-refresh (keeps the panel file the only
 * component export). Markdown copy is injected via `FactorReportLabels` so the
 * builder stays i18n-agnostic and deterministic under test.
 */
import type { ICResult, QuantileResult, SensitivitySummary } from '@/types/api';

/** Config snapshot bound to the report — the current FactorConfigForm values. */
export interface FactorReportConfig {
  factor: string;
  source: string;
  start: string;
  end: string;
  /** Number of assets in the universe (asset UUIDs). */
  universeSize: number;
  priceField: string;
  nQuantiles: number;
  /** IC forward-return horizon (trading days). */
  horizon: number;
  /** Sensitivity cost bands in bps. */
  costBands: number[];
}

/** Inputs to the report builders: config + whichever results exist (null = not run). */
export interface FactorReportInput {
  config: FactorReportConfig | null;
  ic: ICResult | null;
  quantile: QuantileResult | null;
  sensitivity: SensitivitySummary | null;
}

/** Markdown copy injected by the panel from i18n (keeps the builder deterministic). */
export interface FactorReportLabels {
  title: string;
  configHeading: string;
  metricsHeading: string;
  limitationsHeading: string;

  // config field labels
  configFactor: string;
  configSource: string;
  configWindow: string;
  configUniverse: string;
  configHorizon: string;
  configNQuantiles: string;
  configPriceField: string;
  configCostBands: string;

  // section / metric labels
  icSummary: string;
  quantileHeading: string;
  sensitivityHeading: string;
  quantileMonotonicity: string;
  tmbEnding: string;
  bestSharpe: string;
  worstSharpe: string;
  highImpactParams: string;
  icMean: string;
  icIcir: string;
  icTStat: string;
  icPValue: string;
  icN: string;
  icPositiveRate: string;

  // value fallbacks
  notRun: string;
  none: string;

  /** Limitation bullets (research-only caveats), echoed from methodology. */
  limitations: string[];
  /** Closing disclaimer line (e.g. "Historical simulation — not investment advice."). */
  disclaimer: string;
}

/** Last value of the long−short spread series (cumulative ending NAV); null if none. */
export function topMinusBottomEndingValue(q: QuantileResult | null): number | null {
  if (!q || q.top_minus_bottom.length === 0) return null;
  return q.top_minus_bottom[q.top_minus_bottom.length - 1].value;
}

/** Sensitivity dimensions flagged high-impact by the sweep (empty if none / not run). */
export function highImpactParams(s: SensitivitySummary | null): string[] {
  if (!s) return [];
  return s.param_impacts.filter((p) => p.high_impact).map((p) => p.param);
}

/**
 * Build the reproducible JSON snapshot of the report.
 *
 * Mirrors the data the Markdown shows, as plain JSON for machine consumption /
 * archival. No copy / timestamps — purely the bound config + results, so two
 * exports of the same state produce byte-identical output.
 */
export function buildFactorReportJson(input: FactorReportInput): Record<string, unknown> {
  const { config, ic, quantile, sensitivity } = input;
  return {
    config: config ?? null,
    ic: ic ? { summary: ic.summary, periods: ic.series.length } : null,
    quantile: quantile
      ? {
          monotonicity: quantile.monotonicity,
          top_minus_bottom_ending_value: topMinusBottomEndingValue(quantile),
        }
      : null,
    sensitivity: sensitivity
      ? {
          best_net_sharpe: sensitivity.best_net_sharpe,
          worst_net_sharpe: sensitivity.worst_net_sharpe,
          highly_sensitive: sensitivity.highly_sensitive,
          high_impact_params: highImpactParams(sensitivity),
        }
      : null,
  };
}

/** Format a nullable number to a fixed precision, falling back when absent. */
function fmtNum(v: number | null | undefined, digits: number, fallback: string): string {
  if (v === null || v === undefined || Number.isNaN(v)) return fallback;
  return v.toFixed(digits);
}

/**
 * Build a human-readable Markdown report.
 *
 * Structure: title → config snapshot → metrics (IC / quantile / sensitivity) →
 * limitations → disclaimer. Absent results render a single "not run" line under
 * their heading instead of omitting it, so the report always shows what was and
 * wasn't computed.
 */
export function buildFactorReportMarkdown(input: FactorReportInput, labels: FactorReportLabels): string {
  const { config, ic, quantile, sensitivity } = input;
  const lines: string[] = [];

  lines.push(`# ${labels.title}`);
  lines.push('');

  // --- Config snapshot ---
  lines.push(`## ${labels.configHeading}`);
  if (config) {
    lines.push(`- **${labels.configFactor}**: ${config.factor}`);
    lines.push(`- **${labels.configSource}**: ${config.source}`);
    lines.push(`- **${labels.configWindow}**: ${config.start} → ${config.end}`);
    lines.push(`- **${labels.configUniverse}**: ${config.universeSize}`);
    lines.push(`- **${labels.configHorizon}**: ${config.horizon}`);
    lines.push(`- **${labels.configNQuantiles}**: ${config.nQuantiles}`);
    lines.push(`- **${labels.configPriceField}**: ${config.priceField}`);
    lines.push(`- **${labels.configCostBands}**: ${config.costBands.join(', ')}`);
  } else {
    lines.push(labels.notRun);
  }
  lines.push('');

  // --- Metrics ---
  lines.push(`## ${labels.metricsHeading}`);

  lines.push(`### ${labels.icSummary}`);
  if (ic) {
    const s = ic.summary;
    lines.push(`- ${labels.icMean}: ${fmtNum(s.mean, 4, labels.notRun)}`);
    lines.push(`- ${labels.icIcir}: ${fmtNum(s.icir, 4, labels.notRun)}`);
    lines.push(`- ${labels.icTStat}: ${fmtNum(s.t_stat, 3, labels.notRun)}`);
    lines.push(`- ${labels.icPValue}: ${fmtNum(s.p_value, 4, labels.notRun)}`);
    lines.push(`- ${labels.icN}: ${s.n}`);
    lines.push(`- ${labels.icPositiveRate}: ${fmtNum(s.positive_rate, 3, labels.notRun)}`);
  } else {
    lines.push(labels.notRun);
  }
  lines.push('');

  lines.push(`### ${labels.quantileHeading}`);
  if (quantile) {
    lines.push(`- ${labels.quantileMonotonicity}: ${fmtNum(quantile.monotonicity, 3, labels.notRun)}`);
    lines.push(`- ${labels.tmbEnding}: ${fmtNum(topMinusBottomEndingValue(quantile), 4, labels.notRun)}`);
  } else {
    lines.push(labels.notRun);
  }
  lines.push('');

  lines.push(`### ${labels.sensitivityHeading}`);
  if (sensitivity) {
    lines.push(`- ${labels.bestSharpe}: ${fmtNum(sensitivity.best_net_sharpe, 3, labels.notRun)}`);
    lines.push(`- ${labels.worstSharpe}: ${fmtNum(sensitivity.worst_net_sharpe, 3, labels.notRun)}`);
    const hi = highImpactParams(sensitivity);
    lines.push(`- ${labels.highImpactParams}: ${hi.length > 0 ? hi.join(', ') : labels.none}`);
  } else {
    lines.push(labels.notRun);
  }
  lines.push('');

  // --- Limitations ---
  lines.push(`## ${labels.limitationsHeading}`);
  for (const lim of labels.limitations) lines.push(`- ${lim}`);
  lines.push('');
  lines.push(`> ${labels.disclaimer}`);
  lines.push('');

  return lines.join('\n');
}

/**
 * Trigger a client-side download of `content` as `filename`.
 *
 * Uses a transient object URL + a synthetic `<a>` click, then revokes the URL.
 * Works in jsdom for tests (`URL.createObjectURL` / `document` are available).
 */
export function downloadText(filename: string, content: string, mime = 'text/plain'): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
