# FinResearch Agent 项目描述文件

**项目名称**：FinResearch Agent: LLM-powered Financial Research and Backtesting System  
**中文名称**：基于大语言模型 Agent 的金融投研与可复现回测系统  
**项目定位**：面向金融科技申请与 AI/ML 方向申请的综合型工程项目，强调金融数据工程、投研自动化、量化回测验证、风险评估和可解释报告生成。  
**目标申请方向**：NTU MSc AI / MCAAI / SPML / Financial Technology  
**建议周期**：6–8 周完成可展示版本；第一周完成数据底座与 Dashboard 雏形。

---

## 1. 项目背景与申请叙事

当前简历中已有较强的 AI 与大模型背景，包括大语言模型 LoRA 微调、SFT/GRPO、数据集构建、多模态推理、语音大模型系统、司法 AI 数据分析与数据分析实习。短板在于金融科技方向缺少直接相关的金融数据、金融系统、量化研究或投研自动化经历。因此本项目的目的不是临时包装成“量化交易员”，而是自然延伸已有 AI/数据工程能力，构建一个真实、可复现、可展示的 FinTech 场景项目。

项目叙事应定位为：

> 我将已有的大模型、数据处理和系统工程能力迁移到金融科技场景，构建一个 Agent-driven financial research system，用自然语言提出投研假设，通过结构化数据采集、因子构建、回测验证、风险指标和自动化报告生成，形成完整的金融研究闭环。

本项目适合同时服务四个申请方向：

| 申请方向 | 项目对应价值 |
|---|---|
| MSc AI | LLM Agent、RAG、工具调用、模型评估、自动报告生成 |
| MCAAI | 真实行业场景下的 AI 系统实现、Responsible AI、可解释性与风险控制 |
| SPML | 金融时间序列、信号噪声、趋势/动量/波动率分析、预测与验证 |
| FinTech | 金融数据工程、量化回测、投研自动化、风险评估、金融科技应用 |

---

## 2. 项目一句话描述

FinResearch Agent 是一个 AI-ready 的金融投研平台。用户输入自然语言投研问题后，系统会自动解析研究目标，拉取行情与文本数据，构建技术指标、新闻情绪和候选因子，执行可复现回测，并生成包含风险指标、图表和局限性说明的投研报告。

示例用户问题：

```text
过去 6 个月 AI 芯片股是否存在动量效应？
NVDA、AMD、TSM、AVGO、ASML 相比 QQQ 是否具有更高的风险调整收益？
新闻情绪能否改善半导体主题股票的短期择时表现？
```

系统输出：

```text
1. 投研问题拆解
2. 股票池和 benchmark 选择
3. 数据同步状态与数据质量报告
4. 因子构建方法
5. 回测结果：Annual Return、Sharpe、Max Drawdown、Volatility、Turnover
6. 参数敏感性与交易成本分析
7. 自动生成 research memo
8. 模型/策略局限性和风险提示
```

---

## 3. 核心目标

### 3.1 申请材料目标

本项目要在申请材料中证明以下能力：

1. 能够把 AI/LLM 技术落地到金融科技场景，而不是只停留在聊天机器人或模型微调。
2. 理解金融数据不同于普通 CSV，能处理交易日对齐、复权、缺失值、异常收益、数据源一致性等问题。
3. 能够构建可复现的量化研究流程，而不是只展示某一次高收益的回测曲线。
4. 能够使用现代全栈技术搭建可交互系统，体现工程实现能力。
5. 能够用风险指标和 baseline comparison 评价策略，而不是只强调收益率。
6. 能够把 Agent 的自然语言能力与结构化金融工具结合，形成可信的投研自动化流程。

### 3.2 工程目标

项目最终应具备以下闭环：

```text
用户输入投研问题
      ↓
LLM Agent 解析任务
      ↓
数据源选择与数据同步
      ↓
金融时序数据入库与质量检查
      ↓
技术指标 / 情绪因子 / 候选策略构建
      ↓
回测与风险指标计算
      ↓
结果可视化 Dashboard
      ↓
自动生成投研报告
```

### 3.3 最小可行目标

