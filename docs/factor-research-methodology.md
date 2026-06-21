# Factor Research Methodology

> 配套 [`backtesting-methodology.md`](./backtesting-methodology.md)。Week 3 把
> 因子研究能力加到 Week 2 的可复现、可审计、防作弊回测框架之上。本文记录因子
> 构造、IC 评估、分层回测、参数敏感性网格的方法与口径,并附 Week 3 防作弊
> 审计表(实现位置 + 测试证据)。
>
> **定位**:本系统是**研究工具**,产出因子预测力的统计证据与可视化,**不是**
> 交易系统,不输出交易信号、不预测未来收益、不构成投资建议(见末节「非目标」
> 与 `AGENTS.md`)。

## 概述

因子研究回答「某个可观测量(因子)是否对资产未来收益有截面预测力」。流程:

1. **构造因子**:从价格宽表算出每个资产每期的因子值(动量 / 反转 / RSI /
   波动率,因子名编码参数如 `momentum_21`)。
2. **评估预测力**:用信息系数(IC)衡量因子值与未来收益的截面排序相关,并给
   出显著性统计(ICIR / t-stat / p-value)。
3. **分层回测**:按因子值把 universe 分成 N 层,看各层累计收益是否单调、
   多空(最高层 − 最低层)是否为正。
4. **敏感性扫描**:在因子 × 窗口 × 选股方式 × 调仓频率 × 成本网格上跑同一份
   价格,看结论是否对单一参数过度敏感(过拟合信号)。

所有计算复用 Week 2 的防前视原语:`load_prices` 无 forward-fill、因子滚动 /
扩展窗口、forward return 仅用于评估、分层回测复用引擎 `holdings =
decision.shift(1)` 边界。

## 价格宽表约定(复用 Week 2)

因子输入与 Week 2 回测同一份价格宽表(见 `backtesting-methodology.md` §价格
DataFrame 约定):

- `index` = tz-aware UTC 午夜(每个交易日一行);
- `columns` = `str(asset_id)`;
- `dtype` = `float64`;
- **缺失不前向填充**:停牌 / 缺数据保留为 `NaN`,因子计算让 NaN 自然传播,
  `factor_values` 不存 NaN 单元格。

`load_prices`(`app/services/backtest/prices.py`)是唯一的价格读取入口,因子服务
(`app/services/factors/service.py`)直接复用,不另写加载逻辑。

## 因子构造

| 因子 | 函数 | 口径 |
|---|---|---|
| 动量 | `momentum(prices, window)` | `p_t / p_{t-window} − 1`(滚动窗口,只看过去) |
| 反转 | `reversal(prices, window)` | `−momentum`(短窗反转,= 负动量) |
| RSI | `rsi(prices, period)` | 滚动 RSI(平均涨幅 / 平均涨跌幅) |
| 波动率 | `volatility(prices, window)` | 滚动日收益标准差(年化由评估层按需) |

实现:`app/services/factors/momentum.py`、`technical.py`。注册表
`FACTOR_REGISTRY`(`service.py`)按名取用,默认参数档:`momentum_21/63/126`、
`reversal_5/21`、`rsi_14`、`volatility_20d/63d`。

**预热期**:`window` 长度的前若干行无足够历史,输出 `NaN`(不前填、不补 0),
下游评估自动跳过 NaN。这是防前视的第一道关口——因子在 t 行只用了 ≤ t 的价格。

## 信息系数(IC)

IC 衡量因子值与未来收益的**截面排序相关**:对每个时间点 t,把 universe 内各
资产的因子值与未来 `horizon` 日收益做 Spearman 秩相关,得到逐期 IC 序列。

- `forward_returns(prices, horizon)`:`p_{t+horizon} / p_t − 1`,**仅用于评估**,
  绝不进入策略决策或因子输入(否则 = 用未来收益预测过去)。
- `evaluate_ic(factor, forward_returns)`:逐期 Spearman → IC 序列 + 汇总。

实现:`app/services/factors/evaluation.py`。

**horizon 选择**:默认 5 个交易日(可配)。horizon 越长,IC 越平滑但样本越少、
重叠越高;5 日是日频研究的常用起点,变更需在 `config_snapshot` 记录以保证可复现。

## 显著性统计

IC 序列的汇总统计(`ICSummary`),用于判断「IC 非零是否只是噪音」:

| 统计 | 定义 | 解读 |
|---|---|---|
| `mean` | IC 均值 | 方向(正 = 因子值高 → 未来收益高) |
| `icir` | `mean / std` | 信息比率,单位风险下的预测力 |
| `t_stat` | `sqrt(N) · mean / std` | 显著性(N = IC 期数) |
| `p_value` | 双尾,`erfc(|t_stat| / sqrt(2))` | t-stat 对应显著性水平 |
| `n` | IC 期数 | 样本量 |
| `positive_rate` | IC > 0 的期数占比 | 方向稳定性 |

