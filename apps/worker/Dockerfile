# ==============================================================================
# ATLAS Distributed Worker — Production Containerfile
# Multi-stage container build with headless browser and automation drivers
# ==============================================================================

# --- Stage 1: Build & Dependency Resolution ---
FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY apps ./apps

RUN uv sync --frozen --no-dev

# --- Stage 2: Production Worker Runtime ---
FROM python:3.11-slim AS runner

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ATLAS_HOME=/data \
    ATLAS_ARTIFACTS_DIR=/data/artifacts \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libxkbcommon0 \
    libpango-1.0-0 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 atlas \
    && useradd -u 10001 -g atlas -s /bin/bash -m atlas \
    && mkdir -p /data/artifacts \
    && chown -R atlas:atlas /data /app

# Copy virtual environment and code from builder
COPY --from=builder --chown=atlas:atlas /build/.venv /app/.venv
COPY --from=builder --chown=atlas:atlas /build/packages /app/packages
COPY --from=builder --chown=atlas:atlas /build/apps /app/apps
COPY --from=builder --chown=atlas:atlas /build/pyproject.toml /app/pyproject.toml

USER atlas

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "from pathlib import Path; assert b'atlas' in Path('/proc/1/cmdline').read_bytes()"

ENTRYPOINT ["atlas", "worker", "run"]
CMD ["--capabilities", "desktop,browser", "--heartbeat-interval", "5.0", "--poll-interval", "1.0"]
