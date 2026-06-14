# Database Schema

> Ref: `FinResearch_Agent_项目描述文件.md` §9 数据设计

## Overview

<!-- TODO: introduce the persistence layer design — relational metadata in PostgreSQL, time-series market data in TimescaleDB hypertables, separation between OLTP-style tables and append-only analytical tables. Ref: 项目描述文件 §9 -->

## Core Tables

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

## TimescaleDB Hypertables

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

## Indexing Strategy

<!-- TODO: document composite indexes on (asset_id, time), indexes for watchlist lookups, GIN/BRIN considerations for hypertables, retention policy. Ref: 项目描述文件 §9.2 -->

## Migration Workflow

<!-- TODO: Alembic migration authoring and review workflow, applying migrations inside Docker entrypoint, rollback strategy, seeding reference data (assets, benchmarks). Ref: 项目描述文件 §13 项目目录结构 -->
