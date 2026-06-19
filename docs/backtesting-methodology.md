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

### Week 2 Audit Coverage (FRA-39)

| 规则 | 实现位置 | 测试 / 文档证据 |
|---|---|---|
| Look-ahead bias | `run_backtest` 统一执行 `holdings = decision.shift(1)`；策略只输出决策日 target weights | `tests/test_backtest_engine.py::test_lookahead_t_day_target_does_not_move_t_day_gross`、`test_lookahead_t_minus_1_target_moves_t_day_gross` |
| Survivorship bias | 当前 universe 由用户 watchlist / sample seed 给定；系统不声称拥有历史成分股数据库 | 本文 `Limitations` 明确限制和缓解方式 |
| 时间切分验证 | `app.services.backtest.validation` 提供 `TimeSplit` + train 选择 / forward 评估 helper | `tests/test_backtest_validation.py` |
| Baseline comparison | `benchmark_asset_id` 支持 QQQ/SPY 等外部 benchmark；`equity_curve.series_kind` 区分 strategy / benchmark | `tests/test_backtest_benchmark.py`、`tests/test_backtest_api.py`、前端 `BacktestCurveChart` |
| 交易成本前后 | 引擎输出 `gross_returns` 与 net `daily_returns`；指标表存 gross/net 两套 | `tests/test_backtest_engine.py::test_cost_deduction_gap_equals_turnover_times_cost`、`tests/test_backtest_metrics.py` |
| 参数可复现 | `backtest_runs.config_json` 写入 universe、date window、strategy、params、cost、rebalance、price field、benchmark | `tests/test_backtest_api.py::test_create_backtest_config_snapshot_contains_reproducibility_fields`、`tests/test_backtest_sensitivity.py` |

## Engine 选型（FRA-25）

> Ref: 项目描述文件 §8.2 技术选择原则、§4 非目标、§11 回测评估、§12 亮点 3

**决策：自建轻量向量化回测引擎（pandas + numpy），不引入 vectorbt / backtrader。**

项目叙事的核心是「可复现、可审计、防作弊」，而非「跑得快」或「策略花样多」。
主题投研的 universe 规模天然很小（§5 场景 A 的 AI 芯片池仅 5 只，典型
5–30 只），回测频率为日频（§4 明确排除高频 / 分钟级），自建向量化引擎约
两三百行即可覆盖全部 baseline 策略与风险指标，引入重型框架得不偿失。

### 为何不用 vectorbt

| 维度 | vectorbt | 自建 |
|---|---|---|
| 依赖体积 | 拖入 Cython / numba / numba-LLVM 工具链，安装与环境再现成本高 | 仅 `pandas` / `numpy` / `exchange-calendars`，已在 `apps/api` deps |
| 可解释性 | 向量化 API 把「何时调仓、成本如何扣除、权重如何对齐收益」封装成黑箱；出问题时难以逐日审计 | 每日调仓 / 收益结算 / 成本扣除显式写在引擎循环里，可逐行追查 |
| 防作弊 | 框架默认行为隐式处理 look-ahead，难向评审证明「只用了 t-1 数据」 | 防作弊约束直接落到 `Strategy` 协议（见接口契约），`prices.shift(1)` 显式可见 |
| 版本稳定性 | 接口随大版本频繁变动，与 Python 3.11 / pandas 2.x 兼容性需反复验证 | 无第三方 breaking change 风险 |

### 为何不用 backtrader

`backtrader` 是事件驱动、强 OOP、自带 cerebro/broker/feeds 体系的框架，面向
复杂订单类型与多资产事件模拟。其 API 与本项目的现代 typed pandas 工作流
（SQLAlchemy 2.0 / Pydantic v2 / mypy strict）风格割裂，且其结果对象序列化
不直接，难以前后端共享（`packages/shared` 契约）。对于日频、线性比例成本、
无日内 / 无滑点 / 无部分成交的非目标范围（§4），backtrader 的事件模型是
过度设计。

### 自建方案的收益与已知取舍

- **收益**：接口契约完全可控、`typing` 完整（mypy strict 通过）、防作弊约束
  落到协议层、回测参数确定性可记录（§11.3 第 6 条）、零新增重型依赖。
- **已知取舍（如实声明）**：
  - 仅支持 **日频 + 线性比例成本模型**（`cost_bps`，单边买卖各计一次）；
    不建模滑点、冲击成本、部分成交、日内执行（均为 §4 非目标）。
  - 向量化执行采用「rebalance 决策在 t 日开盘、按 t 日收盘 realized return
    结算」的简化口径，与真实 T+1 执行存在偏差，将在 Limitations 中说明。
  - 不内置组合优化器（risk parity / inverse volatility 的权重计算由各自
    策略 issue 实现，引擎只接收 `weights`）。

### 向量化 vs 事件驱动

选定 **向量化**（每日批量计算权重与收益，非逐笔事件循环）。理由：日频口径下
向量化与事件驱动结果等价，但前者代码量小一个数量级、可读性高、易于审计，
契合「可解释 baseline」原则（§8.2 第 4 条）。事件驱动留待未来支持日内 /
分钟级时再评估（当前非目标）。

