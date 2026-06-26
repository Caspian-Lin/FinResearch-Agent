import { describe, expect, it } from 'vitest';

import { FACTOR_NAMES, factorTypeOf } from '@/components/factor/factorMeta';

describe('factor metadata', () => {
  it('exposes macd_hist in the UI factor selector list', () => {
    expect(FACTOR_NAMES).toContain('macd_hist');
  });

  it('does not route macd_hist into the parameter sensitivity sweep', () => {
    expect(factorTypeOf('macd_hist')).toBeNull();
  });
});
