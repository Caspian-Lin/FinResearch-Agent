# LLM Agent Design

> Ref: `FinResearch_Agent_项目描述文件.md` §10 Agent 设计
>
> 本文档定义 Week 5 研究代理的**版本化契约**(FRA-84):`ResearchPlan` schema、
> 工具目录、Agent Run / Step / Tool Call 状态机,以及安全边界与评估准则。代码
> 真相位于 [`apps/api/app/schemas/agent.py`](../apps/api/app/schemas/agent.py)
> (Pydantic v2)与 [`packages/shared/src/schemas/index.ts`](../packages/shared/src/schemas/index.ts)
> (Zod),二者 1:1 对齐,并由共享 fixture
> [`packages/shared/src/__fixtures__/research-plan.canonical.json`](../packages/shared/src/__fixtures__/research-plan.canonical.json)
> 双向校验防漂移。

## Agent Roles

| Agent | 职责 |
|---|---|
| Research Planner | 解析用户投研问题,生成结构化、版本化的 `ResearchPlan` |
| Data Agent | 解析 symbol→asset_id、同步 OHLCV / 新闻,锁定数据窗口与来源 |
| Factor Agent | 选择 / 构建技术因子与文本情绪因子(白名单内) |
| Backtest Agent | 配置策略模板并调用回测 / 对照工具 |
| Risk Agent | 检查交易成本、回撤、过拟合、数据偏差,做成本敏感性扫描 |
| Report Agent | 组装 research memo(摘要 + 章节 + 风险提示 + 局限性) |

## Versioned ResearchPlan Contract

`ResearchPlan` 是所有 Week 5 Agent 共用的唯一结构化契约。它通过 `schema_version`
锁定字段语义;未知版本一律拒绝。完整字段与校验规则见 `agent.py` 的
`ResearchPlan._validate_invariants`,要点(对应 FRA-84 验收标准):

| 字段 | 约束 |
|---|---|
| `schema_version` | 必须等于 `SCHEMA_VERSION`(当前 `"1.0"`);破坏性变更须 bump |
| `research_question` | 非空 |
| `resolution` | `draft` \| `validated`;`validated` 要求所有 `AssetRef.asset_id` 已解析 |
| `universe` | 非空;每个成员区分 `symbol`(用户输入)与 `asset_id`(解析后 UUID) |
| `benchmark` | 必填;`validated` 时必须有 `asset_id` —— 禁止用自由文本绕过资产解析 |
| `data_source` / `price_field` | 白名单枚举(对齐 `DataSource` / `PriceField`) |
| `start_date` / `end_date` | 必须有序,`start_date <= end_date`;锁定数据窗口 |
| `factors` | `technical` 因子必须在 `TECHNICAL_FACTOR_NAMES` 白名单;`sentiment` 因子名固定为 `sentiment` |
| `sentiment_provenance` | 使用任一 sentiment 因子时必须声明 `provider`/`model_name`/`prompt_version`,或显式 `pending=true`(仅 `draft`) |
| `strategy` | `name` 必须在 `STRATEGY_NAMES` 白名单;`rebalance` / `params` 显式 |
| `transaction_cost_bps` | **显式必填**(`>= 0`;声明 0 合法,缺字段被拒) |
| `validation.baselines` | 非空;每项 ∈ `{buy_and_hold, equal_weight, benchmark}` |
| `validation.cost_sensitivity_bps` | 非空;成本敏感性是强制项 |
| `risk_checks.transaction_cost_sensitivity` | 默认 true(回测方法学要求) |
| `assumptions` / `requested_outputs` | 非空;所有结论必须绑定到这些假设与输出 |

说明性示例(完整 canonical 样例见上述 fixture):

```json
{
  "schema_version": "1.0",
  "research_question": "Do AI semiconductor stocks show 6-month momentum vs QQQ?",
  "resolution": "validated",
  "universe": [{ "symbol": "NVDA", "asset_id": "11111111-1111-4111-8111-111111111111" }],
  "benchmark": { "symbol": "QQQ", "asset_id": "66666666-6666-4666-8666-666666666666" },
  "data_source": "yfinance",
  "start_date": "2022-01-01T00:00:00Z",
  "end_date": "2026-06-14T00:00:00Z",
  "price_field": "adjusted",
  "factors": [{ "name": "momentum_63", "kind": "technical" }],
  "strategy": { "name": "momentum", "params": { "lookback": 63, "top_k": 2 }, "rebalance": "monthly" },
  "transaction_cost_bps": 10.0,
  "validation": {
    "baselines": ["buy_and_hold", "equal_weight", "benchmark"],
    "metrics": ["annual_return", "sharpe", "max_drawdown", "turnover"],
    "cost_sensitivity_bps": [0.0, 5.0, 10.0, 25.0]
  },
  "assumptions": ["Universe is survivorship-biased (current constituents only)."],
  "requested_outputs": ["research_memo", "equity_curve", "ic_table"]
}
```