**解读纪律**:`t_stat` 绝对值 ≳ 2 习惯上视作「显著」,但:

- 显著 ≠ 可交易:IC 没有扣除交易成本、滑点、容量限制(见 Limitations);
- 多重检验:在全网格上挑最优因子/窗口会 inflate 显著性,需用 out-of-sample
  或更严阈值修正(见敏感性扫描过拟合警告);
- `n` 小时 t-stat 不稳定。

## 分层(Quantile)回测

把每个时间点的 universe 按因子值排序均分 N 层(1 = 因子值最低,N = 最高),
每层等权多仓,复用 Week 2 引擎逐日结算。

- 实现:`app/services/factors/quantile.py` 的 `QuantileBacktester.run(factor,
  prices, n_quantiles)`,内部分层策略复用 `run_backtest`(`holdings =
  decision.shift(1)` 边界不变)。
- 输出 `QuantileResult`:
  - `quantile_equity`:各层累计净值(标准化为 1.0,key = 1..N);
  - `top_minus_bottom`:最高层 − 最低层的多空累计净值;
  - `monotonicity`:各层平均收益与层序(1..N)的 Spearman 相关;接近 1 表示
    「因子值越高收益越高」的单调关系成立,接近 0 或负则关系混乱(退化时为 NaN)。

**为什么分层而非直接回测单因子**:分层把「因子有没有单调区分力」和「交易
成本 / 容量」分开看——单调性是纯排序性质,不依赖成本假设;多空净值再叠加成本
敏感性。两者一致才构成较稳的证据。

## 参数敏感性网格

`factor_sensitivity_configs`(`app/services/backtest/sensitivity.py`)把
`factor × window × (top_k | quantile 层) × rebalance × cost_bands` 展开成网格,
对同一份价格逐点跑回测 + 双口径指标,再 `summarize_sweep` 汇总:

- `metric_table`:每点一行(params + cost_bps + gross/net Sharpe / MaxDD / turnover
  + gross-net 收益差);
- `param_impacts`:每个维度的 normalized range(均值极差 / 整体均值),超阈值
  标 `high_impact`;
- `highly_sensitive`:任一维度高影响 → 真(「结果高度依赖单一参数」)。

前端热力图(FRA-58)把 `window × cost_bps` 的 net Sharpe 画成网格,直观展示成本
与窗口对结果的扰动。

**过拟合警告(重要)**:敏感性网格是 **in-sample** 的参数搜索。在网格上挑出
「最优」因子/窗口/top_k 几乎必然 overfit 历史样本——highly_sensitive = true 恰恰
说明结论不可轻信。稳健做法是 in-sample 选参后必须在独立的 forward 窗口验证
(复用 `app/services/backtest/validation.py` 的 `TimeSplit`),本文不自动执行
该流程,仅提供工具与警告。

## Anti-Cheat Rules(因子版)

继承 Week 2 六条,并细化为因子场景:

1. **因子只用历史**:因子函数均为滚动 / 扩展窗口,只用 ≤ t 的价格;预热期输出
   NaN 而非前填。
2. **forward return 仅评估**:`forward_returns` 只在 `evaluate_ic` 内消费,不进
   策略决策,不作为因子输入。
3. **价格无 forward-fill**:`load_prices` 不对缺口前填,NaN 自然传播。
4. **分层 shift(1) 边界**:分层回测复用引擎,target weights 到 holdings 统一
   一日延迟(`holdings = decision.shift(1)`)。
5. **数据窗口绑定**:因子值 PK `(asset_id, factor_name, time, source)` 锁定来源
   与时间;每次 run 的完整参数写 `config_json` / `config_snapshot`。
6. **参数可复现**:异步 job 结果落 `result_json`,输入快照落 `config_json`,任一
   run 可独立复现。

### Week 3 Audit Coverage (FRA-59)

