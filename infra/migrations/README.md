# infra/migrations

Alembic 数据库迁移工作目录。

本目录被 `apps/api` 容器通过 `/app/infra/migrations/alembic.ini` 调用
（见根目录 `Makefile` 与 `docker-compose.yml` 中的卷映射
`./infra/migrations:/app/infra/migrations:cached`）。

## 目录结构

```
infra/migrations/
├── README.md            # 本文件
├── alembic.ini          # Alembic 配置（script_location=.，从 env.py 读 DATABASE_URL）
├── env.py               # 运行时环境：读取 DATABASE_URL、注入 target_metadata
├── script.py.mako       # 自动生成迁移文件的 Mako 模板
└── versions/            # 自动生成的迁移脚本（首次 `make migrate-new` 后填充）
    └── .gitkeep
```

## 常用命令

所有命令通过 `Makefile` 封装，先在容器内执行 `alembic`：

```bash
# 应用所有未执行的迁移到最新版本
make migrate

# 基于当前 ORM 模型自动生成新迁移（autogenerate）
make migrate-new NAME=add_user_table

# 回滚最近一个迁移
make migrate-down
```

对应的实际命令（在 `apps/api` 容器内执行）：

```bash
alembic -c /app/infra/migrations/alembic.ini upgrade head
alembic -c /app/infra/migrations/alembic.ini revision --autogenerate -m "<name>"
alembic -c /app/infra/migrations/alembic.ini downgrade -1
```

## 环境变量

**应用迁移前必须先设置 `DATABASE_URL`**，例如在仓库根目录的 `.env` 中：

```bash
DATABASE_URL=postgresql+psycopg://finresearch:finresearch_dev_password@postgres:5432/finresearch
```

`env.py` 中的默认值与上述一致，仅供本机/容器内 fallback，正式环境务必通过
环境变量覆盖。

## target_metadata 与 autogenerate

`env.py` 中 `target_metadata` 默认为 `None`（skeleton 阶段）。当 ORM 模型
齐备后，需要把：

```python
from app.db.base import Base
# 显式 import 所有模型，保证 Base.metadata 已注册
import app.models  # noqa: F401
target_metadata = Base.metadata
```

打开注释后，`make migrate-new` 才能 autogenerate 出真实 diff。
当前阶段可以先手写迁移，或在 `versions/` 中放入初始 schema。

## 文件命名

`alembic.ini` 中已配置 `file_template`，迁移文件名形如：

```
2026_06_14_0130-abcdef_initial_schema.py
```

便于按时间排序查看演化历史。