## 接口契约（FRA-25）

> 实现位于 `apps/api/app/services/backtest/`（`types.py` 数据契约、
> `protocols.py` 行为协议）。本节锁定各模块对内部数据结构的假设，避免策略 /
> 指标 / API 各自为政。FRA-25 仅交付 stub（typing 完整、可被后续 issue 直接
> 实现），不包含 `run` 循环、权重计算或风险指标的实现。

### 价格 DataFrame 约定

引擎、策略、指标三层共享的**价格宽表**格式（沿用 Week 1 数据约定）：

| 属性 | 约定 |
|---|---|
| `index` | `DatetimeIndex`，tz-aware **UTC 00:00（午夜）**，升序，与 `ohlcv.time` 一致 |
| `columns` | `asset_id`（UUID 字符串），即 `Asset.id` 的字符串形式 |
| `dtype` | `float64`（从 `ohlcv.close` / `ohlcv.adjusted_close` 的 `Numeric(20,6)` 转换而来） |
| `price_field` | 由 `BacktestConfig.price_field` 选择：`RAW` → `close`，`ADJUSTED` → `adjusted_close`（默认复权，避免除权跳空污染收益） |
| 缺失值 | `NaN`。rebalance 日若某资产缺失，策略应产出 `NaN`/0 权重；引擎不前向填充未来数据 |

交易日历由 `exchange_calendars`（Week 1 quality.py 已用）提供，universe 跨
交易所时取并集并如实记录（survivorship / calendar mismatch 见 Limitations）。

### `Strategy` 协议（`protocols.py`）

```python
class Strategy(Protocol):
    def weights(self, prices: pd.DataFrame) -> pd.DataFrame: ...
```

- **输入**：价格宽表（截断到决策点；引擎保证 `t` 日调仓决策只看到 `t-1` 及
  更早数据）。
- **输出**：与输入同形状的**目标权重宽表**，每行权重之和应在 `[0, 1]`
  （允许留现金，现金权重 = `1 − Σ`）。引擎按 `weights_t` 在 `t` 日调仓。
- **防作弊（落到接口）**：策略实现只能使用 `prices` 中 `t-1` 及更早的行。
  Week 2 引擎契约是：策略对传入的价格表产出**决策日目标权重**，引擎随后统一
  对 target weights 执行 `decision.shift(1)` 得到实际持仓；策略**不应**自行
  shift。等权 / 均线 / 动量等 baseline 的权重计算必须遵守该契约。

### `BacktestConfig`（`types.py`）

可复现参数记录（§11.3 第 6 条）：universe、`start` / `end`（`date`）、
`initial_capital`（默认 100000）、`cost_bps`（单边交易成本，basis points，
默认 0，支持成本前后对比 = §11.3 第 5 条）、`rebalance`
（`RebalanceFreq.DAILY/WEEKLY/MONTHLY`）、`price_field`、`benchmark`
（benchmark 的 `asset_id`，如 QQQ；`None` 表示不对比基准）、
`strategy_name` + `strategy_params`（记录策略名与超参，保证可复现）。

### `BacktestResult`（`types.py`）

引擎输出：`equity_curve`（`pd.Series`，UTC 午夜 index）、`daily_returns`
（`pd.Series`）、`turnover`（`pd.Series`，每个 rebalance 点的换手）、
`positions`（`pd.DataFrame`，index=time、columns=asset_id、values=权重）、
`trades`（`list[Trade]`，每次调仓的权重变化与换手）、`metrics`
（`BacktestMetrics | None`，**留给风险指标 issue 填充**，本 issue 仅占位）。

`BacktestMetrics` 字段与 `packages/shared` 的同名 TS 类型一一对齐
（annual_return / volatility / sharpe_ratio / max_drawdown / calmar_ratio /
turnover / win_rate / beta / correlation），保证前后端契约一致。

### `BacktestEngine` 协议（`protocols.py`）

```python
class BacktestEngine(Protocol):
    def run(self, config: BacktestConfig, prices: pd.DataFrame) -> BacktestResult: ...
```

引擎 `run` 循环、收益结算、成本扣除、换手统计的**实现**由引擎核心 issue
交付（不在 FRA-25 范围）。本 issue 只锁定其调用签名，使策略 / 指标 / API
三方可在引擎落地前对着同一契约编码。

## Sensitivity Analysis

> Ref: 项目描述文件 §7.2 P1、§11.3 第 5 条;实现位于
> `apps/api/app/services/backtest/sensitivity.py`(FRA-35)。

**Week 2 MVP 目标**:证明系统能记录参数、跨成本假设对比、避免只展示单一最优曲线。
完整因子参数研究(因子 IC、分层回测、显著性统计、超参自动搜索)**明确推迟到
Week 3**(见下文「非目标」)。

### 网格(Week 2)