| 规则 | 实现位置 | 测试 / 文档证据 |
|---|---|---|
| 因子只用历史(无前视) | 因子滚动 / 扩展窗口(`factors/momentum.py`、`factors/technical.py`);预热期输出 NaN 不前填 | `tests/test_factor_momentum.py::test_factor_value_is_stable_against_future_prices`、`test_warmup_rows_are_nan`、`test_nan_input_propagates_without_forward_fill` |
| forward return 仅评估 | `forward_returns` 只在 `evaluate_ic` 消费;分层复用引擎 `holdings = decision.shift(1)` | `tests/test_factor_evaluation.py`、`tests/test_factor_quantile.py`(未来因子行不影响过去权益) |
| 价格无 forward-fill | `load_prices`(`backtest/prices.py`)保留缺口为 NaN;因子服务复用同一入口 | `tests/test_factor_service.py`、`tests/test_backtest_prices.py` |
| Survivorship | universe 由用户 watchlist / 请求给定,系统无历史成分股 / 退市数据库 | 本文 `Limitations §Survivorship` |
| Overfitting | 敏感性网格标注 in-sample;train/forward 切分复用 `backtest/validation.py` | `tests/test_factor_sensitivity.py::test_run_sweep_cost_dimension_drags_net_sharpe`、`tests/test_backtest_validation.py`、本文 `敏感性网格` 过拟合警告 |
| 数据窗口绑定 | `factor_values` PK `(asset_id, factor_name, time, source)` 幂等 upsert | `tests/test_factor_service.py::test_source_is_part_of_primary_key`、`test_repeat_compute_is_idempotent`、`test_read_back_matches_computed` |
| 参数可复现 | job `config_json`(输入快照)+ `result_json`(结构化结果);API 每响应带 `config_snapshot` | `tests/test_factor_worker.py::test_get_job_success_returns_result`、`tests/test_factor_api.py`(config_snapshot) |

## 接口契约

因子层协议(纯函数 / dataclass,便于审计与测试):

- **`Factor.compute(prices) → DataFrame`**(`factors/protocols.py`):输入价格宽表,
  输出同 index/columns 的因子值宽表(NaN 表示预热 / 缺失)。
- **`InformationCoefficient.evaluate(factor, forward_returns) → ICResult`**:
  逐期 Spearman + 汇总。
- **`QuantileBacktester.run(factor, prices, n_quantiles) → QuantileResult`**:
  分层回测,复用 Week 2 `BacktestConfig` / 引擎。
- **`Strategy` 协议(Week 2)**:因子选股策略 `FactorStrategy` 注册为 `"factor"`,
  供敏感性网格与普通回测复用。

前后端契约类型见 `packages/shared/src/types/index.ts`(`TimeSeriesPoint` /
`FactorValue` / `ICSummary` / `ICResult` / `QuantileResult`),与后端
`app/schemas/factor.py` 一一对应,前端无二次转换层。

## Limitations

因子研究结果必须与以下限制一起解读;报告和 UI 不应把结果表述为投资建议、
预测或盈利承诺。

### IC ≠ 可交易 alpha

IC 衡量的是截面排序预测力,不含交易成本、滑点、冲击成本、容量、卖空可行性、
税费。一个统计显著的 IC 在扣除成本、考虑实际可投资性后可能消失。多空净值
(`top_minus_bottom`)虽叠加了 `cost_bands`,但成本模型仍是单边比例成本(见
`backtesting-methodology.md §Execution / Cost Model`),不是真实交易成本估计。

### 短窗口过拟合

默认 demo 窗口(~1 年、5 资产量级)样本量小,IC 的 t-stat 与分层单调性都不稳
定。在敏感性网格上挑最优参数几乎必然 overfit。任何「最优因子/窗口」结论必须
经独立 forward 窗口验证(本文提供 `TimeSplit` 工具但不自动执行)。

### 单一数据源

数据仅来自 yfinance(单一免费源),可能有拆分调整错误、退市数据缺失、延迟。因子
值与 IC 都继承该数据源的所有偏差;`source` 字段记录来源以便区分,但当前未接入
多源交叉校验。

### Survivorship / Universe

universe 来自用户 watchlist 或一次请求的资产列表,系统未接入历史指数成分、退市
证券或公司行动事件库,无法完全消除 survivorship bias。结论只能解释为「该给定
股票池在该窗口的历史模拟」,不能外推为真实历史可投资集合。每次 run 的
`config_json.universe` 记录资产集合以明示边界。

### Look-Ahead 边界

本地因子接口的防前视由滚动窗口 + 预热 NaN + `shift(1)` 边界保证。但该约束只覆盖
系统内部计算的因子;未来若接入**外部因子或 LLM 生成因子**,仍必须单独保证其输入
特征本身不含未来数据——系统无法替外部数据源做此担保。

## 非目标

- **不交易、不下单**:无 broker 接入,因子值与回测净值均为离线研究产物。
- **不预测未来**:IC / 分层 / 敏感性是对**历史样本**的统计描述,不外推未来。
- **不构成投资建议**:所有输出供研究与学习,`AGENTS.md` 明确禁止把结果表述为
  推荐或承诺。

## Ref

- [`backtesting-methodology.md`](./backtesting-methodology.md) — Week 2 回测口径、
  防作弊六条、引擎选型、Limitations(本文继承并扩展)。
- `packages/shared/src/types/index.ts` — 前后端共享因子契约类型。
- `app/services/factors/` — 因子计算、IC 评估、分层、worker job 实现。
- `app/services/backtest/sensitivity.py` — 参数 / 成本敏感性网格(FRA-54)。
