FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN mkdir -p /data/backups/cloudflared /data/cloudflared

ENV APP_ENV=production \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    DATABASE_URL=sqlite:////data/tunneldeck.db \
    CLOUDFLARED_CONFIG_PATH=/data/cloudflared/config.yml \
    CLOUDFLARED_CONTROL_MODE=docker \
    CLOUDFLARED_DOCKER_CONTAINER_NAME=cloudflared \
    CLOUDFLARED_BACKUP_DIR=/data/backups/cloudflared \
    TUNNEL_CONFIG_LOCK_PATH=/data/backups/cloudflared/config.lock

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=3).status == 200 else 1)"

CMD ["sh", "-c", "exec uvicorn app.main:app --host ${APP_HOST:-0.0.0.0} --port ${APP_PORT:-8000}"]
