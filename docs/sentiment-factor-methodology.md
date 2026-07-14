# Sentiment Factor Methodology

> 配套 [`backtesting-methodology.md`](./backtesting-methodology.md) 与
> [`factor-research-methodology.md`](./factor-research-methodology.md)。Week 4 把
> 金融文本因子(新闻情绪)加到 Week 2/3 的可复现、可审计、防作弊框架之上。本文
> 记录新闻时间戳对齐、情绪分类、sentiment factor 聚合、technical-only vs
> technical+sentiment 对照实验的方法与口径,并附 Week 4 防作弊审计表(实现位置 +
> 测试证据)。
>
> **定位**:本系统是**研究工具**,产出文本因子的统计证据与可视化,**不是**交易
> 系统,不输出交易信号、不预测未来收益、不构成投资建议(见末节「非目标」与
> `AGENTS.md`)。文本因子比价格因子更容易引入时间戳、来源覆盖、LLM 分类漂移和
> 过拟合问题——本文如实记录这些限制。

## 概述

新闻情绪因子研究回答「市场文本信息(新闻标题 / 摘要)的方向性情绪是否对资产
未来收益有截面预测力」。流程:

1. **采集新闻**(`FRA-67`):按 universe + 时间窗口从 provider 拉取新闻,幂等 upsert
   到 `news_items` 表。
2. **分类情绪**(`FRA-68`):对每条新闻调用 classifier(fixture 规则或 LLM),输出
   `{label, score, confidence, model_name, prompt_version}`,幂等 upsert 到
   `sentiment_scores` 表。
3. **构造因子**(`FRA-69`):把每个 `sentiment_score.published_at` 映射到第一个
   ≥ 它的交易日(`signal_date`),按 `(signal_date, asset_id)` 取日频均值,得到日频
   sentiment factor(宽表),持久化到 `factor_values` 表。
4. **对照实验**(`FRA-71`):在同一 universe / window / prices / cost 条件下跑
   technical-only 与 technical+sentiment 策略,比较是否文本因子改善了短期择时表现。

所有计算复用 Week 2/3 的防前视原语:`published_at` 映射到 ≥ 它的交易日(绝不提前)、
NaN 不前向填充(缺覆盖 = 无信号)、引擎统一 `holdings = decision.shift(1)`。

## 新闻时间戳与交易日对齐

**这是文本因子防前视的核心关卡。** 新闻的 `published_at` 是信息最早可用的时刻;
一条新闻不能影响其发布时刻之前的持仓决策。

### 映射规则

| 场景 | 映射 | 示例 |
|---|---|---|
| 盘前发布(`published_at` 在 T 日 00:00–开盘) | → T 日 `signal_date` | T 日 03:30 发布 → T 日 |
| 盘中发布(`published_at` 在 T 日交易时段) | → **T+1 日** `signal_date` | T 日 14:00 发布 → T+1 日 |
| 盘后发布(`published_at` 在 T 日收盘后) | → **T+1 日** `signal_date` | T 日 20:00 发布 → T+1 日 |
| 周末 / 节假日发布 | → 下一个交易日 `signal_date` | 周六发布 → 周一 |

实现:`app/services/sentiment/factor.py` 的 `compute_sentiment_factor_frame()`。
具体算法:用 `exchange_calendars` 取 universe 交易日历,对每条 score 的
`published_at` 做 `calendar.searchsorted(pub, side='right')` 向后取第一个交易日
(午夜 00:00 UTC)。这保证 `signal_date >= published_at`(绝不提前)。

**为什么盘中映射到 T+1 而非 T 日**:保守口径——当日盘中发布的新闻无法保证在当日
开盘决策前被收到(决策时点在开盘),映射到 T+1 确保 `shift(1)` 后实际持仓变更
发生在 T+2 开盘,与真实信息到达 → 下一个决策窗口 → 执行的链条一致。

