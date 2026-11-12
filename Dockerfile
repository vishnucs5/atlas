# ATLAS Production Runtime Containerfile
FROM python:3.11-slim

# Set environment flags
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    ATLAS_HOME=/data \
    ATLAS_DB_PATH=/data/atlas.db \
    ATLAS_ARTIFACTS_DIR=/data/artifacts

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    sqlite3 \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency configuration and source tree
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY apps ./apps

# Install dependencies using uv workspace
RUN uv sync --frozen --no-dev

# Place virtual environment binaries on PATH
ENV PATH="/app/.venv/bin:$PATH"

# Create data directories
RUN mkdir -p /data/artifacts

# Expose API port
EXPOSE 8000

# Default command launches ATLAS API Service
CMD ["uvicorn", "atlas_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
