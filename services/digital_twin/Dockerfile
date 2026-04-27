# Digital Twin Video Analysis Service
# YOLO-based vehicle detection and speed estimation

FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ENV PYTHONPATH=/app

# System deps for OpenCV headless
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency definition first (layer cache)
COPY pyproject.toml uv.lock* ./

RUN uv sync --frozen --no-dev --no-install-project

# Copy source code
COPY . .

EXPOSE 8001

CMD ["uv", "run", "uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8001"]
