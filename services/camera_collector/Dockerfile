# Camera Collector Service
# Async worker to fetch HCMC traffic camera snapshots

FROM python:3.13-slim AS base

# Prevent Python from buffering logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ENV PYTHONPATH=/app

# Install uv (same as backend for consistency)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency definition first (layer cache)
COPY pyproject.toml uv.lock ./

# Install dependencies only (no project install)
RUN uv sync --frozen --no-dev --no-install-project

# Copy source code
COPY . .

# Create dataset directory inside container
RUN mkdir -p /data/dataset

# Run collector loop
CMD ["uv", "run", "python", "-m", "service.main"]