### signal_date 与 holdings 的关系

```
published_at ──映射──→ signal_date ──shift(1)──→ holdings 生效日
(新闻发布)        (第一个 >= published_at        (signal_date 的下一个交易日)
                   的交易日午夜)
```

引擎统一执行 `holdings = decision.shift(1)`,因此 `signal_date` 日的决策在
`signal_date + 1` 日的持仓中生效。这意味着:
- 盘前新闻:published_at=T → signal_date=T → holdings 生效=T+1(隔日)
- 盘后新闻:published_at=T → signal_date=T+1 → holdings 生效=T+2

**不双重滞后**:引擎的 `shift(1)` 是唯一的执行延迟,signal_date 映射不做额外
shift(因为 signal_date 本身已经是「可决策日」,不是「持仓日」)。

## 情绪分类定义

### 数据模型

每条 `SentimentScore`(`app/models/news.py`)记录:

| 字段 | 类型 | 说明 |
|---|---|---|
| `news_item_id` | FK → `news_items` | 关联的新闻条目 |
| `asset_id` | FK → `assets` | 关联的资产 |
| `published_at` | datetime | 继承自 `news_items.published_at`(不复制,join 读取) |
| `model_name` | str | 分类器标识(如 `gpt-4o-mini`、`fixture-rule`) |
| `prompt_version` | str | prompt 模板版本(如 `v1`),保证分类结果可复现 |
| `label` | str | `positive` / `negative` / `neutral` |
| `score` | float | 情绪强度,范围 `[-1, +1]`(正=正面,负=负面) |
| `confidence` | float \| null | 分类器置信度 `[0, 1]`(规则分类器无,LLM 有) |

### 分类器

| 分类器 | key | 实现 | 说明 |
|---|---|---|---|
| 规则(关键词) | `fixture` | `classifier.py::FixtureClassifier` | 正面/负面关键词匹配,确定性、无 LLM 调用 |
| LLM | `llm` | `classifier.py::LLMClassifier` | 调用 OpenAI-compatible API,JSON 解析 + clamp |

实现:`app/services/sentiment/classifier.py`。分类器通过 `get_classifier(key)`
工厂获取,`key=None` 时回退到 `settings.SENTIMENT_DEFAULT_CLASSIFIER`。

**LLM 分类防作弊 / 可复现措施**:
- `prompt_version` 与 `model_name` 持久化到每条 score,使分类结果可审计;
- LLM 返回的 JSON 解析失败时跳过该条(不静默标为中性);
- `score` 被 clamp 到 `[-1, +1]`(LLM 可能返回超出范围的浮点);
- `label` 不在 `{positive, negative, neutral}` 时跳过(不静默纠正);
- 每条 score 记录 `raw_response`?(当前 fixture 分类器不记录 raw,LLM 分类器在
  分类时消费但不持久化 raw JSON——见 Limitations §LLM reproducibility)。

### 幂等性

`sentiment_scores` 的冲突键是 `(news_item_id, model_name)`(同一条新闻 + 同一模型
重分类 = upsert 覆盖,不重复)。`news_items` 的冲突键是
`(asset_id, source, published_at, headline_hash)`。

## Sentiment Factor 聚合

### 因子定义

```
factor(signal_date, asset) = mean(score for all scores where
    published_at maps to signal_date and asset_id == asset)
```

- 无新闻覆盖的 `(signal_date, asset)` 单元格 = **NaN**(不前向填充)。
- 同一天多条新闻:取算术平均。
- 不同 model_name 的 score 分别参与(除非 `model_name` 过滤指定)。

### 聚合函数

`compute_sentiment_factor(db, asset_ids, start, end, model_name)` 返回宽表
DataFrame:

| 属性 | 约定 |
|---|---|
| `index` | UTC 午夜,交易日(signal_date) |
| `columns` | `str(asset_id)` |
| `dtype` | `float64` |
| 缺失值 | `NaN`(无新闻覆盖) |

