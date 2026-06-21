/**
 * Factor metadata shared by the config form and the page (FRA-58).
 *
 * Kept out of `FactorConfigForm.tsx` so that file exports only a component
 * (react-refresh / fast-refresh requirement). The factor list mirrors the
 * backend `FACTOR_REGISTRY` (FRA-55); the sensitivity factor-type allow-list
 * mirrors `ALLOWED_FACTOR_TYPES` (momentum / rsi / volatility — not reversal).
 */
import type { FactorPriceField } from '@/types/api';

/** Registered factor names (mirrors backend FACTOR_REGISTRY, FRA-55). */
export const FACTOR_NAMES = [
  'momentum_21',
  'momentum_63',
  'momentum_126',
  'reversal_5',
  'reversal_21',
  'rsi_14',
  'volatility_20d',
  'volatility_63d',
] as const;

/** Factor types supported by the sensitivity sweep (mirrors ALLOWED_FACTOR_TYPES). */
export const SENSITIVITY_FACTOR_TYPES = ['momentum', 'rsi', 'volatility'] as const;

/** Derive the sweep factor type from a factor name (null if unsupported, e.g. reversal). */
export function factorTypeOf(factorName: string): string | null {
  if (factorName.startsWith('momentum')) return 'momentum';
  if (factorName.startsWith('rsi')) return 'rsi';
  if (factorName.startsWith('volatility')) return 'volatility';
  return null;
}

/** Parsed form values handed from the config form to the page. */
export interface FactorFormValues {
  name: string;
  universe: string[];
  source: string;
  start: string;
  end: string;
  priceField: FactorPriceField;
  factor: string;
  nQuantiles: number;
}
