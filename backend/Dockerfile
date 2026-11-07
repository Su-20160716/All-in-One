# 全能协作平台 —— 后端容器
FROM python:3.13-slim

WORKDIR /app
# 默认按生产模式启动：DEBUG 关闭、域名与密钥由运行时环境变量注入。
# 本地想用这个镜像调试时显式传 -e DJANGO_DEBUG=1。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=0

# 优先按 lock 安装，保证构建可复现；requirements.txt 仅作为 lock 缺失时的兜底
COPY requirements.lock requirements.txt ./
RUN if [ -s requirements.lock ]; then \
        pip install --no-cache-dir -r requirements.lock; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

COPY . .

# 构建期收集静态文件（生产 DEBUG=0 时由 WhiteNoise 托管）
# 构建阶段没有运行时密钥/域名，这里只注入一次性占位值，不写入镜像环境
RUN DJANGO_SECRET_KEY=build-only-collectstatic DJANGO_ALLOWED_HOSTS=* \
    python manage.py collectstatic --noinput

EXPOSE 8000
# 容器探活（#129）：daphne 卡死/事件循环阻塞时进程仍在，容器却显示 running。
# 用标准库请求 /api/core/health/（免登录，含 DB 探测）；带上 X-Forwarded-Proto
# 以免生产分支的 SECURE_SSL_REDIRECT 把健康检查 301 到 https 导致误判。
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request as u,sys; r=u.Request('http://127.0.0.1:8000/api/core/health/', headers={'X-Forwarded-Proto':'https'}); sys.exit(0 if u.urlopen(r, timeout=4).status == 200 else 1)"
# 每次启动先迁移+初始化（幂等），再以 Daphne(ASGI) 启动以支持 WebSocket
CMD sh -c "python manage.py migrate --noinput && python manage.py seed && daphne -b 0.0.0.0 -p 8000 config.asgi:application"
