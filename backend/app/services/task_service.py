"""Service for managing Celery training tasks and Redis progress streaming."""

import asyncio
import json
import logging
from datetime import datetime

import redis

from app.config import settings

logger = logging.getLogger(__name__)


def _get_redis():
    return redis.Redis(host=settings.redis_host, port=settings.redis_port, decode_responses=True)


def create_training_task(
    network_id: str,
    tl_id: str,
    algorithm: str = "dqn",
    total_timesteps: int = 10000,
    scenario: str = "moderate",
) -> str:
    """Dispatch a single-junction training task to Celery."""
    from app.tasks.training_task import train_traffic_light

    result = train_traffic_light.delay(
        network_id=network_id,
        tl_id=tl_id,
        algorithm=algorithm,
        total_timesteps=total_timesteps,
        scenario=scenario,
    )
    return result.id


def create_multi_training_task(
    network_id: str,
    tl_ids: list[str],
    algorithm: str = "dqn",
    total_timesteps: int = 10000,
    scenario: str = "moderate",
) -> str:
    """Dispatch a multi-junction training task to Celery."""
    from app.tasks.training_task import train_multi_junction

    result = train_multi_junction.delay(
        network_id=network_id,
        tl_ids=tl_ids,
        algorithm=algorithm,
        total_timesteps=total_timesteps,
        scenario=scenario,
    )
    return result.id


def get_task_status(task_id: str) -> dict:
    """Get task status from Celery + Redis cached progress."""
    from celery.result import AsyncResult
    from app.celery_app import celery_app

    result = AsyncResult(task_id, app=celery_app)
    r = _get_redis()

    # Get cached progress from Redis
    progress_json = r.get(f"task:{task_id}:progress")
    progress = json.loads(progress_json) if progress_json else {}

    # Get metadata
    meta_json = r.get(f"task:{task_id}:meta")
    meta = json.loads(meta_json) if meta_json else {}

    status = result.status  # PENDING, STARTED, SUCCESS, FAILURE, REVOKED
    if progress.get("status") == "completed":
        status = "completed"
    elif progress.get("status") == "failed":
        status = "failed"
    elif progress.get("status") == "running":
        status = "running"

    return {
        "task_id": task_id,
        "status": status.lower(),
        "network_id": meta.get("network_id"),
        "algorithm": meta.get("algorithm"),
        "tl_ids": meta.get("tl_ids", []),
        "total_timesteps": meta.get("total_timesteps"),
        "progress": progress.get("progress", 0.0),
        "created_at": meta.get("created_at"),
        "error": progress.get("error"),
        "model_path": progress.get("model_path"),
    }


def cancel_task(task_id: str) -> dict:
    """Revoke a Celery task."""
    from app.celery_app import celery_app

    celery_app.control.revoke(task_id, terminate=True)
    r = _get_redis()

    cancel_payload = json.dumps({
        "task_id": task_id,
        "status": "cancelled",
    })
    r.publish(f"task:{task_id}:updates", cancel_payload)
    r.setex(f"task:{task_id}:progress", 3600, cancel_payload)

    return {"task_id": task_id, "status": "cancelled"}


def list_tasks() -> list[dict]:
    """List all task IDs from Redis."""
    r = _get_redis()
    task_ids = r.lrange("tasks:list", 0, -1)
    tasks = []
    for task_id in task_ids:
        try:
            status = get_task_status(task_id)
            tasks.append(status)
        except Exception:
            tasks.append({"task_id": task_id, "status": "unknown"})
    return tasks


async def stream_task_updates(task_id: str):
    """Async generator for SSE streaming via Redis pub/sub."""
    r = _get_redis()
    pubsub = r.pubsub()
    pubsub.subscribe(f"task:{task_id}:updates")

    try:
        while True:
            message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message["type"] == "message":
                data = message["data"]

                # Determine SSE event name from payload status
                event_name = "progress"
                terminal = False
                try:
                    payload = json.loads(data)
                    status = payload.get("status")
                    if status == "completed":
                        event_name = "complete"
                        terminal = True
                    elif status in ("failed", "cancelled"):
                        event_name = "error"
                        terminal = True
                    elif status == "running":
                        event_name = "progress"
                except (json.JSONDecodeError, KeyError):
                    pass

                yield f"event: {event_name}\ndata: {data}\n\n"

                if terminal:
                    return

            # Heartbeat
            yield f"event: heartbeat\ndata: {{}}\n\n"
            await asyncio.sleep(1)
    finally:
        pubsub.unsubscribe(f"task:{task_id}:updates")
        pubsub.close()
