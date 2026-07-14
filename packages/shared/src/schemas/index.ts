import { z } from 'zod';

/**
 * zod 运行时校验 schema。
 *
 * 与 `../types` 中接口一一对应。优先使用 schema 推导出的类型
 * (`z.infer<typeof xxxSchema>`),以保证静态类型与运行时校验一致。
 */

export const assetTypeSchema = z.enum(['stock', 'etf', 'index']);

export const dataSourceSchema = z.enum([
  'yfinance',
  'polygon',
  'alpha_vantage',
  'stooq',
  'openbb',
]);

export const assetSchema = z.object({
  id: z.string().min(1),
  symbol: z.string().min(1),
  name: z.string(),
  type: assetTypeSchema,
  exchange: z.string(),
  sector: z.string().nullable().optional(),
  industry: z.string().nullable().optional(),
  created_at: z.string().datetime({ offset: true }),
});

export const ohlcvBarSchema = z.object({
  time: z.string().datetime({ offset: true }),
  asset_id: z.string().min(1),
  open: z.number().finite(),
  high: z.number().finite(),
  low: z.number().finite(),
  close: z.number().finite(),
  adjusted_close: z.number().finite(),
  volume: z.number().int().nonnegative(),
  source: dataSourceSchema,
});

export const watchlistSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  description: z.string().nullable().optional(),
  asset_ids: z.array(z.string().min(1)),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
});

const strategyTypeSchema = z.enum([
  'equal_weight',
  'inverse_volatility',
  'risk_parity',
  'momentum',
  'value',
  'mean_reversion',
  'custom',
]);

const agentValidationSchema = z.object({
  backtest: z.boolean(),
  benchmark: z.string().min(1),
  risk_checks: z.boolean(),
});

/** Agent 执行计划,对应项目描述文档第 10.2 节 */
export const agentPlanSchema = z
  .object({
    research_question: z.string().min(1),
    universe: z.array(z.string().min(1)).min(1),
    benchmark: z.string().min(1),
    start_date: z.string().min(1),
    end_date: z.string().min(1),
    factors: z.array(z.string()),
    strategy: z.object({
      type: strategyTypeSchema,
      params: z.record(z.string(), z.unknown()).optional(),
    }),
    validation: agentValidationSchema,
  })
  .refine(plan => plan.start_date <= plan.end_date, {
    message: 'start_date must be on or before end_date',
    path: ['end_date'],
  });

/** 从 schema 推导出的类型别名,便于消费方按需引用 */
export type AssetT = z.infer<typeof assetSchema>;
export type OhlcvBarT = z.infer<typeof ohlcvBarSchema>;
export type WatchlistT = z.infer<typeof watchlistSchema>;
export type AgentPlanT = z.infer<typeof agentPlanSchema>;

// ─── Week 5 agent contract (FRA-84)──────────────────────────────────────────
// 1:1 mirror of apps/api/app/schemas/agent.py. The canonical fixture at
// __fixtures__/research-plan.canonical.json is validated by BOTH this zod
// schema (apps/web vitest) and the Pydantic model (tests/test_agent_contracts.py)
// to prevent frontend/backend drift. Keep the allowlists and the superRefine
// rules byte-for-byte aligned with the Python model_validator.
//
// NOTE: `agentPlanSchema` above is the deprecated Week-1 placeholder; new code
// must use `researchPlanSchema`. It is kept only for the legacy `ResearchMemo`.

export const SCHEMA_VERSION = '1.0' as const;

/** Technical factor names — mirror FACTOR_REGISTRY. */
export const technicalFactorNamesSchema = z.enum([
  'momentum_21',
  'momentum_63',
  'momentum_126',
  'reversal_5',
  'reversal_21',
  'macd_hist',
  'rsi_14',
  'volatility_20d',
  'volatility_63d',
]);

/** Strategy template names — mirror the strategy registry. */
export const strategyNamesSchema = z.enum([
  'buy_hold',
  'equal_weight',
  'factor',
  'ma_crossover',
  'momentum',
  'reversal',
  'sentiment_tech',
]);

export const validationBaselineKindsSchema = z.enum([
  'buy_and_hold',
  'equal_weight',
  'benchmark',
]);

/** Invocable tool names — the Orchestrator rejects anything outside this set. */
export const knownToolNamesSchema = z.enum([
  'resolve_assets',
  'sync_ohlcv',
  'sync_news',
  'compute_factor',
  'evaluate_factor',
  'run_backtest',
  'run_comparison',
  'run_risk_checks',
  'cost_sensitivity_sweep',
  'generate_memo',
]);

export const agentRolesSchema = z.enum([
  'research_planner',
  'data_agent',
  'factor_agent',
  'backtest_agent',
  'risk_agent',
  'report_agent',
]);