**复用 Week 2/3 约定**:宽表格式与因子研究完全一致(`factor-research-methodology.md`
§价格宽表约定),sentiment factor 持久化到 `factor_values` 表,source =
`model_name`,可直接被 `read_factor_values` 读取,供回测引擎消费。

### 持久化

`compute_and_store_sentiment_factor()` 计算因子后调用 `persist_factor_values()`
(幂等 upsert,`ON CONFLICT DO UPDATE`),额外持久化 `news_count` 因子(source =
`{model_name}_news_count`)以记录覆盖度。

## Technical-only vs Technical+Sentiment 对照实验

### 实验设计

在同一 universe / window / prices / cost / rebalance 条件下,跑 2–3 组策略:

| 角色 | 策略 | 说明 |
|---|---|---|
| `technical_only` | 纯技术因子(如 momentum) | 对照组,等价 `FactorStrategy` |
| `technical_sentiment` | 技术 + 情绪融合 | 实验组 |
| `sentiment_only`(可选) | 纯情绪因子 | 解释组 |

### 融合模式

| 模式 | 逻辑 |
|---|---|
| `overlay` | 技术因子选 top_k,再用 `sentiment_threshold` 过滤(score < threshold 的被剔除);NaN sentiment 被过滤(不前填) |
| `combined` | 技术因子值 + sentiment 值分别做 `cross_sectional_rank` 归一化到 [0,1],按 `sentiment_weight` 加权后选 top_k |

### 策略协议

`SentimentTechStrategy` 实现 Week 2 `Strategy` 协议(`weights(prices) → DataFrame`),
引擎统一 `holdings = decision.shift(1)`,与所有其他策略共享同一执行边界。

### 实验输出

每组创建一个子 `BacktestRun`(`run_kind="backtest"`, `status="success"`),
父 run(`run_kind="sentiment_comparison"`)的 `result_json["child_runs"]` 存子 run
ID。API 返回 parent + children metrics 对照。

## Anti-Cheat Rules(文本因子版)

继承 Week 2 六条 + Week 3 六条,并细化为文本因子场景:

1. **published_at 不提前映射**:`published_at` 映射到第一个 ≥ 它的交易日
   (`signal_date`),绝不提前。
2. **NaN 不前向填充**:无新闻覆盖的 `(signal_date, asset)` = NaN;NaN sentiment
   在 overlay 模式中被过滤(不前填、不标为中性)。
3. **引擎 shift(1) 边界不变**:sentiment factor 通过 `factor_values` 表进入策略,
   策略只输出决策日 target weights,引擎统一 `holdings = decision.shift(1)`。
4. **分类结果可复现**:`model_name` + `prompt_version` 持久化到每条 score;每次
   run 的完整参数(含 classifier、provider、model_name)写 `config_json` /
   `config_snapshot`。
5. **新闻去重幂等**:`news_items` 按
   `(asset_id, source, published_at, headline_hash)` 去重;`sentiment_scores` 按
   `(news_item_id, model_name)` 去重;重复采集 / 重分类 = upsert,不新增行。
6. **数据窗口绑定**:每次 run 的 `config_json.universe` + `start` / `end` +
   `model_name` + `provider` + `classifier` 锁定来源与时间。

### Week 4 Audit Coverage (FRA-73)

