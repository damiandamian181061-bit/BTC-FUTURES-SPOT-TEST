# syntax=docker/dockerfile:1
# One image: the Vite front end is built in a Node stage, then served by the FastAPI backend from a slim Python image.
#   docker compose up -d --build      -> http://127.0.0.1:8000  (API docs at /docs)
# Data, charts and the API-key file are mounted at run time (docker-compose.yml); nothing secret is baked in.

# ---------------------------------------------------------------- 1. front end
FROM node:24-alpine AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- 2. backend + built front end
FROM python:3.13-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg \
    BTC_BOT_ROOT=/app \
    BTC_BOT_DATA_DIR=/app/data \
    BTC_BOT_CHARTS_DIR=/app/charts \
    BTC_BOT_FRONTEND_DIST=/app/frontend/dist
WORKDIR /app

COPY backend/pyproject.toml backend/README.md backend/
COPY backend/src backend/src
RUN pip install "./backend[api,dev]"

COPY backend/tests backend/tests
COPY STRATEGY_RULES.md ./
COPY --from=web /src/frontend/dist frontend/dist

RUN useradd --create-home --uid 1000 app && mkdir -p data charts && chown app:app data charts
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "btc_bot.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
