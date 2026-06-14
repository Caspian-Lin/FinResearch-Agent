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
