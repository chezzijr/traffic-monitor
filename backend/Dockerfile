# Backend Dockerfile for Traffic Light Optimization Web App
# Uses Python 3.13 with SUMO traffic simulator and uv package manager

FROM python:3.13-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SUMO_HOME=/usr/share/sumo \
    PATH="/usr/share/sumo/bin:$PATH"

# Install system dependencies and SUMO
RUN apt-get update && apt-get install -y --no-install-recommends \
    sumo \
    sumo-tools \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files first for better layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies using uv
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY app/ ./app/

# Copy simulation files
COPY simulation/ ./simulation/

# Expose the API port
EXPOSE 8000

# Run the FastAPI application with uvicorn
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