| 规则 | 实现位置 | 测试 / 文档证据 |
|---|---|---|
| published_at 不提前映射 | `factor.py::compute_sentiment_factor_frame` 用 `calendar.searchsorted(pub, side='right')` 向后取交易日 | `tests/test_sentiment_factor.py::test_midnight_publication_maps_to_same_day`、`test_intraday_publication_maps_to_next_day`、`test_naive_datetime_treated_as_utc`、`test_modifying_future_news_does_not_affect_past` |
| NaN 不前向填充 | 因子聚合不 forward-fill;`test_no_forward_fill` 验证缺口保持 NaN | `tests/test_sentiment_factor.py::test_no_forward_fill`、`test_empty_scores_returns_nan_frame` |
| 引擎 shift(1) 不变(含 sentiment) | `SentimentTechStrategy.weights()` 输出决策日权重;引擎统一 shift(1) | `tests/test_sentiment_comparison.py::test_future_price_does_not_move_past_signals`、`test_future_sentiment_does_not_move_past_signals`、`test_signal_at_t_moves_holding_at_t_plus_one` |
| 分类结果可复现 | `sentiment_scores` 存 `model_name` + `prompt_version`;API 每响应带 `config_snapshot` | `tests/test_sentiment_classify.py::test_fixture_classifier_records_reproducibility_fields`、`test_llm_classifier_records_params_with_prompt_version`、`test_classify_writes_scores_and_persists_reproducibility` |
| 新闻去重幂等 | `news_items` 按 `(asset_id, source, published_at, headline_hash)` ON CONFLICT upsert;`sentiment_scores` 按 `(news_item_id, model_name)` ON CONFLICT | `tests/test_sentiment_classify.py::test_upsert_scores_is_idempotent`、`test_classify_is_idempotent_on_repeat`、`test_upsert_scores_overwrites_same_conflict_key` |
| overlay NaN 过滤 | overlay 模式跳过 NaN sentiment 资产(不前填、不标中性) | `tests/test_sentiment_comparison.py::test_overlay_nan_sentiment_filtered`、`test_overlay_all_filtered_is_cash` |
| 对照组等价 FactorStrategy | `sentiment_frame=None` 时退化为纯技术策略,选股逻辑与 `FactorStrategy` 一致 | `tests/test_sentiment_comparison.py::test_pure_technical_matches_factor_strategy_selection`、`test_pure_technical_warmup_is_cash` |
| 参数可复现 | comparison run 的 `config_json` 含完整策略参数(technical_factor / window / top_k / mode / sentiment_threshold / sentiment_weight / cost / rebalance / model_name) | `tests/test_sentiment_comparison.py::test_create_comparison_enqueues_run`、API `config_snapshot` 字段 |
| LLM 分类异常处理 | JSON 解析失败 / label 不在白名单 / score 越界 → 跳过(不静默纠正) | `tests/test_sentiment_classify.py::test_llm_classifier_skips_bad_json`、`test_llm_classifier_skips_bad_label`、`test_llm_classifier_clamps_out_of_range` |
| 因子持久化幂等 | `persist_factor_values` ON CONFLICT DO UPDATE;重复计算 = upsert | `tests/test_sentiment_factor.py::test_idempotent_rerun` |
| 多模型共存 | `(news_item_id, model_name)` 冲突键使不同模型的 score 共存 | `tests/test_sentiment_classify.py::test_upsert_scores_distinct_models_coexist` |

## Limitations

文本因子研究结果必须与以下限制一起解读;报告和 UI 不应把结果表述为投资建议、
预测或盈利承诺。

### IC / 回测 ≠ 可交易 alpha

Sentiment factor 的回测净值与 metrics 继承 `backtesting-methodology.md` 的全部
限制:不含滑点 / 冲击成本 / 容量 / 卖空可行性 / 税费;`cost_bps` 是单边比例成本
的简化模型。一个「看起来不错」的 technical+sentiment 净值差可能来自幸存者偏差、
小样本噪音或数据窥探(data snooping),不能外推为可交易 alpha。

### 新闻覆盖偏差

新闻源(yfinance provider)只覆盖部分资产和部分时间。某些资产在某些日期可能
**完全没有新闻**,导致 `sentiment factor = NaN`。这些 NaN 在 overlay 模式中被
过滤(等价于「不持有」),在 combined 模式中被跳过。**缺失覆盖不等于中性情绪**——
被过滤的资产可能是信号噪音(无新闻 = 无变化 = 正常),也可能是因为 provider 未
覆盖。结论只能解释为「该 provider 在该窗口提供的新闻的聚合情绪」。