6 周内完成一个可演示版本，至少支持：

- 用户登录
- 股票池管理
- 美股/ETF 日线行情同步
- PostgreSQL + TimescaleDB 时序数据存储
- 数据质量检查
- 价格曲线与同步任务 Dashboard
- 基础因子与策略回测
- 风险指标计算
- LLM Agent 将自然语言问题转换为结构化研究任务
- 自动生成 research memo
- Docker Compose 一键启动
- README、截图、Demo video、英文项目介绍和简历 bullet

---

## 4. 非目标范围

为了避免项目失控，以下内容不作为第一阶段目标：

1. 实盘自动交易。
2. 接入券商真实下单接口。
3. 高频交易或分钟级别交易系统。
4. 复杂强化学习交易策略。
5. Kubernetes 生产部署。
6. 多租户 SaaS 商业系统。
7. 对收益率作夸大宣传。
8. 声称系统能稳定盈利。
9. 过度依赖黑箱 LLM 直接生成交易决策。

本项目的核心是“金融研究自动化与可复现验证”，不是“自动赚钱机器”。

---

## 5. 用户场景

### 场景 A：主题投研

用户输入：

```text
分析 AI 芯片主题股票在 2022 年以来是否存在动量效应。
```

系统行为：

1. 识别主题：AI semiconductor。
2. 默认股票池：NVDA、AMD、TSM、AVGO、ASML。
3. 默认 benchmark：QQQ、SPY。
4. 拉取 2022-01-01 至今的 OHLCV 数据。
5. 计算 1M、3M、6M momentum、volatility、drawdown。
6. 回测月度调仓动量策略。
7. 输出相对 QQQ 的风险调整表现。

### 场景 B：新闻情绪增强策略

用户输入：

```text
新闻情绪是否能提升半导体主题股票的短期择时能力？
```

系统行为：

1. 拉取新闻标题或摘要。
2. 使用金融情绪模型或 LLM classifier 生成 sentiment score。
3. 将 sentiment score 与 momentum factor 结合。
4. 比较 technical-only 与 technical + sentiment 策略。
5. 输出差异指标和统计解释。

### 场景 C：自动生成投研 memo

用户输入：

```text
生成一份关于 NVDA vs QQQ 的风险收益分析报告。
```

系统行为：

1. 拉取 NVDA 和 QQQ 数据。
2. 计算收益、波动率、Sharpe、Max Drawdown、beta、相关性。
3. 生成图表。
4. 自动生成简短 research memo。
5. 在报告末尾列出数据来源、假设和局限性。

---

## 6. 系统架构

### 6.1 总体架构

```text
React / Vite Dashboard
        |
        v
FastAPI Backend  <---->  LLM Agent Orchestrator
        |                         |
        v                         v
Redis Queue  ------------>  Data / Backtest / Report Workers
        |
        v
PostgreSQL + TimescaleDB
        |
        v
Market Data / Factor Data / Backtest Results / Research Memos
```

### 6.2 模块划分

| 模块 | 说明 |
|---|---|
| Web Dashboard | 用户登录、股票池管理、数据同步、回测结果、图表展示 |
| Backend API | 提供认证、资产管理、数据同步、回测、报告查询接口 |
| Data Worker | 拉取行情、新闻、财务指标，执行清洗和入库 |
| Data Quality Engine | 检查缺失交易日、重复数据、空值、异常收益 |
| Factor Engine | 计算技术指标、动量、反转、波动率、情绪因子 |
| Backtesting Engine | 执行策略回测，计算收益和风险指标 |
| Agent Orchestrator | 将自然语言投研问题转换为结构化任务 |
| Report Generator | 生成 research memo、Markdown/PDF 报告 |
| Database | 存储资产、时序行情、因子、回测结果和报告 |

---

## 7. 核心功能需求

### 7.1 P0 必须完成

