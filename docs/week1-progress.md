# Week 1 Progress — Data Foundation & Dashboard

> Ref: `FinResearch_Agent_项目描述文件.md` §14 Week 1 & §15 第一周最小验收标准
> 与 `README.md` 的 [Week 1 Progress](../README.md#week-1-progress) 一致。

## Goals

Week 1：金融数据底座与 Dashboard。

目标：完成可登录、可同步、可展示行情数据的 Web 系统，并支持 English /
简体中文切换。**本项目不要求截图交付**，1 分钟 demo 以可复现的操作步骤
形式记录（见下文 Verification Checklist）。

## Deliverables

- [x] Docker Compose 环境（`docker-compose.yml`，可选；默认 local-first 开发）
- [x] FastAPI 后端（`apps/api`，路由 auth/assets/ohlcv/quality/sync/watchlists）
- [x] React Dashboard（`apps/web`，Ant Design + ECharts + i18next）
- [x] PostgreSQL + TimescaleDB（`ohlcv` hypertable）
- [x] 用户登录（JWT register/login + `get_current_user`）
- [x] 股票池管理（watchlist CRUD + ownership 强制，前端按 `asset_id` 管理）
- [x] OHLCV 数据同步（yfinance + RQ worker + 任务状态轮询）
- [x] 数据质量检查（缺失 bar + 异常统计 API）
- [x] 价格曲线展示（Line / Candle / Area + 成交量副图 + MA5/MA20，复权切换）
- [x] README 和 1 分钟 demo 步骤（**不要求截图**）
- [x] 国际化基础（`en` / `zh-CN` 运行时切换，见 README §Internationalization）

对应 Linear issue（均 Done）：FRA-5/13 schema、FRA-6 auth、FRA-7 assets、
FRA-8 sync、FRA-9 quality、FRA-10 watchlist API、FRA-11 dashboard、FRA-14
契约对齐、FRA-15 ohlcv 查询、FRA-16 watchlist 前端、FRA-17 auth 前端、
FRA-20 i18n、FRA-21 asset seed、FRA-24 图表样式扩展。

## Verification Checklist

第一周结束时，可按以下步骤复现 1 分钟 demo（与 README §1-Minute Demo 一致）：

- [x] 打开网页 http://localhost:5173
- [x] 在 Header 切换 English / 简体中文（即时生效、持久化，无需刷新）
- [x] 注册账号 → 登录（或用 seed 的 admin）
- [x] 进入 Watchlist，新建自选池，添加资产（如 `NVDA` / `AMD` / `QQQ`），按 `asset_id` 管理
- [x] 进入 Dashboard，从 watchlist 选择 asset
- [x] 点击 Sync Data，看到任务状态从 `running` 变成 `success`
- [x] Dashboard 价格曲线渲染（可切 Line/Candle/Area、成交量、MA、复权）
- [x] Data Quality 面板展示缺失值与异常点统计

第一周 GitHub README 至少包含（均已在 `README.md` 落实）：

- [x] Project motivation
- [x] Architecture
- [x] Tech stack
- [x] Data schema
- [x] How to run
- [x] Week 1 progress
- [x] Next steps
- [x]（**不包含**截图交付要求；demo 以步骤形式给出）

## Blockers

第一周实际遇到的阻碍与处置：

- **TimescaleDB 本地安装（WSL2）**：开发机无 Docker，本地直接装
  PostgreSQL + TimescaleDB 扩展；`ohlcv` hypertable 依赖 `create_hypertable()`，
  没有扩展则 migration 失败。已在 README How to Run 明确为前置依赖（非可选）。
- **yfinance IP 级 429 限流**：seed 验证时 `SPY` 等直接触发
  `YFRateLimitError`，同步可返回 0 bars。根因与缓解见下方已知限制，
  后续国内源适配器见 FRA-23。
- **sync 对 0 条数据误报 success**：限流/空响应时 task 仍返回
  `status: success`，前端假性成功、图表空白。已记录为 FRA-22（Backlog），
  在 README/本文档如实标注为已知限制，不隐瞒。

## Known Limitations

如实声明，避免误导：

- **数据源单一**：Week 1 仅 yfinance（延迟日线），`ohlcv.source` 字段已为
  多源预留但暂无第二来源；AkShare/Tushare 国内源、OpenBB/Stooq 计划中（FRA-23）。
- **yfinance 限流 → 假性成功**：见 Blockers。空 fetch 仍可能显示 success
  （FRA-22 未修），图表空白时优先怀疑数据源而非代码。
- **A 股字段/覆盖不完整**：yfinance 对 A 股质量参差，A 股序列需额外谨慎，
  待国内适配器落地（FRA-23）。
- **数据窗口手动指定**：同步需显式 `[start, end]`（inclusive），无自动
  历史回补。
- **质量检查不持久化**：Week 1 按需计算缺失/异常，不写
  `data_quality_reports`；覆盖率与异常指标为参考、非穷尽。
- **非交易/非投顾**：本项目不接入券商、不承诺盈利、不提供投资建议；
  所有结论绑定于明确的数据窗口、资产范围与假设。

## Next Week

Week 2 — 回测引擎与风险指标（ref: 项目描述文件 §14 Week 2）：

- 策略：Buy & Hold、Equal Weight、Moving Average、Momentum
- 基准对比（QQQ/SPY）
- 风险指标：Sharpe、Max Drawdown、Volatility、Turnover（含交易成本前后）
- 回测结果入库；回撤曲线与收益曲线展示

旁路跟进（非 Week 2 核心，但承接 Week 1 遗留）：FRA-22（空 fetch 假性
成功）、FRA-23（国内数据源适配层）。
