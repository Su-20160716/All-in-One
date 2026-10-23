# 全能协作平台 —— 前端容器（多阶段：node 构建 → nginx 托管）
#
# D6：锁定依赖（COPY package-lock + npm ci）——CI/容器构建与本地
# package-lock 逐字节一致，不会「本地好好的、线上装出新版本」。
# Node 22 LTS；npm registry 可用构建参数切换（国内默认 npmmirror）。
FROM node:22-alpine AS build
WORKDIR /app
ARG NPM_REGISTRY=https://registry.npmmirror.com
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund --registry=$NPM_REGISTRY
COPY . .
# 构建期 API 基地址：同域部署（nginx 代理 /api）留空即可；
# 前后端分域部署时传 --build-arg VITE_API_BASE（如 https://api.example.com）
ARG VITE_API_BASE=
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
