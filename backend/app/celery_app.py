"""Celery application configuration."""

from celery import Celery

from app.config import settings

celery_app = Celery(
    "traffic_monitor",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
)

celery_app.autodiscover_tasks(["app.tasks"])
