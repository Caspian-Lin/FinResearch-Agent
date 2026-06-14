-- =============================================================================
-- FinResearch Agent — PostgreSQL / TimescaleDB 初始化脚本
-- =============================================================================
-- 挂载点：/docker-entrypoint-initdb.d/00-init.sql
-- 执行时机：仅在 postgres_data 数据卷为空时由 entrypoint 执行一次
--           （即首次 `docker compose up -d postgres`）。
--
-- 职责边界：
--   本脚本只负责创建 PostgreSQL 扩展，**不创建任何业务表**。
--   所有业务表（users / assets / market_ohlcv / data_quality_reports / ...）
--   都由 Alembic 迁移维护，请使用 `make migrate` 应用。
--
-- 修改注意：
--   修改本文件后必须 `make down -v` 清空数据卷才会重新执行。
--   生产环境永远不要这样做——请通过 Alembic 迁移增量变更。
-- =============================================================================

-- 启用 TimescaleDB 扩展（时序数据 hypertable）
-- 用于 market_ohlcv 等表，调用 create_hypertable() 自动按时间分区。
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 启用 uuid-ossp 扩展，提供 uuid_generate_v4()
-- 用于在数据库层生成 UUID 主键（users.id / assets.id 等）。
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 启用 citext 扩展（大小写不敏感文本）
-- 用于 users.email 等字段，保证 "User@Example.com" 与 "user@example.com"
-- 视作同一行，避免重复注册。可选。
CREATE EXTENSION IF NOT EXISTS citext;

-- 验证：\dx 可在 psql 中查看已安装扩展。
