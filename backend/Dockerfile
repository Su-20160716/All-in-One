# 全能协作平台 —— 后端容器
FROM python:3.13-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=1 \
    DJANGO_ALLOWED_HOSTS=*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 构建期收集静态文件（生产 DEBUG=0 时由 WhiteNoise 托管）
RUN python manage.py collectstatic --noinput

EXPOSE 8000
# 每次启动先迁移+初始化（幂等），再以 Daphne(ASGI) 启动以支持 WebSocket
CMD sh -c "python manage.py migrate --noinput && python manage.py seed && daphne -b 0.0.0.0 -p 8000 config.asgi:application"