| 功能 | 具体要求 | 验收标准 |
|---|---|---|
| 用户认证 | 支持注册、登录、JWT 鉴权 | 用户能登录系统并访问 Dashboard |
| 股票池管理 | 支持添加/删除资产，创建 watchlist | 能添加 NVDA、AMD、QQQ 等资产 |
| 行情同步 | 支持拉取美股/ETF 日线 OHLCV | 点击同步后数据入库 |
| 时序数据库 | 使用 PostgreSQL + TimescaleDB 存储行情 | market_ohlcv 表可查询历史价格 |
| 数据质量检查 | 检查缺失、重复、空值、异常收益 | Data Quality 页面能展示问题统计 |
| Dashboard | 展示价格曲线、同步状态、数据统计 | 能截图放入 README |
| Docker 启动 | Docker Compose 一键启动核心服务 | 新环境可复现运行 |

### 7.2 P1 应完成

| 功能 | 具体要求 | 验收标准 |
|---|---|---|
| 回测引擎 | 支持 buy-and-hold、均线、动量策略 | 能输出收益曲线和指标 |
| 风险指标 | 计算 Sharpe、Max Drawdown、Volatility、Turnover | 指标可视化展示 |
| Benchmark 对比 | 支持与 QQQ/SPY 对比 | 策略和 benchmark 曲线同图展示 |
| 参数敏感性 | 对 lookback window、rebalance frequency 进行测试 | 输出参数对结果影响 |
| 交易成本 | 支持交易成本假设 | 展示成本前后表现差异 |

### 7.3 P2 增强功能

| 功能 | 具体要求 | 验收标准 |
|---|---|---|
| LLM Agent | 将自然语言问题转成结构化研究任务 | Agent 输出 JSON plan |
| Research Memo | 自动生成投研报告 | 报告包含数据、图表、结论、局限性 |
| 新闻情绪 | 新闻标题/摘要情绪分析 | sentiment factor 可加入回测 |
| RAG 资料库 | 存储历史报告、策略解释、术语说明 | Agent 能引用已有文档 |
| 代码生成限制 | Agent 不直接执行危险代码 | 所有策略需进入 sandbox/模板化执行 |

---

## 8. 技术栈

### 8.1 推荐技术栈

| 层级 | 技术选择 | 说明 |
|---|---|---|
| Frontend | React + Vite + TypeScript | 快速搭建现代 Web 应用 |
| UI | Ant Design | 适合后台管理和数据系统 |
| Chart | ECharts / Recharts | 展示价格曲线、回撤、收益分布 |
| Backend | FastAPI | Python 生态友好，适合 AI 与数据系统 |
| ORM | SQLAlchemy 2.0 | 类型化、可维护的数据库访问 |
| Schema | Pydantic | API 数据校验与结构化任务定义 |
| Database | PostgreSQL + TimescaleDB | 时序金融数据存储 |
| Queue | Redis + RQ/Celery | 异步数据同步与回测任务 |
| Data Source | OpenBB / yfinance / Stooq | 行情和金融数据入口 |
| Quant | vectorbt / backtrader / Qlib | 回测与量化研究 |
| ML | scikit-learn / LightGBM / PyTorch | 因子建模、预测、分类 |
| Agent | LangGraph / LlamaIndex / 自研 tool-calling | 投研任务编排 |
| Storage | DuckDB 可选 | 本地实验和快速分析 |
| DevOps | Docker Compose | 一键启动和展示复现 |
| Testing | pytest + Playwright | 后端测试和前端 E2E 测试 |

### 8.2 技术选择原则

1. 优先选择成熟、容易展示、容易复现的技术。
2. 第一阶段不引入 Kafka、Airflow、Kubernetes、复杂权限系统。
3. 数据库优先 PostgreSQL + TimescaleDB，而不是只用 CSV 或 SQLite。
4. 回测优先可解释 baseline，而不是复杂黑箱模型。
5. Agent 必须调用结构化工具，不允许自由生成未经验证的结论。

---

## 9. 数据设计

### 9.1 核心表

| 表名 | 用途 |
|---|---|
| users | 用户信息 |
| assets | 股票、ETF、指数等资产元数据 |
| watchlists | 用户自定义股票池 |
| watchlist_assets | 股票池与资产的多对多关系 |
| market_ohlcv | OHLCV 行情时序数据 |
| data_sync_jobs | 数据同步任务状态 |
| data_quality_reports | 数据质量检查结果 |
| factors | 因子值，如 momentum、volatility、sentiment |
| backtest_runs | 回测任务元信息 |
| backtest_metrics | 回测指标 |
| research_memos | 自动生成投研报告 |

