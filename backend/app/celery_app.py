"""Celery application configuration for background task processing."""

import os

from celery import Celery

# Redis broker URL from environment (default for local development)
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")

# Create Celery app instance
celery_app = Celery(
    "traffic_monitor",
    broker=CELERY_BROKER_URL,
    backend=CELERY_BROKER_URL,  # Use same Redis instance for result backend
)

# Celery configuration
celery_app.conf.update(
    # Task serialization settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone settings
    timezone="UTC",
    enable_utc=True,
    # Worker settings
    worker_concurrency=3,  # Max 3 concurrent workers for SUMO isolation
    worker_prefetch_multiplier=1,  # Disable prefetching for long-running tasks
    # Task settings
    task_track_started=True,  # Track when tasks start
    task_time_limit=3600,  # 1 hour hard limit
    task_soft_time_limit=3300,  # 55 min soft limit for graceful shutdown
    # Result settings
    result_expires=86400,  # Results expire after 24 hours
)

# Autodiscover tasks in app.tasks module
celery_app.autodiscover_tasks(["app.tasks"])
