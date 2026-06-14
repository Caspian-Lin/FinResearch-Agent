/**
 * FinResearch Agent 共享业务类型。
 *
 * 这些类型是前后端共享的契约,定义在 zod schemas 之外供消费方在
 * 不依赖运行时校验时直接 import 使用。对于运行时校验,请使用
 * `../schemas` 中导出的 zod schema。
 */

/** 资产类型 */
export type AssetType = 'stock' | 'etf' | 'index';

/** 行情数据来源 */
export type DataSource = 'yfinance' | 'polygon' | 'alpha_vantage' | 'stooq' | 'openbb';

/** 资产元信息 */
export interface Asset {
  id: string;
  symbol: string;
  name: string;
  type: AssetType;
  exchange: string;
  sector?: string | null;
  industry?: string | null;
  created_at: string;
}

/** OHLCV 行情 bar,时间戳统一使用 ISO 8601 字符串 */
export interface OhlcvBar {
  time: string;
  asset_id: string;
  open: number;
  high: number;
  low: number;
  close: number;
  adjusted_close: number;
  volume: number;
  source: DataSource;
}

/** 观察列表 */
export interface Watchlist {
  id: string;
  name: string;
  description?: string | null;
  asset_ids: string[];
  created_at: string;
  updated_at: string;
}

/** 数据质量报告 */
export interface DataQualityReport {
  asset_id: string;
  source: DataSource;
  start_date: string;
  end_date: string;
  missing_days: number;
  duplicate_rows: number;
  null_close_rows: number;
  abnormal_return_days: number;
  generated_at: string;
}

/** 回测核心指标 */
export interface BacktestMetrics {
  annual_return: number;
  volatility: number;
  sharpe_ratio: number;
  max_drawdown: number;
  calmar_ratio: number;
  turnover: number;
  win_rate: number;
  beta: number;
  correlation: number;
}

/** 一次回测运行 */
export interface BacktestRun {
  id: string;
  strategy_type: string;
  params: Record<string, unknown>;
  benchmark: string;
  metrics: BacktestMetrics;
  created_at: string;
}

/** 投研备忘录中的章节 */
export interface ResearchMemoSection {
  heading: string;
  body: string;
}

/** 投研备忘录 */
export interface ResearchMemo {
  id: string;
  question: string;
  plan: AgentPlan;
  summary: string;
  sections: ResearchMemoSection[];
  limitations: string[];
  created_at: string;
}

/** 策略类型 (占位,后续按需扩展) */
export type StrategyType =
  | 'equal_weight'
  | 'inverse_volatility'
  | 'risk_parity'
  | 'momentum'
  | 'value'
  | 'mean_reversion'
  | 'custom';

/** Agent 验证配置 */
export interface AgentValidation {
  backtest: boolean;
  benchmark: string;
  risk_checks: boolean;
}

/** Agent 执行计划,对应项目描述文档第 10.2 节 */
export interface AgentPlan {
  research_question: string;
  universe: string[];
  benchmark: string;
  start_date: string;
  end_date: string;
  factors: string[];
  strategy: {
    type: StrategyType;
    params?: Record<string, unknown>;
  };
  validation: AgentValidation;
}