### 9.2 market_ohlcv 表设计

```sql
CREATE TABLE market_ohlcv (
    time TIMESTAMPTZ NOT NULL,
    asset_id UUID NOT NULL REFERENCES assets(id),
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    adjusted_close NUMERIC,
    volume BIGINT,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (time, asset_id, source)
);

SELECT create_hypertable('market_ohlcv', 'time');
```

### 9.3 data_quality_reports 表设计

```sql
CREATE TABLE data_quality_reports (
    id UUID PRIMARY KEY,
    asset_id UUID NOT NULL REFERENCES assets(id),
    source TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    missing_days INT,
    duplicate_rows INT,
    null_close_rows INT,
    abnormal_return_days INT,
    generated_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 10. Agent 设计

### 10.1 Agent 角色

| Agent | 职责 |
|---|---|
| Research Planner | 解析用户投研问题，生成结构化研究计划 |
| Data Agent | 选择数据源、股票池、时间范围，触发数据同步 |
| Factor Agent | 选择或构建技术指标、情绪指标、风险指标 |
| Backtest Agent | 配置回测参数并调用回测工具 |
| Risk Agent | 检查交易成本、回撤、过拟合、数据偏差 |
| Report Agent | 生成 research memo 和结论摘要 |

### 10.2 Agent 输出格式

Agent 不应直接输出自由文本结论，而应先输出结构化 JSON：

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

### 10.3 Agent 安全边界

1. Agent 不直接连接真实交易接口。
2. Agent 不输出“买入/卖出建议”作为确定性投资建议。
3. Agent 的策略代码必须通过模板或 sandbox 执行。
4. 所有报告必须包含风险提示和局限性。
5. 所有结论必须绑定数据区间、股票池和假设条件。

---

## 11. 回测与评估设计

### 11.1 Baseline 策略

| 策略 | 用途 |
|---|---|
| Buy and Hold | 最基础基准 |
| Equal Weight Portfolio | 主题股票池等权组合 |
| Moving Average Crossover | 技术分析 baseline |
| Momentum Strategy | 因子研究 baseline |
| Reversal Strategy | 对照实验 |
| QQQ/SPY Benchmark | 市场基准 |

### 11.2 核心指标

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

### 11.3 回测防作弊要求

1. 禁止 look-ahead bias：所有因子只能使用当时可见数据。
2. 避免 survivorship bias：若无法完全处理，需要在报告中说明。
3. 使用时间切分验证，避免随机切分金融时间序列。
4. 每个策略必须与 baseline 比较。
5. 必须展示交易成本前后表现。
6. 必须记录每次回测参数，保证可复现。

---

## 12. 创新点与亮点

### 亮点 1：Agent-driven 投研工作流

项目不是普通 Dashboard，而是将自然语言投研问题转化为结构化金融研究任务。Agent 负责规划数据、因子、回测和报告，使用户能够从自然语言问题进入可验证研究流程。

可写入简历：

> Designed an LLM-agent-based research workflow that converts natural-language investment hypotheses into structured data retrieval, factor construction, backtesting, and risk-report generation tasks.

### 亮点 2：金融数据质量监控

项目强调金融数据工程，而不是简单拉取 CSV。系统会检查缺失交易日、重复行情、空价格、异常收益和同步状态，使金融研究过程更可信。

可写入简历：

> Built a time-series data pipeline with automated quality checks for missing trading days, duplicated records, null prices, and abnormal returns.

### 亮点 3：可复现回测与风险评估

项目不以“策略赚了多少钱”为卖点，而是强调 baseline comparison、transaction cost sensitivity、risk metrics 和参数记录，使结果具有研究可信度。

可写入简历：

> Developed a reproducible backtesting module with benchmark comparison, transaction-cost sensitivity analysis, and risk metrics including Sharpe ratio, volatility, turnover, and maximum drawdown.

### 亮点 4：LLM + 金融文本情绪因子

项目可将新闻标题、财报摘要或公告文本转为 sentiment factor，并与传统技术指标结合，体现大模型背景向金融科技场景迁移。

可写入简历：

> Integrated financial news sentiment signals with technical indicators to evaluate whether text-derived factors improve short-term strategy performance.

### 亮点 5：AI-ready 金融研究平台

系统结构不是一次性脚本，而是全栈平台：前端、后端、数据库、worker、Agent、回测、报告全部有明确接口。该亮点能够展示工程能力。

可写入简历：

> Implemented a full-stack AI-ready financial research platform using React, FastAPI, PostgreSQL/TimescaleDB, Redis, and Docker Compose.

---

## 13. 项目目录结构

```text
finresearch-agent/
  apps/
    web/                  # React 前端
    api/                  # FastAPI 后端
    worker/               # 数据同步与回测 worker
  packages/
    shared/               # 共享类型、常量、schemas
  infra/
    docker/               # Docker 配置
    migrations/           # Alembic migration
  docs/
    architecture.md
    database-schema.md
    agent-design.md
    backtesting-methodology.md
    week1-progress.md
    screenshots/
  notebooks/
    factor_research.ipynb
    sentiment_experiment.ipynb
  tests/
    test_assets_api.py
    test_ohlcv_ingestion.py
    test_quality_report.py
    test_backtest_engine.py
  docker-compose.yml
  README.md
  .env.example
