"""Celery task definitions for training pipeline."""

from app.tasks.training_task import train_traffic_light, train_multi_junction

__all__ = ["train_traffic_light", "train_multi_junction"]