| 策略 | 维度 | 默认档位 |
|---|---|---|
| Moving Average Crossover | fast × slow × cost | (5, 10) × (20, 50) × (0, 5, 10, 25)bps |
| Momentum | lookback × top_k × rebalance × cost | (21, 63) × (1, 3) × (daily, monthly) × (0, 5, 10, 25)bps |

* 成本档 `[0, 5, 10, 25]bps` 是单边交易成本,满足 §11.3 第 5 条「成本前后对比」
  与 §7.2 成本敏感性;每档成本对所有策略点重复,使「换手 → 成本 → 净收益」可横向对比。
* Momentum 单独把 `rebalance` 作为维度(daily / monthly),使换仓频率对结果的
  影响可被度量(issue「rebalance 至少一个小网格」)。

### 流程

1. **展开网格**(`ma_crossover_configs` / `momentum_configs`):从一份 base
   `BacktestConfig` 用 `dataclasses.replace` 生成每个 (参数, cost) 组合的 frozen
   config;`fast >= slow` 的非法组合被过滤。
2. **跑网格**(`run_sweep`):对**同一份** prices 逐 config 跑 FRA-28 引擎 + FRA-34
   指标(gross / net 双口径),产出 `list[SweepPoint]`。复用同一份 prices 保证点间
   可比 —— 差异只来自参数 / 成本,而非数据窗口。
3. **汇总**(`summarize_sweep`):每个 point 输出 net Sharpe / MaxDD / turnover /
   gross-net 年化收益差;对每个维度(策略参数 + cost)算 *normalized range*
   `(max 组均值 − min 组均值) / |总体均值|`,超过阈值(默认 0.5)标记为「高影响」。
   任一维度高影响 → 「结果高度依赖单一参数」,提示不要只信单一最优参数点。

### 入库与可复现

每个 (参数, cost) 组合写入一个 `BacktestRun(run_kind='sensitivity')` + 1:1
`BacktestMetrics`(指标来自 `run_sweep`,**不重跑回测** —— sweep 复用同一份 prices,
重跑是浪费)。每个 run 的 `config_json` 内嵌完整 sweep 网格规格
(`config_json.sweep.grid`)+ 该点的参数 / 成本,使任一子 run 独立可复现(§11.3
第 6 条)。sweep run 用 `run_kind='sensitivity'` 与常规回测区分,便于查询。

### 非目标(明确推迟到 Week 3)

* 超参自动搜索 / 优化(网格之外的贝叶斯优化、遗传算法等);
* 因子 IC / 分层回测 / 显著性统计(因子研究专题);
* 前端热力图 / 交互式可视化(Week 2 仅产出表格 / JSON)。

## Limitations

Week 2 回测输出必须与以下限制一起解读；报告和 UI 不应把结果表述为投资建议或
盈利承诺。

### Survivorship / Universe

当前 universe 来自用户 watchlist、seed 样例资产或一次 API 请求中的资产列表。系统
尚未接入历史指数成分、退市证券或公司行动事件数据库，因此无法完全消除
survivorship bias。缓解方式是：每次 run 在 `config_json.universe` 记录资产 UUID
集合，并在 demo / report 中明确 asset universe；若用户选择的是当前仍存在的股票池，
结论只能解释为“该给定股票池在该窗口的历史模拟”，不能外推为真实历史可投资集合。

### Look-Ahead Mitigation

引擎在 target weights 到实际 holdings 的边界统一执行一日延迟：
`holdings = decision.shift(1).fillna(0)`。这保证 t 日策略信号不会影响 t 日收益。
测试覆盖“改 t 日 target 不改变 t 日收益、改 t-1 target 才改变 t 日收益”。该机制
只约束本地策略接口；未来若接入外部因子或 LLM 生成策略，仍必须保证输入特征本身
没有包含未来数据。

### Time Split

金融时间序列不能随机切分。Week 2 提供 `TimeSplit` helper：先在 train 窗口按
net Sharpe / annual return 选择候选配置，再把同一配置复制到更晚的 forward 窗口
评估。该 helper 是最小可演示版本，不等同于完整 walk-forward optimization；
完整因子研究和统计检验推迟到 Week 3。

### Execution / Cost Model

执行模型是日频、收盘价、权重目标模型：不模拟日内成交、滑点、冲击成本、部分成交、
限价单、停牌成交失败或税费。`cost_bps` 是单边比例成本，应用于买入和卖出的权重
变化。gross/net 对比可展示成本影响方向，但不是真实交易成本估计。

### Benchmarks

Benchmark comparison 使用同一数据源和窗口中的 QQQ/SPY 等单资产 buy-and-hold 曲线。
若 benchmark 数据缺失，前缀缺口会被跳过，Beta / Correlation 可能为 0 或 `None`。
缺失 benchmark 不代表策略没有市场风险，只代表当前 run 没有足够基准数据。

### Sample Size / Regime Dependence

短窗口、单一市场状态或单一主题股票池的回测容易过拟合。即使 train→forward demo
通过，也只能说明该窗口下的实现链路可复现，不能证明策略稳健、可盈利或优于市场。