```

---

## 14. 6 周开发路线

### Week 1：金融数据底座与 Dashboard

目标：完成可登录、可同步、可展示行情数据的 Web 系统。

交付物：

- Docker Compose 环境
- FastAPI 后端
- React Dashboard
- PostgreSQL + TimescaleDB
- 用户登录
- 股票池管理
- OHLCV 数据同步
- 数据质量检查
- 价格曲线展示
- README 和截图

### Week 2：回测引擎与风险指标

目标：完成基础策略回测和风险评估。

交付物：

- Buy and Hold
- Equal Weight
- Moving Average
- Momentum Strategy
- Benchmark comparison
- Sharpe、Max Drawdown、Volatility、Turnover
- 回测结果入库
- 回撤曲线和收益曲线

### Week 3：因子研究与参数敏感性

目标：构建可解释因子研究流程。

交付物：

- 1M/3M/6M momentum
- RSI、MACD、volatility
- 因子排名
- 参数敏感性实验
- 交易成本影响分析
- 因子表现报告

### Week 4：金融文本与情绪因子

目标：将 LLM/NLP 能力迁移到金融文本分析。

交付物：

- 新闻标题/摘要采集
- 情绪分类 prompt 或模型
- sentiment score 入库
- sentiment + technical 策略对比
- 文本因子局限性说明

### Week 5：LLM Agent 投研工作流

目标：实现自然语言到结构化研究任务的转换。

交付物：

- Research Planner Agent
- Data Agent
- Factor Agent
- Backtest Agent
- Report Agent
- JSON plan schema
- Agent tool-calling 日志

### Week 6：报告生成与申请材料打磨

目标：把项目包装成 GitHub 和申请材料可展示版本。

交付物：

- 自动 research memo
- Demo video
- GitHub README
- 架构图
- 数据库 ER 图
- 项目截图
- 英文项目介绍
- 中文/英文简历 bullet
- limitations and future work

---

## 15. 第一周最小验收标准

第一周结束时，需要能够录制 1 分钟 demo：

```text
1. 打开网页
2. 登录
3. 进入 dashboard
4. 添加 NVDA / AMD / QQQ 到 watchlist
5. 点击 Sync Data
6. 看到任务状态从 running 变成 success
7. 打开 Dashboard 看到价格曲线
8. 打开 Data Quality 看到缺失值和异常点统计
```

第一周 GitHub README 至少包含：

- Project motivation
- Architecture
- Tech stack
- Data schema
- How to run
- Screenshots
- Week 1 progress
- Next steps

---

## 16. GitHub README 摘要

```text
FinResearch Agent is an AI-ready financial research platform that integrates market data ingestion, time-series storage, data quality monitoring, quantitative backtesting, LLM-agent-based research planning, and automated research memo generation.