## Tool Catalog

工具目录是 Agent **唯一可调用工具的白名单**(`KNOWN_TOOL_NAMES` / `TOOL_CATALOG`)。
Orchestrator 拒绝任何不在目录中的工具调用。每个工具声明:所属角色、允许的调用方、
输入 / 输出 schema 引用、是否产生副作用(DB 写或外部调用)、是否幂等、超时。
覆盖 Data / Factor / Backtest / Risk / Report 五类角色。

### Data(role = data)

| 工具 | 调用方 | 输入 → 输出 | 副作用 | 幂等 | 超时 |
|---|---|---|---|---|---|
| `resolve_assets` | research_planner, data_agent | `list[str]` → `list[AssetRef]` | 否(只读 `assets`) | 是 | 30s |
| `sync_ohlcv` | data_agent | `SyncRequest` → `SyncResponse` | 是(写 `ohlcv` + 拉外部源) | 是(ON CONFLICT upsert) | 600s |
| `sync_news` | data_agent | `NewsSyncRequest` → `NewsSyncResponse` | 是(写 `news_items`) | 是(ON CONFLICT upsert) | 600s |

### Factor(role = factor)

| 工具 | 调用方 | 输入 → 输出 | 副作用 | 幂等 | 超时 |
|---|---|---|---|---|---|
| `compute_factor` | factor_agent | `FactorComputeRequest` → `FactorComputeResponse` | 是(写 `factor_values`) | 是 | 600s |
| `evaluate_factor` | factor_agent, risk_agent | `QuantileBacktestRequest` → `ICResponse \| QuantileBacktestResponse` | 否(只读计算) | 是 | 300s |

### Backtest(role = backtest)

| 工具 | 调用方 | 输入 → 输出 | 副作用 | 幂等 | 超时 |
|---|---|---|---|---|---|
| `run_backtest` | backtest_agent | `BacktestCreateRequest` → `BacktestEnqueueResponse` | 是(写 `BacktestRun` + 入队) | 否(每次新建 run) | 900s |
| `run_comparison` | backtest_agent | `ComparisonCreateRequest` → `ComparisonEnqueueResponse` | 是(父子 run) | 否 | 900s |

### Risk(role = risk)

| 工具 | 调用方 | 输入 → 输出 | 副作用 | 幂等 | 超时 |
|---|---|---|---|---|---|
| `run_risk_checks` | risk_agent | `RiskChecksConfig` → `RiskCheckReport` | 否(只读审计) | 是 | 120s |
| `cost_sensitivity_sweep` | risk_agent | `SensitivityRequest` → `SensitivityResponse` | 否(只读计算) | 是 | 600s |

### Report(role = report)

| 工具 | 调用方 | 输入 → 输出 | 副作用 | 幂等 | 超时 |
|---|---|---|---|---|---|
| `generate_memo` | report_agent | `ResearchPlan` → `ResearchMemo` | 是(持久化报告) | 是(同 plan 重生成覆盖) | 180s |

## Agent Run / Step / Tool Call State Machine

`AgentRun`、`AgentStep`、`ToolCall` 共用一套状态机(见 `agent.py` 的 `RUN_TRANSITIONS`
与 `STEP_TRANSITIONS`)。**终态(`succeeded` / `failed` / `canceled`)不可回退** ——
任何试图离开终态的转换都会抛 `IllegalStateTransitionError`。

### AgentRun

```
draft ──┬──> validated ──┬──> queued ──> running ──┬──> succeeded (terminal)
        │                │                         ├──> failed    (terminal)
        └──> canceled    └──> canceled             └──> canceled  (terminal)
            (terminal)       (terminal)
```

| 当前 | 合法目标 |
|---|---|
| `draft` | `validated`, `canceled` |
| `validated` | `queued`, `canceled` |
| `queued` | `running`, `canceled` |
| `running` | `succeeded`, `failed`, `canceled` |
| `succeeded` / `failed` / `canceled` | ∅(终态) |

注:AgentRun 用 `succeeded`(过去式),与 `BacktestRun.status` 的 `success` 是两套
生命周期,FRA-85 在持久层做映射。

### AgentStep / ToolCall

Step 与 ToolCall 只在 run 进入 `queued` 后才存在,跳过 plan 级的 `draft`/`validated`:

| 当前 | 合法目标 |
|---|---|
| `queued` | `running`, `canceled` |
| `running` | `succeeded`, `failed`, `canceled` |
| `succeeded` / `failed` / `canceled` | ∅(终态) |

