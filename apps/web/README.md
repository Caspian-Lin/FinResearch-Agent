# @finresearch/web — React Dashboard

Vite + React 18 + TypeScript dashboard. Uses Ant Design for layout and
ECharts for price/drawdown/return visualizations.

## Layout

```text
apps/web/
  index.html
  vite.config.ts
  tsconfig.json
  src/
    main.tsx                # React root
    App.tsx                 # Layout shell + router
    routes/                 # Route components (Week 1+)
      Dashboard.tsx
      Watchlists.tsx
      DataQuality.tsx
      Backtests.tsx
      Memos.tsx
    components/             # Reusable components
      PriceChart.tsx
      SyncStatusBadge.tsx
    hooks/                  # Custom hooks (useAuth, useWatchlist, ...)
    api/                    # Typed API client (axios)
    store/                  # Zustand or Redux Toolkit store
    types/                  # Frontend-only types (shared types live in @finresearch/shared)
    utils/
    styles/
  Dockerfile
  nginx.conf
```

## Local Development

```bash
# From repo root
pnpm install
make web-dev                # Vite dev server with HMR
# Or via Docker
make up SERVICE=web
make logs SERVICE=web
```

Open http://localhost:5173 in your browser.

## Build for Production

```bash
pnpm --filter @finresearch/web build
# Output: apps/web/dist/ — served by nginx in the production Docker image
```

## Routes (planned)

| Path | Description |
|---|---|
| `/login` | User login form |
| `/` | Dashboard with price curves & sync status |
| `/watchlists` | Watchlist management |
| `/quality` | Data quality reports |
| `/backtests` | Backtest list & detail |
| `/memos` | Research memo viewer |
| `/agent` | LLM agent chat / plan viewer |
