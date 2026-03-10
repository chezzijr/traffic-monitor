#!/bin/bash
# run-service.sh

echo "🚀 Starting Camera Collector Service..."
cd services/camera_collector && uv run python -m service.main