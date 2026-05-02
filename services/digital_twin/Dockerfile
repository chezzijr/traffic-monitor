# Digital Twin Video Analysis Service
# YOLO-based vehicle detection and speed estimation

FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SUMO_HOME=/usr/share/sumo \
    PATH="/usr/share/sumo/bin:$PATH"

ENV PYTHONPATH=/app

# System deps for OpenCV + SUMO
RUN apt-get update && apt-get install -y --no-install-recommends \
    sumo \
    sumo-tools \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.6.8 /uv /uvx /bin/

WORKDIR /app

# Copy dependency definition first (layer cache)
COPY pyproject.toml uv.lock .python-version ./

ENV UV_HTTP_TIMEOUT=600
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Copy source code
COPY . .

EXPOSE 8001

CMD ["uv", "run", "uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8001"]