### LLM 分类漂移与可复现性

- **LLM 分类非确定性**:同一 prompt + 同一输入在不同时间可能返回不同 label /
  score(模型版本更新、采样温度)。`model_name` + `prompt_version` 持久化可追溯
  分类时使用的配置,但无法保证重跑得到完全相同的 score。
- **raw_response 未持久化**:当前实现不存储 LLM 返回的原始 JSON 文本
  (`raw_response`),无法逐条审计分类器的原始输出。补救:`prompt_version` 锁定
  prompt 模板,`model_name` 锁定模型;但模型内部权重更新不可控。
- **prompt 工程风险**:分类质量高度依赖 prompt 设计。当前 prompt 模板是固定的
  (`v1`),未做 prompt sensitivity 分析——不同 prompt 可能产生显著不同的 score。

### 重复新闻与源质量

新闻按 `(asset_id, source, published_at, headline_hash)` 去重,但:
- **同一事件多个来源**:不同 provider 可能报道同一事件但 headline 不同,导致
  重复计入(Bloomberg 和 Reuters 同一财报)。
- **聚合新闻 vs 原创**:新闻源可能包含聚合 / 转载,headline 相似但 published_at
  不同,未被 `headline_hash` 去重。
- `headline_hash` 用完整 headline 文本的哈希,不做语义去重。

### 过拟合

与 `factor-research-methodology.md §短窗口过拟合` 相同:默认 demo 窗口
(~1 年,小 universe)样本量小。在 `overlay` / `combined` 模式上搜索最优
`sentiment_threshold` / `sentiment_weight` 几乎必然 overfit。technical+sentiment
优于 technical-only 可能只是噪音——需要在独立 forward 窗口验证(本文提供工具
但不自动执行)。

### Survivorship / Universe

继承 Week 2/3 的 survivorship 限制。此外,新闻覆盖本身存在 survivorship:仍在
交易的股票更有新闻覆盖,退市 / 停牌股票的新闻可能缺失。

### Look-Ahead 边界

本地 sentiment factor 的防前视由 `published_at → signal_date` 映射 + NaN 不前填
+ 引擎 `shift(1)` 三重保证。但该约束只覆盖系统内部的因子构造链路;未来若接入
**外部文本因子或 LLM 生成因子**,仍必须单独保证其输入特征本身不含未来数据——
系统无法替外部数据源做此担保。

## 非目标

- **不交易、不下单**:无 broker 接入,所有输出均为离线研究产物。
- **不预测未来**:sentiment factor / 对照净值是对**历史样本**的统计描述,不外推
  未来。
- **不构成投资建议**:所有输出供研究与学习,`AGENTS.md` 明确禁止把结果表述为
  推荐或承诺。
- **不声称文本因子改善收益**:technical+sentiment 优于 technical-only 的回测结果
  不能外推为「情绪因子有用」——可能是过拟合、数据窥探或噪音。

## Ref

- [`backtesting-methodology.md`](./backtesting-methodology.md) — Week 2 回测口径、
  防作弊六条、引擎选型、Limitations(本文继承并扩展)。
- [`factor-research-methodology.md`](./factor-research-methodology.md) — Week 3
  因子研究口径、IC / 分层 / 敏感性网格(本文继承价格因子约定)。
- `app/services/sentiment/` — 新闻采集、情绪分类、因子构造、对照实验实现。
- `app/services/backtest/strategies/sentiment_tech.py` — `SentimentTechStrategy`
  (overlay / combined 融合模式)。
- `app/services/backtest/comparison.py` — 对照实验 runner(纯函数)。
- `packages/shared/src/types/index.ts` — 前后端共享 sentiment 契约类型
  (`NewsItem`、`SentimentScore`、`SentimentSummary`)。
