# Backtesting & Risk Methodology

> Ref: `FinResearch_Agent_项目描述文件.md` §11 回测与评估设计

## Baseline Strategies

| 策略 | 用途 |
|---|---|
| Buy and Hold | 最基础基准 |
| Equal Weight Portfolio | 主题股票池等权组合 |
| Moving Average Crossover | 技术分析 baseline |
| Momentum Strategy | 因子研究 baseline |
| Reversal Strategy | 对照实验 |
| QQQ/SPY Benchmark | 市场基准 |

## Core Metrics

| 指标 | 说明 |
|---|---|
| Annual Return | 年化收益 |
| Volatility | 年化波动率 |
| Sharpe Ratio | 风险调整收益 |
| Max Drawdown | 最大回撤 |
| Calmar Ratio | 收益与回撤关系 |
| Turnover | 换手率 |
| Win Rate | 胜率 |
| Beta | 相对 benchmark 的市场暴露 |
| Correlation | 与 benchmark 的相关性 |
| Transaction Cost Sensitivity | 交易成本敏感性 |

## Anti-Cheat Rules

1. 禁止 look-ahead bias：所有因子只能使用当时可见数据。
2. 避免 survivorship bias：若无法完全处理，需要在报告中说明。
3. 使用时间切分验证，避免随机切分金融时间序列。
4. 每个策略必须与 baseline 比较。
5. 必须展示交易成本前后表现。
6. 必须记录每次回测参数，保证可复现。

## Sensitivity Analysis

<!-- TODO: describe parameter sweeps over lookback window, rebalance frequency, top-k, transaction cost bands; how results are summarized (heatmap, distribution) and persisted into backtest_metrics. Ref: 项目描述文件 §11.3 -->

## Limitations

<!-- TODO: enumerate backtest limitations — survivorship bias, look-ahead bias mitigations, transaction cost model simplifications, regime dependence, sample size caveats. Ref: 项目描述文件 §11.3 & §4 非目标范围 -->
