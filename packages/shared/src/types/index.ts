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

// ─── Factor research(Week 3,FRA-47)──────────────────────────────────────────
// 与后端 app/services/factors 契约一一对应;详见 docs/factor-research-methodology.md(FRA-59)。

/** 时序点(time + value),承载 IC series / 分层净值等时间序列结果 */
export interface TimeSeriesPoint {
  /** ISO 8601,UTC 午夜 */
  time: string;
  value: number;
}

/** 因子值,对齐后端 FactorValue(FRA-47)与 factor_values 表(FRA-48) */
export interface FactorValue {
  asset_id: string;
  /** 因子名,编码参数,如 momentum_21 / rsi_14 / volatility_20d */
  factor_name: string;
  /** ISO 8601,UTC 午夜 */
  time: string;
  value: number;
  /** 参数快照,保证可复现(§11.3 第 6 条) */
  params: Record<string, unknown>;
  source: string;
}

/** IC(信息系数)统计汇总,对齐后端 ICSummary(FRA-47 / FRA-52) */
export interface ICSummary {
  mean: number;
  icir: number;
  t_stat: number;
  p_value: number;
  n: number;
  positive_rate: number;
}

/** IC 评估结果:逐期 IC 序列 + 汇总,对齐后端 ICResult */
export interface ICResult {
  series: TimeSeriesPoint[];
  summary: ICSummary;
}

/** 分层(quantile)回测结果,对齐后端 QuantileResult(FRA-47 / FRA-53) */
export interface QuantileResult {
  /** key = 分层标签(1..N,1 = 因子值最低),value = 该层净值时序 */
  quantile_equity: Record<string, TimeSeriesPoint[]>;
  /** long top − short bottom 多空组合净值时序 */
  top_minus_bottom: TimeSeriesPoint[];
  /** 层平均收益随层序的单调性(如 Spearman 相关) */
  monotonicity: number;
}

/** 单个资产在某日横截面因子排名快照中的行(FRA-76) */
export interface FactorRankingSnapshotItem {
  asset_id: string;
  symbol: string;
  factor_value: number;
  rank_pct: number;
  z_score: number | null;
  quantile_bucket: number;
}

/** 某一决策日的横截面因子排名快照(FRA-76) */
export interface FactorRankingSnapshot {
  factor_name: string;
  source: string;
  /** ISO 8601,UTC 午夜;无有效横截面时为 null */
  snapshot_time: string | null;
  requested_date: string | null;
  n_quantiles: number;
  items: FactorRankingSnapshotItem[];
  total: number;
  config_snapshot: Record<string, unknown>;
}
