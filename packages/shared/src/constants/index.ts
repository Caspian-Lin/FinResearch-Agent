import type { AssetType, DataSource } from '../types';

/** API 版本,用于所有 `/api/v1/...` 路由前缀 */
export const API_VERSION = 'v1' as const;

/** 默认回测基准 */
export const DEFAULT_BENCHMARKS = ['QQQ', 'SPY'] as const;

/** 全部支持的资产类型 (常量数组,便于 UI 下拉等场景遍历) */
export const ASSET_TYPES: readonly AssetType[] = ['stock', 'etf', 'index'] as const;

/** 全部支持的数据源 */
export const DATA_SOURCES: readonly DataSource[] = [
  'yfinance',
  'polygon',
  'alpha_vantage',
  'stooq',
  'openbb',
] as const;

/** BullMQ 任务队列名 */
export const QUEUES = {
  default: 'default',
  data: 'data_sync',
  backtest: 'backtest',
} as const;

/** 年化无风险利率,用于 Sharpe ratio 计算 (与 10 年美债近似) */
export const RISK_FREE_RATE = 0.045;

/** 每年交易日数,用于年化波动率/收益等计算 */
export const TRADING_DAYS_PER_YEAR = 252;