export const priceFieldSchema = z.enum(['raw', 'adjusted']);
export const rebalanceFrequencySchema = z.enum(['daily', 'weekly', 'monthly']);
export const planResolutionSchema = z.enum(['draft', 'validated']);
export const factorKindSchema = z.enum(['technical', 'sentiment']);
export const toolRoleSchema = z.enum(['data', 'factor', 'backtest', 'risk', 'report']);
export const agentRunStatusSchema = z.enum([
  'draft',
  'validated',
  'queued',
  'running',
  'succeeded',
  'failed',
  'canceled',
]);
export const agentStepStatusSchema = z.enum([
  'queued',
  'running',
  'succeeded',
  'failed',
  'canceled',
]);

export const assetRefSchema = z.object({
  symbol: z.string().min(1).max(32),
  /** Resolved asset UUID; required once resolution='validated'. */
  asset_id: z.string().uuid().nullish(),
});

export const factorSpecSchema = z.object({
  name: z.string().min(1),
  kind: factorKindSchema.default('technical'),
  params: z.record(z.string(), z.unknown()).default({}),
});

export const sentimentProvenanceSchema = z.object({
  provider: z.string().nullish(),
  model_name: z.string().nullish(),
  prompt_version: z.string().nullish(),
  /** true defers provider/model/prompt resolution (draft only). */
  pending: z.boolean().default(false),
});

export const strategyConfigSchema = z.object({
  name: strategyNamesSchema,
  params: z.record(z.string(), z.unknown()).default({}),
  rebalance: rebalanceFrequencySchema,
});

export const validationConfigSchema = z.object({
  baselines: z.array(validationBaselineKindsSchema).min(1),
  metrics: z.array(z.string().min(1)).min(1),
  cost_sensitivity_bps: z.array(z.number().finite()).min(1),
});

export const riskChecksConfigSchema = z.object({
  enabled: z.boolean().default(true),
  transaction_cost_sensitivity: z.boolean().default(true),
  survivorship_documented: z.boolean().default(false),
  max_drawdown_warning: z.number().nullish(),
});

/**
 * Versioned, fully-bound research plan — the canonical Week-5 contract.
 * Field constraints + `superRefine` mirror the Pydantic `model_validator` in
 * `apps/api/app/schemas/agent.py`. Rejects empty universe, inverted dates,
 * missing benchmark/transaction-cost/baseline, unknown factor/strategy, and
 * unresolved symbols on a validated plan.
 */
export const researchPlanSchema = z
  .object({
    schema_version: z.literal(SCHEMA_VERSION).default(SCHEMA_VERSION),
    research_question: z.string().min(1),
    resolution: planResolutionSchema.default('draft'),
    universe: z.array(assetRefSchema).min(1),
    benchmark: assetRefSchema,
    data_source: dataSourceSchema,
    start_date: z.string().datetime({ offset: true }),
    end_date: z.string().datetime({ offset: true }),
    price_field: priceFieldSchema,
    factors: z.array(factorSpecSchema).default([]),
    sentiment_provenance: sentimentProvenanceSchema.nullish(),
    strategy: strategyConfigSchema,
    transaction_cost_bps: z.number().min(0),
    validation: validationConfigSchema,
    risk_checks: riskChecksConfigSchema.default({}),
    assumptions: z.array(z.string().min(1)).min(1),
    requested_outputs: z.array(z.string().min(1)).min(1),
  })
  .superRefine((plan, ctx) => {
    const techNames = technicalFactorNamesSchema.options as readonly string[];
    if (plan.start_date > plan.end_date) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['end_date'],
        message: 'start_date must be on or before end_date',
      });
    }
    if (plan.resolution === 'validated') {
      const missing: string[] = [];
      if (!plan.benchmark.asset_id) missing.push(`benchmark:${plan.benchmark.symbol}`);
      for (const ref of plan.universe) if (!ref.asset_id) missing.push(ref.symbol);
      if (missing.length) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['resolution'],
          message: 'validated plan has unresolved asset(s): ' + missing.join(', '),
        });
      }
    }
    let hasSentiment = false;
    plan.factors.forEach((f, i) => {
      if (f.kind === 'technical') {
        if (!techNames.includes(f.name)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ['factors', i, 'name'],
            message: `unknown technical factor '${f.name}'`,
          });
        }
      } else {
        hasSentiment = true;
        if (f.name !== 'sentiment') {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ['factors', i, 'name'],
            message: "sentiment factor must use canonical name 'sentiment'",
          });
        }
      }
    });
    if (hasSentiment) {
      const p = plan.sentiment_provenance;
      if (!p) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['sentiment_provenance'],
          message: 'plan uses a sentiment factor but declares no sentiment_provenance',
        });
      } else {
        const resolved = Boolean(p.provider && p.model_name && p.prompt_version);
        if (!resolved && !p.pending) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ['sentiment_provenance'],
            message: 'sentiment_provenance needs provider/model_name/prompt_version or pending=true',
          });
        }
        if (p.pending && plan.resolution === 'validated') {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ['sentiment_provenance'],
            message: 'validated plan may not keep sentiment_provenance pending',
          });
        }
      }
    }
  });

