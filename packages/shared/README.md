# @finresearch/shared

FinResearch Agent monorepo 的内部共享包。存放跨前端 (`apps/web`) 与后端共用的 TypeScript 类型、常量与 [zod](https://zod.dev) schemas,作为单一事实来源 (single source of truth),避免前后端定义漂移。

## 目录结构

```
packages/shared/
├── src/
│   ├── types/        # 业务相关的 TypeScript 类型与接口
│   ├── schemas/      # zod 运行时校验 schema,并推导出类型
│   ├── constants/    # API 版本、默认基准、数据源、队列名等常量
│   └── index.ts      # 统一 re-export
├── package.json
├── tsconfig.json
└── README.md
```

## 使用方式

在 monorepo 内通过 workspace 协议引用:

```json
"dependencies": {
  "@finresearch/shared": "workspace:*"
}
```

```ts
import { AssetType, assetSchema, DEFAULT_BENCHMARKS, RISK_FREE_RATE } from '@finresearch/shared';
```

开发期可直接解析到 `src/index.ts`,构建后通过 `dist/index.js` 消费。
