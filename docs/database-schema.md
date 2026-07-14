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
| factor_values | `(asset_id, factor_name, time, source)` | 因子值时序,TimescaleDB hypertable |
| news_items | `id UUID` | 新闻标题/摘要;`UNIQUE(asset_id, source, published_at, headline_hash)` |
| sentiment_scores | `id UUID` | classifier 情绪分;`UNIQUE(news_item_id, model_name)` |

后续 issue 实现的表:`data_sync_jobs`、`data_quality_reports`、
`research_memos`。`backtest_runs`、`backtest_metrics`、`equity_curve`、`trades`
已在 Week 2 migration 中实现;`factor_values` 已在 FRA-48 中实现。Week 3 给
`backtest_runs` 加了 `run_kind`(`backtest` / `sensitivity` / `factor_sensitivity` /
`factor_compute` / `factor_quantile` / `factor_sweep`,FRA-35/54/57)与
`result_json`(因子 worker 异步 job 的结构化结果,FRA-57)两列。Week 4 加了
`news_items` 与 `sentiment_scores`(FRA-66):前者持久化新闻标题/摘要,后者持久化
classifier 情绪分,均以 `asset_id` 外键关联到 `assets`。

### 文本与 sentiment 时间口径(Week 4 / FRA-66)

`news_items.published_at` 与 `sentiment_scores.published_at` 是文本信号的**最早可用
时间**(anti-cheat,与 FRA-65 契约一致):下游因子聚合只能把一条 sentiment 映射到
`published_at` 当天或之后的交易决策日,不得映射回更早交易日。`sentiment_scores.score`
归一到 `[-1, 1]`(负=bearish、0=neutral、正=bullish),`confidence` 归一到 `[0, 1]`,
`label ∈ {positive, neutral, negative}`;classifier 复现元数据(`model_name` /
`prompt_version` / 参数快照)存 `params`(JSONB),原始 provider/model 响应存
`raw_response`(JSONB)。两者为**普通关系表**(非 TimescaleDB hypertable)——news/
sentiment 是稀疏事件流,非 ohlcv / factor_values 那种连续追加时序;`headline_hash`
(sha256(headline))支撑内容去重,使重复抓取幂等。

## Identity & Keys

- **UUID 主键**:`assets` / `users` / `watchlist` 用 `id UUID` 主键,server-side
  `gen_random_uuid()` 生成;关联表(`ohlcv` / `watchlist_items`)以 `asset_id` UUID
  外键引用 `assets(id)`。symbol 仅作业务标识,`UNIQUE(symbol, exchange)` 约束
  (不同交易所可能存在相同 symbol)。
- **ohlcv 复合主键**:`(asset_id, time, source)` 支持同一时点多数据源,且 `time`
  入主键满足 TimescaleDB hypertable 对分区列的要求。
- **factor_values 复合主键**:`(asset_id, factor_name, time, source)` 支持同一
  资产、同一因子、同一时点的多计算来源/版本,且 `time` 入主键满足 TimescaleDB
  hypertable 对分区列的要求。`factor_name` 编码参数,例如 `momentum_21`、
  `rsi_14`、`macd`、`volatility_20d`。

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

```sql
CREATE TABLE factor_values (
    asset_id    UUID          NOT NULL REFERENCES assets(id),
    factor_name TEXT          NOT NULL,
    time        TIMESTAMPTZ   NOT NULL,
    value       NUMERIC(20,8) NOT NULL,
    source      TEXT          NOT NULL,
    created_at  TIMESTAMPTZ   DEFAULT now(),
    PRIMARY KEY (asset_id, factor_name, time, source)
);

SELECT create_hypertable('factor_values', 'time');

CREATE INDEX ix_factor_values_factor_name_time
    ON factor_values (factor_name, time);
CREATE INDEX ix_factor_values_asset_id_time
    ON factor_values (asset_id, time);
```

## Indexing Strategy

<!-- TODO: composite indexes on (asset_id, time), watchlist lookups, GIN/BRIN
     considerations for hypertables, retention policy. Ref: 项目描述文件 §9.2 -->

## Migration Workflow

<!-- TODO: Alembic 迁移编写/评审流程、Docker entrypoint 应用迁移、回滚策略、
     播种参考数据(benchmarks)。Ref: 项目描述文件 §13 -->
