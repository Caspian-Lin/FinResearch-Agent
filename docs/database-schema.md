# Database Schema

> Ref: `FinResearch_Agent_项目描述文件.md` §9 数据设计

## Overview

关系型元数据存于 PostgreSQL,时序行情存于 TimescaleDB hypertable。
OLTP 风格表(`users` / `assets` / `watchlist` / `watchlist_items`)与追加型
分析表(`ohlcv`)分离。

所有业务表主键用 **UUID**(PG `gen_random_uuid()` server-side 生成),与业务
标识(symbol)解耦,以应对 corporate action(拆股 / 改名 / symbol 退市重用)——
这正是 FRA-13 将 FRA-5 的 `symbol PK` 改为 `asset_id UUID` 的原因。

## Core Tables

Week 1 已实现的表(见 `init_week1_schema` 迁移):

| 表名 | 主键 | 说明 |
|---|---|---|
| users | `id UUID` | 用户信息(`email` unique) |
| assets | `id UUID` | 资产元数据;`UNIQUE(symbol, exchange)` |
| watchlist | `id UUID` | 用户自选池;`UNIQUE(user_id, name)` |
| watchlist_items | `(watchlist_id, asset_id)` | 自选池与资产多对多 |
| ohlcv | `(asset_id, time, source)` | OHLCV 行情,TimescaleDB hypertable |

后续 issue 实现的表:`data_sync_jobs`、`data_quality_reports`、`factors`、
`backtest_runs`、`backtest_metrics`、`research_memos`(均以 `asset_id UUID`
外键引用 `assets(id)`)。

## Identity & Keys

- **UUID 主键**:`assets` / `users` / `watchlist` 用 `id UUID` 主键,server-side
  `gen_random_uuid()` 生成;关联表(`ohlcv` / `watchlist_items`)以 `asset_id` UUID
  外键引用 `assets(id)`。symbol 仅作业务标识,`UNIQUE(symbol, exchange)` 约束
  (不同交易所可能存在相同 symbol)。
- **ohlcv 复合主键**:`(asset_id, time, source)` 支持同一时点多数据源,且 `time`
  入主键满足 TimescaleDB hypertable 对分区列的要求。

## TimescaleDB Hypertables

```sql
CREATE TABLE ohlcv (
    asset_id   UUID          NOT NULL REFERENCES assets(id),
    time       TIMESTAMPTZ   NOT NULL,
    source     TEXT          NOT NULL,
    open       NUMERIC(20,6),
    high       NUMERIC(20,6),
    low        NUMERIC(20,6),
    close      NUMERIC(20,6),
    adjusted_close NUMERIC(20,6),
    volume     BIGINT,
    created_at TIMESTAMPTZ   DEFAULT now(),
    PRIMARY KEY (asset_id, time, source)
);

SELECT create_hypertable('ohlcv', 'time');
```

## Indexing Strategy

<!-- TODO: composite indexes on (asset_id, time), watchlist lookups, GIN/BRIN
     considerations for hypertables, retention policy. Ref: 项目描述文件 §9.2 -->

## Migration Workflow

<!-- TODO: Alembic 迁移编写/评审流程、Docker entrypoint 应用迁移、回滚策略、
     播种参考数据(benchmarks)。Ref: 项目描述文件 §13 -->
