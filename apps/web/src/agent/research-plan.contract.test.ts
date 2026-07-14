/**
 * Frontend side of the FRA-84 contract gate.
 *
 * The same canonical fixture that the backend validates via Pydantic
 * (`tests/test_agent_contracts.py`) is validated here via the Zod mirror in
 * `@finresearch/shared`. Both sides must agree on field names and enum
 * semantics — this test fails the moment they drift.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import {
  assertRunTransition,
  assertStepTransition,
  IllegalStateTransitionError,
  researchPlanSchema,
  SCHEMA_VERSION,
} from '@finresearch/shared';

// vitest runs with cwd = apps/web; resolve up to the repo root then into shared.
const fixturePath = resolve(
  process.cwd(),
  '..',
  '..',
  'packages',
  'shared',
  'src',
  '__fixtures__',
  'research-plan.canonical.json',
);
const canonicalPlan = JSON.parse(readFileSync(fixturePath, 'utf-8')) as unknown;

function validPlan(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    schema_version: SCHEMA_VERSION,
    research_question: 'Do AI semis show 6m momentum vs QQQ?',
    resolution: 'validated',
    universe: [{ symbol: 'NVDA', asset_id: '11111111-1111-4111-8111-111111111111' }],
    benchmark: { symbol: 'QQQ', asset_id: '66666666-6666-4666-8666-666666666666' },
    data_source: 'yfinance',
    start_date: '2022-01-01T00:00:00Z',
    end_date: '2026-06-14T00:00:00Z',
    price_field: 'adjusted',
    factors: [{ name: 'momentum_63', kind: 'technical' }],
    strategy: { name: 'momentum', params: { lookback: 63, top_k: 2 }, rebalance: 'monthly' },
    transaction_cost_bps: 10.0,
    validation: {
      baselines: ['buy_and_hold', 'equal_weight', 'benchmark'],
      metrics: ['annual_return', 'sharpe', 'max_drawdown', 'turnover'],
      cost_sensitivity_bps: [0.0, 5.0, 10.0, 25.0],
    },
    assumptions: ['Universe is survivorship-biased.'],
    requested_outputs: ['research_memo'],
    ...overrides,
  };
}

const rejects = (plan: Record<string, unknown>): void => {
  const res = researchPlanSchema.safeParse(plan);
  expect(res.success).toBe(false);
};

describe('ResearchPlan contract (frontend Zod mirror)', () => {
  it('validates the shared canonical fixture', () => {
    const res = researchPlanSchema.safeParse(canonicalPlan);
    expect(res.success).toBe(true);
    if (res.success) {
      expect(res.data.universe).toHaveLength(5);
      expect(res.data.sentiment_provenance?.model_name).toBe('fixture-rule');
    }
  });

  it('validates a minimal plan and applies defaults', () => {
    const res = researchPlanSchema.safeParse(validPlan());
    expect(res.success).toBe(true);
  });

  it('rejects an empty universe', () => rejects({ ...validPlan(), universe: [] }));

  it('rejects inverted dates', () =>
    rejects({ ...validPlan(), start_date: '2027-01-01T00:00:00Z' }));

  it('rejects a missing transaction cost', () => {
    const p = validPlan();
    delete p.transaction_cost_bps;
    rejects(p);
  });

  it('rejects empty validation baselines', () => {
    rejects({ ...validPlan(), validation: { baselines: [], metrics: ['x'], cost_sensitivity_bps: [0] } });
  });

  it('rejects an unknown technical factor', () =>
    rejects({ ...validPlan(), factors: [{ name: 'momentum_999', kind: 'technical' }] }));

  it('rejects an unknown strategy', () =>
    rejects({ ...validPlan(), strategy: { name: 'lstm', params: {}, rebalance: 'monthly' } }));

  it('rejects a sentiment factor without provenance', () =>
    rejects({ ...validPlan(), factors: [{ name: 'sentiment', kind: 'sentiment' }] }));

  it('rejects a validated plan with an unresolved asset', () => {
    rejects({ ...validPlan(), universe: [{ symbol: 'NVDA' }] });
  });

  it('rejects an unknown schema version', () =>
    rejects({ ...validPlan(), schema_version: '0.9' }));

  it('allows a draft plan with unresolved assets', () => {
    const p = validPlan({ resolution: 'draft', universe: [{ symbol: 'NVDA' }], benchmark: { symbol: 'QQQ' } });
    expect(researchPlanSchema.safeParse(p).success).toBe(true);
  });
});

describe('Agent state machine (frontend mirror)', () => {
  it('allows the canonical happy path', () => {
    expect(() => {
      assertRunTransition('draft', 'validated');
      assertRunTransition('validated', 'queued');
      assertRunTransition('queued', 'running');
      assertRunTransition('running', 'succeeded');
    }).not.toThrow();
  });

  it('rejects skipping states', () => {
    expect(() => assertRunTransition('draft', 'running')).toThrow(IllegalStateTransitionError);
  });

  it('makes terminal run states immutable', () => {
    for (const terminal of ['succeeded', 'failed', 'canceled'] as const) {
      expect(() => assertRunTransition(terminal, 'running')).toThrow(IllegalStateTransitionError);
    }
  });

  it('makes terminal step states immutable', () => {
    for (const terminal of ['succeeded', 'failed', 'canceled'] as const) {
      expect(() => assertStepTransition(terminal, 'running')).toThrow(IllegalStateTransitionError);
    }
  });
});
