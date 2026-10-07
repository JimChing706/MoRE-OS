# ============================================================
# MoRE v3.0 — Docker 部署配置
# Neuro-Symbolic Metacognitive Architecture
# ============================================================

# 构建阶段
FROM node:20-alpine AS builder

WORKDIR /app

# 安装依赖
COPY package*.json ./
RUN npm ci --only=production=false

# 复制源代码
COPY . .

# 构建
RUN npm run build

# 生产阶段
FROM nginx:alpine

# 安全：基础镜像 nginx:alpine 会滞后于 Alpine 安全仓库，导致镜像里残留
# 已修复的高危系统包（实测：libexpat CVE-2026-93990、pcre2 CVE-2026-103111，
# 二者在 alpine 安全仓库均有修复版本）。构建时统一升级消解。
RUN apk upgrade --no-cache

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制Nginx配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost:80/ || exit 1

EXPOSE 80

LABEL \
  app.name="MoRE v3.0 Agent OS" \
  app.version="3.0.0" \
  app.description="Neuro-Symbolic Metacognitive Architecture Console"
