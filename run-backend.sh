#!/bin/bash
# run-backend.sh

cleanup() {
    echo "Stopping Backend and Redis..."
    docker stop dev-redis 2>/dev/null
    exit
}
trap cleanup SIGINT

echo "📦 Starting Redis container..."
docker run -d --rm --name dev-redis -p 6379:6379 redis:alpine

echo "🚀 Starting FastAPI Backend..."
cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000