The project aims to bridge AI engineering and financial technology by transforming natural-language investment hypotheses into reproducible research workflows with structured data retrieval, factor construction, risk evaluation, and benchmark comparison.
```

---

## 17. 简历表达建议

### 中文简历版本

**AI 驱动的金融投研与回测系统 FinResearch Agent**

- 设计并实现基于 LLM Agent 的金融投研系统，将自然语言投资假设转换为结构化数据同步、因子构建、策略回测与风险报告生成流程。
- 构建基于 React、FastAPI、PostgreSQL/TimescaleDB、Redis 和 Docker Compose 的全栈金融研究平台，支持股票池管理、行情数据入库、数据质量监控和交互式可视化。
- 实现可复现量化回测模块，支持 Buy-and-Hold、均线、动量等 baseline 策略，并通过 Sharpe Ratio、Max Drawdown、Volatility、Turnover 和交易成本敏感性进行评估。
- 集成金融新闻情绪与技术指标，探索文本因子对短期策略表现的影响，并在自动生成的 research memo 中呈现假设、结果、风险和局限性。

### 英文简历版本

**FinResearch Agent: LLM-powered Financial Research and Backtesting System**

- Designed an LLM-agent-based investment research system that transforms natural-language hypotheses into structured data retrieval, factor construction, backtesting, and risk-report generation workflows.
- Built a full-stack financial research platform using React, FastAPI, PostgreSQL/TimescaleDB, Redis, and Docker Compose, enabling authenticated users to manage watchlists, trigger market data ingestion, and monitor data quality.
- Developed a reproducible backtesting module with baseline strategies, benchmark comparison, transaction-cost sensitivity analysis, and risk metrics including Sharpe ratio, maximum drawdown, volatility, and turnover.
- Integrated financial news sentiment with technical indicators to evaluate whether text-derived signals improve short-term strategy performance, with automated research memo generation and limitation analysis.

---

## 18. 风险与应对

| 风险 | 影响 | 应对方式 |
|---|---|---|
| 项目过大，做不完 | 无法形成展示闭环 | 先完成 Week 1 数据底座，再扩展 Agent |
| 只做聊天机器人 | 金融技术含量不足 | 必须加入数据、回测、风险指标 |
| 回测结果不好看 | 影响展示信心 | 强调方法论和风险评估，不强调盈利 |
| 数据源不稳定 | Demo 失败 | 本地缓存样例数据，支持 mock mode |
| Agent 输出不可靠 | 报告可信度下降 | 使用结构化 JSON schema 和工具调用日志 |
| 过度金融化 | 与原 AI 背景断裂 | 强调 AI for financial research 的迁移能力 |

---

## 19. 最终项目展示材料清单

申请前应准备以下材料：

1. GitHub 仓库。
2. README 首页截图。
3. 系统架构图。
4. 数据库 schema / ER 图。
5. Dashboard 截图。
6. 数据同步和数据质量检查截图。
7. 回测结果截图。
8. Agent 执行流程截图。
9. 一份自动生成的 research memo 样例。
10. 1–2 分钟 demo video。
11. 中文简历 bullet。
12. 英文简历 bullet。
13. 个人陈述中关于该项目的 1 段英文叙事。

---

## 20. 项目最终定位

本项目不应被描述为“量化交易机器人”，而应被描述为：

> A reproducible AI-powered financial research platform that combines LLM agents, financial data engineering, quantitative backtesting, and risk-aware research memo generation.

中文定位：

> 一个将大语言模型 Agent、金融时序数据工程、量化回测和风险分析结合起来的 AI 金融投研系统，用于把自然语言投资假设转化为可复现、可验证、可解释的研究流程。

该项目最适合承担你申请材料中的“金融科技背景补强”角色，同时不会削弱你原有 AI/大模型主线。它可以把你的个人叙事从“会做大模型项目的 CS 学生”升级为“能够将 AI 系统落地到金融科技场景的复合型申请者”。
