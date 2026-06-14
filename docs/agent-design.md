# LLM Agent Design

> Ref: `FinResearch_Agent_项目描述文件.md` §10 Agent 设计

## Agent Roles

| Agent | 职责 |
|---|---|
| Research Planner | 解析用户投研问题，生成结构化研究计划 |
| Data Agent | 选择数据源、股票池、时间范围，触发数据同步 |
| Factor Agent | 选择或构建技术指标、情绪指标、风险指标 |
| Backtest Agent | 配置回测参数并调用回测工具 |
| Risk Agent | 检查交易成本、回撤、过拟合、数据偏差 |
| Report Agent | 生成 research memo 和结论摘要 |

## Output Schema

```json
{
  "research_question": "Do AI semiconductor stocks show 6-month momentum?",
  "universe": ["NVDA", "AMD", "TSM", "AVGO", "ASML"],
  "benchmark": "QQQ",
  "start_date": "2022-01-01",
  "end_date": "2026-06-14",
  "factors": ["momentum_6m", "volatility_20d", "rsi_14"],
  "strategy": {
    "type": "cross_sectional_momentum",
    "rebalance_frequency": "monthly",
    "top_k": 2,
    "transaction_cost": 0.001
  },
  "validation": {
    "baseline": ["buy_and_hold", "equal_weight", "QQQ"],
    "metrics": ["annual_return", "sharpe", "max_drawdown", "turnover"]
  }
}
```

## Tool Catalog

<!-- TODO: enumerate tools each agent may call — e.g. sync_ohlcv(asset_ids, start, end), compute_factor(name, params), run_backtest(strategy_config), fetch_news(query, since), generate_memo(run_id). Specify tool signatures, allowed caller agents, and structured return schemas. Ref: 项目描述文件 §10 -->

## Safety Boundaries

1. Agent 不直接连接真实交易接口。
2. Agent 不输出“买入/卖出建议”作为确定性投资建议。
3. Agent 的策略代码必须通过模板或 sandbox 执行。
4. 所有报告必须包含风险提示和局限性。
5. 所有结论必须绑定数据区间、股票池和假设条件。

## Evaluation

<!-- TODO: define agent evaluation criteria — JSON schema conformance rate, tool-call validity, hypothesis coverage, citation of data windows/assumptions in memos, and regression prompts. Ref: 项目描述文件 §10 & §11.3 -->
