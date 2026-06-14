# infra/docker

本目录存放 `docker-compose.yml` 中各服务所依赖的基础配置文件与初始化脚本。

这些文件以只读卷（`:ro`）的形式挂载到对应容器的固定路径上，仅在容器首次
启动或满足触发条件时被读取/执行。

## 目录结构

```
infra/docker/
├── README.md              # 本文件
├── postgres/
│   └── init.sql           # PostgreSQL 初始化脚本
└── redis/
    └── redis.conf         # Redis 自定义配置
```

## 文件挂载说明

| 文件 | 容器内挂载路径 | 触发时机 |
| --- | --- | --- |
| `postgres/init.sql` | `/docker-entrypoint-initdb.d/00-init.sql` | **仅在数据卷为空时**（即首次启动 `postgres_data` 卷）由 PostgreSQL 官方镜像的 entrypoint 按文件名字典序执行一次。重建容器不会重复执行；若想重跑必须先清空 `postgres_data` 卷（`make down -v`）。 |
| `redis/redis.conf` | `/usr/local/etc/redis/redis.conf` | 由 docker-compose 中 `command: ["redis-server", "/usr/local/etc/redis/redis.conf"]` 显式加载，每次 redis-server 启动都会读取。修改后 `docker compose restart redis` 即可生效。 |

## 职责划分

- **`postgres/init.sql`** 只负责创建 PostgreSQL 扩展（`timescaledb` /
  `uuid-ossp` / `citext`），**不创建任何业务表**。业务表（`users` /
  `assets` / `ohlcv` / `data_quality_reports` / ...）全部由
  Alembic 迁移在 `infra/migrations/versions/` 中维护，通过
  `make migrate` 应用。
- **`redis/redis.conf`** 定义 Redis 的内存上限、淘汰策略、AOF 持久化等
  行为。开发环境默认 `maxmemory 256mb` + `allkeys-lru`，足以支撑
  RQ 任务队列与短期缓存。

## 修改建议

- 修改 `init.sql` 后必须**清空 `postgres_data` 卷**才会重新执行：
  ```bash
  make down -v    # 注意：会清空所有数据
  make up
  ```
  生产环境永远不要这样做，请通过 Alembic 迁移增量变更。
- 修改 `redis.conf` 后只需 `docker compose restart redis`。
