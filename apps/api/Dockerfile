# ==============================================================================
# ATLAS API Service — Production Containerfile
# Multi-stage minimal container build for production execution
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

# --- Stage 2: Production Distroless/Minimal Runtime ---
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

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/readyz || exit 1

ENTRYPOINT ["uvicorn", "atlas_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
