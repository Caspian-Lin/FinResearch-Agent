"""Alembic 运行时环境。

被 `alembic -c /app/infra/migrations/alembic.ini upgrade|revision|...` 调用，
由 Alembic 在执行任何命令前 import 本模块。

主要职责：
1. 从环境变量 ``DATABASE_URL`` 读取数据库连接串（``alembic.ini`` 中
   ``sqlalchemy.url`` 故意留空，由本文件注入）。
2. 设置 ``target_metadata``，供 ``alembic revision --autogenerate`` 比对模型
   与数据库 schema 的差异。
3. 实现 offline / online 两种标准执行模式。

当前处于项目 skeleton 阶段：
- ``target_metadata`` 暂时为 ``None``，autogenerate 不会产出 diff。
- 等到 ``app/models/`` 下 ORM 模型齐备后，把下方 ``try/except`` 块中的注释
  打开即可启用。
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Alembic 配置对象（读取 alembic.ini）
# ---------------------------------------------------------------------------
config = context.config

# 配置日志（alembic.ini 中的 [loggers] 段）
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# target_metadata：autogenerate 比对的目标
# ---------------------------------------------------------------------------
# Importing app.models registers every model on Base.metadata so that
# `alembic revision --autogenerate` detects them. Requires the `app` package
# to be importable: in the api container WORKDIR=/app/apps/api; locally run
# alembic from apps/api (or put it on PYTHONPATH).
import app.models  # noqa: F401  — register models on Base.metadata
from app.db.base import Base

target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# 从环境变量读取数据库 URL，覆盖 alembic.ini 中的 sqlalchemy.url
# ---------------------------------------------------------------------------
DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://finresearch:finresearch_dev_password@postgres:5432/finresearch"
)

database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
config.set_main_option("sqlalchemy.url", database_url)


# ---------------------------------------------------------------------------
# offline 模式：生成 SQL 脚本而不连接数据库
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """以 'offline' 模式运行迁移。

    输出 SQL 到 stdout，不实际连接数据库。适合在 CI 中校验迁移正确性。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# online 模式：连接数据库直接执行
# ---------------------------------------------------------------------------
def run_migrations_online() -> None:
    """以 'online' 模式运行迁移。

    创建 engine、连接数据库、在事务中执行迁移。
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
