FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /srv/frontend/dist
RUN useradd -m app && mkdir -p /srv/backend/data && chown -R app /srv/backend/data
USER app
ENV FRONTEND_DIST=/srv/frontend/dist CHROMA_PERSIST_DIR=/srv/backend/data/chroma \
    SQLITE_DB_PATH=/srv/backend/data/research.db CHECKPOINT_DB_PATH=/srv/backend/data/checkpoints.db \
    REPORTS_DIR=/srv/backend/data/reports
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
# single worker: live-run event buffers are in-process; scale vertically or add sticky sessions
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
