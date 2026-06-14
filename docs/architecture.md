# Architecture

FinResearch Agent is an AI-ready financial research platform that integrates market data ingestion, time-series storage, data quality monitoring, quantitative backtesting, LLM-agent-based research planning, and automated research memo generation.

> Ref: `FinResearch_Agent_项目描述文件.md` §6 系统架构

## High-Level Topology

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

## Service Breakdown

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

## Data Flow

<!-- TODO: document end-to-end request lifecycle from React dashboard → FastAPI → Redis queue → workers → TimescaleDB, including async task status polling. Ref: 项目描述文件 §6.2 -->

## Tech Stack Decisions

<!-- TODO: rationale for FastAPI + SQLAlchemy 2.0 + Pydantic, TimescaleDB over plain Postgres, Redis + RQ/Celery for async jobs, LangGraph for agent orchestration. Ref: 项目描述文件 §8 技术栈 -->

## Cross-Cutting Concerns

<!-- TODO: authentication/JWT, structured logging, error handling, configuration management, observability, security boundaries for agent code execution. Ref: 项目描述文件 §6 & §10.3 -->
