# syntax=docker/dockerfile:1.7
# Multi-stage build for the React frontend.
#   dev    — Vite dev server with HMR, used by docker-compose
#   build  — Compile production bundle
#   prod   — nginx serving static assets + /api reverse proxy

ARG NODE_VERSION=20

# ---------- base ----------
FROM node:${NODE_VERSION}-alpine AS base
WORKDIR /workspace
RUN corepack enable && corepack prepare pnpm@9.12.0 --activate
# Configure Taobao npm mirror
RUN pnpm config set registry https://registry.npmmirror.com/

# ---------- deps ----------
FROM base AS deps
COPY package.json pnpm-workspace.yaml .npmrc ./
COPY apps/web/package.json ./apps/web/package.json
COPY packages/shared/package.json ./packages/shared/package.json
RUN pnpm install --frozen-lockfile || pnpm install

# ---------- dev ----------
FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["pnpm", "--filter", "@finresearch/web", "dev", "--host", "0.0.0.0"]

# ---------- build ----------
FROM deps AS builder
COPY . .
RUN pnpm --filter @finresearch/web build

# ---------- prod (nginx) ----------
FROM nginx:1.27-alpine AS prod
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /workspace/apps/web/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -q --spider http://localhost/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
