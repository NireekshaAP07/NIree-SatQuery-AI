# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
# SatQuery AI — Backend Docker Image
# Supports: linux/arm64 (Oracle Cloud Free VM) & linux/amd64 (local dev)
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# System dependencies: GDAL, PostgreSQL client, build tools
# BuildKit cache mount: apt packages are cached between builds —
# only downloaded once, never re-fetched on code-only changes.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    libpq-dev \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set GDAL env vars so rasterio/geopandas find the system GDAL
ENV GDAL_VERSION=3.6.2
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

# Production settings
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GUNICORN_WORKERS=2 \
    GUNICORN_THREADS=2 \
    GUNICORN_TIMEOUT=120 \
    GUNICORN_KEEPALIVE=5

WORKDIR /app

# Copy requirements FIRST — this layer is cached as long as requirements.txt
# doesn't change. Code changes do NOT trigger a pip re-install.
COPY requirements.txt .

# BuildKit pip cache: downloaded wheels are cached between builds.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install GDAL==$(gdal-config --version) \
    && pip install -r requirements.txt

# Copy source code last — only this layer rebuilds on code changes.
COPY . .

# ⚠️  IMPORTANT: data/raw is the dataset drop zone for manual user uploads.
# Mount this directory as a Docker volume so data persists across restarts.
VOLUME ["/app/data"]

EXPOSE 8000

# Use gunicorn with uvicorn workers for production
CMD ["sh", "-c", "gunicorn app.main:app \
    --workers ${GUNICORN_WORKERS:-2} \
    --worker-class uvicorn.workers.UvicornWorker \
    --threads ${GUNICORN_THREADS:-2} \
    --timeout ${GUNICORN_TIMEOUT:-120} \
    --keep-alive ${GUNICORN_KEEPALIVE:-5} \
    --bind 0.0.0.0:8000 \
    --access-logfile - \
    --error-logfile - \
    --log-level info"]