## Safety Boundaries

1. Agent **不直接连接**真实交易 / 经纪接口。
2. Agent **不输出**「买入 / 卖出建议」作为确定性投资建议。
3. Agent 产出的策略代码必须通过**模板或 sandbox** 执行 —— 永远不得 `eval` / `exec`
   模型自由输出;模型**不得生成或执行任意 Python / SQL / shell**。
4. 只允许**白名单**策略(`STRATEGY_NAMES`)、因子(`TECHNICAL_FACTOR_NAMES` +
   `sentiment`)与工具(`KNOWN_TOOL_NAMES`);未知者一律拒绝。
5. 所有报告**必须**包含风险提示和局限性章节;所有结论**必须**绑定数据窗口、
   资产 universe、`transaction_cost_bps` 与 `assumptions`。

### Week 4 补充:文本因子边界

Factor Agent 在使用 sentiment / text factor 时,必须遵守
[`sentiment-factor-methodology.md`](./sentiment-factor-methodology.md) 中的
防前视约束:

- **时间戳对齐**:`published_at` 映射到第一个 ≥ 它的交易日(`signal_date`),
  绝不提前。Agent 不得绕过此映射(如直接使用 raw `published_at` 作为决策日)。
- **NaN 不前填**:无新闻覆盖的单元格 = NaN,Agent 不得用 forward-fill 或 0 填充。
- **可复现性声明**:Agent 使用 sentiment factor 时必须在 plan 与报告中标注
  `provider`、`model_name`、`prompt_version` 和数据窗口(`SentimentProvenance`)。
- **分类漂移**:`sentiment_scores` 表的 `model_name` + `prompt_version` 是
  分类结果可审计的唯一凭证;Agent 不得声称文本因子「改善」了收益,只能描述为
  「在该窗口 / 该模型 / 该分类器下的历史对照结果」。

## Evaluation

Agent 的评估围绕**契约一致性**与**可复现性**,而非收益预测能力(本系统不预测未来、
不构成投资建议)。回归与集成测试覆盖以下维度:

| 维度 | 判定 | 证据 |
|---|---|---|
| Plan 契约一致 | 前后端校验同一份 canonical fixture 通过;非法样例(空 universe、日期倒置、缺 benchmark / 交易成本 / baseline、未知 factor / strategy / tool)被拒 | `tests/test_agent_contracts.py`、`apps/web/src/agent/research-plan.contract.test.ts` |
| Tool-call 合法性 | 调用必须在 `KNOWN_TOOL_NAMES` 内,`status` 转换合法 | `agent.py` `ToolCall._validate_tool_name` + 状态机测试 |
| 状态机不可逆 | 终态无任何合法出边;非法转换抛 `IllegalStateTransitionError` | `tests/test_agent_contracts.py::test_*_transition*` |
| 假设 / 窗口绑定 | plan 必须含 `assumptions`、`requested_outputs`、`start/end_date`、`data_source`、`price_field`、`transaction_cost_bps` | `ResearchPlan._validate_invariants` |
| Sentiment 可审计 | sentiment 因子强制 `SentimentProvenance`(provider/model/prompt 或 pending) | `tests/test_agent_contracts.py::test_sentiment_*` |
| Memo 含风险提示 | `generate_memo` 输出必含 limitations 章节 | (FRA-86/87 实现时补回归) |
| 回归 prompt 集 | 固定投研问题 → 期望 plan 结构(字段存在 + 白名单命中),防 Planner 回归 | (FRA-86 实现时补) |

非目标:不评估「策略是否跑赢基准」,不把回测收益作为 Agent 质量指标 —— 任何
「看起来太好」的结果应先怀疑是 look-ahead / 过拟合 bug(见 `AGENTS.md` 域规则)。

## Ref

- [`apps/api/app/schemas/agent.py`](../apps/api/app/schemas/agent.py) — Pydantic v2 契约
  (`ResearchPlan` / 状态机 / `TOOL_CATALOG`)。
- [`packages/shared/src/schemas/index.ts`](../packages/shared/src/schemas/index.ts) —
  Zod 镜像 + 推导类型。
- [`packages/shared/src/__fixtures__/research-plan.canonical.json`](../packages/shared/src/__fixtures__/research-plan.canonical.json) —
  前后端共享 canonical fixture。
- [`sentiment-factor-methodology.md`](./sentiment-factor-methodology.md) — 文本因子
  防前视约束(FRA-73)。
- [`backtesting-methodology.md`](./backtesting-methodology.md) — 回测口径、防作弊六条、
  成本敏感性要求。