export const toolCallSchema = z.object({
  tool: knownToolNamesSchema,
  role: toolRoleSchema,
  status: agentStepStatusSchema.default('queued'),
  input: z.record(z.string(), z.unknown()).nullish(),
  output: z.record(z.string(), z.unknown()).nullish(),
  error: z.string().nullish(),
  started_at: z.string().datetime({ offset: true }).nullish(),
  finished_at: z.string().datetime({ offset: true }).nullish(),
});

export const agentStepSchema = z.object({
  name: z.string().min(1),
  agent_role: agentRolesSchema,
  status: agentStepStatusSchema.default('queued'),
  tool_calls: z.array(toolCallSchema).default([]),
  started_at: z.string().datetime({ offset: true }).nullish(),
  finished_at: z.string().datetime({ offset: true }).nullish(),
  error: z.string().nullish(),
});

export const agentRunSchema = z.object({
  status: agentRunStatusSchema.default('draft'),
  plan: researchPlanSchema,
  steps: z.array(agentStepSchema).default([]),
  created_at: z.string().datetime({ offset: true }).nullish(),
  updated_at: z.string().datetime({ offset: true }).nullish(),
  error: z.string().nullish(),
});

// ─── Allowlist sets & state machine (runtime constants) ─────────────────────

export const TECHNICAL_FACTOR_NAMES: ReadonlySet<string> = new Set(
  technicalFactorNamesSchema.options,
);
export const STRATEGY_NAMES: ReadonlySet<string> = new Set(strategyNamesSchema.options);
export const VALIDATION_BASELINE_KINDS: ReadonlySet<string> = new Set(
  validationBaselineKindsSchema.options,
);
export const KNOWN_TOOL_NAMES: ReadonlySet<string> = new Set(knownToolNamesSchema.options);
export const AGENT_ROLES: ReadonlySet<string> = new Set(agentRolesSchema.options);

export const TERMINAL_RUN_STATUSES: ReadonlySet<AgentRunStatusT> = new Set([
  'succeeded',
  'failed',
  'canceled',
]);

/** Legal AgentRun transitions; terminal states have no outgoing edge. */
export const RUN_TRANSITIONS: Readonly<Record<AgentRunStatusT, readonly AgentRunStatusT[]>> = {
  draft: ['validated', 'canceled'],
  validated: ['queued', 'canceled'],
  queued: ['running', 'canceled'],
  running: ['succeeded', 'failed', 'canceled'],
  succeeded: [],
  failed: [],
  canceled: [],
};

/** Legal AgentStep / ToolCall transitions. */
export const STEP_TRANSITIONS: Readonly<Record<AgentStepStatusT, readonly AgentStepStatusT[]>> = {
  queued: ['running', 'canceled'],
  running: ['succeeded', 'failed', 'canceled'],
  succeeded: [],
  failed: [],
  canceled: [],
};

export class IllegalStateTransitionError extends Error {
  constructor(current: string, target: string, kind: 'run' | 'step') {
    super(`illegal ${kind} transition '${current}' -> '${target}'`);
    this.name = 'IllegalStateTransitionError';
  }
}

export function assertRunTransition(
  current: AgentRunStatusT,
  target: AgentRunStatusT,
): void {
  if (!RUN_TRANSITIONS[current].includes(target)) {
    throw new IllegalStateTransitionError(current, target, 'run');
  }
}

export function assertStepTransition(
  current: AgentStepStatusT,
  target: AgentStepStatusT,
): void {
  if (!STEP_TRANSITIONS[current].includes(target)) {
    throw new IllegalStateTransitionError(current, target, 'step');
  }
}

// ─── Week 5 inferred type aliases ───────────────────────────────────────────

export type PriceFieldT = z.infer<typeof priceFieldSchema>;
export type RebalanceFrequencyT = z.infer<typeof rebalanceFrequencySchema>;
export type PlanResolutionT = z.infer<typeof planResolutionSchema>;
export type FactorKindT = z.infer<typeof factorKindSchema>;
export type ToolRoleT = z.infer<typeof toolRoleSchema>;
export type AgentRunStatusT = z.infer<typeof agentRunStatusSchema>;
export type AgentStepStatusT = z.infer<typeof agentStepStatusSchema>;
export type AssetRefT = z.infer<typeof assetRefSchema>;
export type FactorSpecT = z.infer<typeof factorSpecSchema>;
export type SentimentProvenanceT = z.infer<typeof sentimentProvenanceSchema>;
export type StrategyConfigT = z.infer<typeof strategyConfigSchema>;
export type ValidationConfigT = z.infer<typeof validationConfigSchema>;
export type RiskChecksConfigT = z.infer<typeof riskChecksConfigSchema>;
export type ResearchPlanT = z.infer<typeof researchPlanSchema>;
export type ToolCallT = z.infer<typeof toolCallSchema>;
export type AgentStepT = z.infer<typeof agentStepSchema>;
export type AgentRunT = z.infer<typeof agentRunSchema>;
