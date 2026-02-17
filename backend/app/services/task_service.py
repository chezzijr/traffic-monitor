"""Task service for managing Celery task state and queries.

This module provides functions for managing training tasks including:
- Creating and dispatching Celery tasks
- Querying task status and metadata
- Listing all tasks
- Cancelling running tasks
- Streaming task updates via Redis pub/sub
"""

import json
import logging
from datetime import datetime
from typing import Any, Generator

import redis
from celery.result import AsyncResult

from app.celery_app import celery_app
from app.tasks.training_task import train_traffic_light

logger = logging.getLogger(__name__)

# Redis key patterns
TASK_META_KEY = "task:{task_id}:meta"
TASK_UPDATES_CHANNEL = "task:{task_id}:updates"
TASKS_LIST_KEY = "tasks:list"


def get_redis_client() -> redis.Redis:
    """Get a Redis client for task operations.

    Returns:
        Redis client instance
    """
    from app.celery_app import CELERY_BROKER_URL

    return redis.from_url(CELERY_BROKER_URL)


def create_training_task(
    network_id: str,
    tl_id: str,
    algorithm: str = "dqn",
    total_timesteps: int = 10000,
    scenario: str = "moderate",
) -> dict[str, Any]:
    """Create and dispatch a training task.

    Args:
        network_id: ID of the SUMO network to train on
        tl_id: ID of the traffic light to optimize
        algorithm: RL algorithm to use ('dqn' or 'ppo')
        total_timesteps: Total timesteps to train for
        scenario: Traffic scenario for training

    Returns:
        dict with task_id, status, and created_at
    """
    # Dispatch Celery task
    async_result = train_traffic_light.delay(
        network_id=network_id,
        traffic_light_id=tl_id,
        algorithm=algorithm,
        total_timesteps=total_timesteps,
        scenario=scenario,
    )

    task_id = async_result.id
    created_at = datetime.now().isoformat()

    # Store task metadata in Redis
    metadata = {
        "network_id": network_id,
        "tl_id": tl_id,
        "algorithm": algorithm,
        "total_timesteps": total_timesteps,
        "scenario": scenario,
        "created_at": created_at,
    }

    redis_client = get_redis_client()
    redis_client.set(
        TASK_META_KEY.format(task_id=task_id),
        json.dumps(metadata),
    )

    # Add task ID to list (prepend for newest first)
    redis_client.lpush(TASKS_LIST_KEY, task_id)

    logger.info(f"Created training task: {task_id}")

    return {
        "task_id": task_id,
        "status": "PENDING",
        "created_at": created_at,
    }


def get_task(task_id: str) -> dict[str, Any] | None:
    """Get task status and metadata.

    Args:
        task_id: Celery task ID

    Returns:
        dict with task details or None if task doesn't exist
    """
    redis_client = get_redis_client()

    # Get task metadata from Redis
    meta_key = TASK_META_KEY.format(task_id=task_id)
    metadata_json = redis_client.get(meta_key)

    # Get Celery task state
    result = AsyncResult(task_id, app=celery_app)
    state = result.state
    info = result.info

    # If task is PENDING with no metadata, it doesn't exist
    if state == "PENDING" and metadata_json is None:
        return None

    # Parse metadata
    metadata = json.loads(metadata_json) if metadata_json else {}

    # Build result dict
    task_data = {
        "task_id": task_id,
        "status": state,
        "metadata": metadata,
        "info": {},
    }

    # Handle different states
    if state == "FAILURE":
        # For failed tasks, info is the exception
        task_data["error"] = str(info) if info else "Unknown error"
    elif info and isinstance(info, dict):
        task_data["info"] = info

    return task_data


def list_tasks(status: str | None = None) -> list[dict[str, Any]]:
    """List all tasks with their status.

    Args:
        status: Optional status filter (e.g., 'STARTED', 'SUCCESS')

    Returns:
        List of task dicts sorted by creation time (newest first)
    """
    redis_client = get_redis_client()

    # Get all task IDs from list
    task_ids = redis_client.lrange(TASKS_LIST_KEY, 0, -1)

    if not task_ids:
        return []

    tasks = []
    for task_id_bytes in task_ids:
        task_id = task_id_bytes.decode() if isinstance(task_id_bytes, bytes) else task_id_bytes

        # Get task metadata
        meta_key = TASK_META_KEY.format(task_id=task_id)
        metadata_json = redis_client.get(meta_key)

        # Get Celery state
        result = AsyncResult(task_id, app=celery_app)
        state = result.state
        info = result.info

        # Skip if status filter doesn't match
        if status and state != status:
            continue

        # Parse metadata
        metadata = json.loads(metadata_json) if metadata_json else {}

        task_data = {
            "task_id": task_id,
            "status": state,
            "metadata": metadata,
            "info": info if isinstance(info, dict) else {},
        }

        tasks.append(task_data)

    return tasks


def cancel_task(task_id: str) -> dict[str, Any]:
    """Cancel a running task.

    Args:
        task_id: Celery task ID to cancel

    Returns:
        dict with cancellation status

    Raises:
        ValueError: If task is already completed or failed
    """
    result = AsyncResult(task_id, app=celery_app)
    state = result.state

    if state == "SUCCESS":
        raise ValueError("Cannot cancel completed task")
    if state == "FAILURE":
        raise ValueError("Cannot cancel failed task")

    # Revoke the task with termination
    result.revoke(terminate=True)

    logger.info(f"Cancelled task: {task_id}")

    return {
        "status": "cancelled",
        "task_id": task_id,
    }


def get_task_stream(task_id: str) -> Generator[dict[str, Any], None, None]:
    """Get a generator for streaming task updates via Redis pub/sub.

    Args:
        task_id: Task ID to stream updates for

    Yields:
        dict with update data from Redis pub/sub

    Note:
        This generator should be consumed in a streaming context (e.g., SSE).
        It will yield messages until the task completes or fails.
    """
    redis_client = get_redis_client()
    pubsub = redis_client.pubsub()

    channel = TASK_UPDATES_CHANNEL.format(task_id=task_id)
    pubsub.subscribe(channel)

    try:
        for message in pubsub.listen():
            if message["type"] != "message":
                continue

            # Parse the message data
            data_bytes = message["data"]
            if isinstance(data_bytes, bytes):
                data = json.loads(data_bytes.decode())
            else:
                data = json.loads(data_bytes)

            yield data

            # Stop streaming when task completes or fails
            status = data.get("status", "")
            if status in ("completed", "failed", "cancelled"):
                break
    finally:
        pubsub.close()


def delete_task(task_id: str) -> dict[str, Any]:
    """Delete a task from Redis.

    Args:
        task_id: Task ID to delete

    Returns:
        dict with deletion status

    Raises:
        ValueError: If task is still running
    """
    result = AsyncResult(task_id, app=celery_app)
    state = result.state

    if state in ("PENDING", "STARTED"):
        raise ValueError("Cannot delete running task")

    redis_client = get_redis_client()

    # Remove metadata
    meta_key = TASK_META_KEY.format(task_id=task_id)
    redis_client.delete(meta_key)

    # Remove from task list
    redis_client.lrem(TASKS_LIST_KEY, 0, task_id)

    logger.info(f"Deleted task: {task_id}")

    return {
        "status": "deleted",
        "task_id": task_id,
    }


def cleanup_stale_tasks() -> dict[str, Any]:
    """Remove stale tasks that have no Celery state or metadata.

    Returns:
        dict with count of removed tasks
    """
    redis_client = get_redis_client()

    # Get all task IDs
    task_ids = redis_client.lrange(TASKS_LIST_KEY, 0, -1)

    removed = 0
    for task_id_bytes in task_ids:
        task_id = task_id_bytes.decode() if isinstance(task_id_bytes, bytes) else task_id_bytes

        # Get task metadata
        meta_key = TASK_META_KEY.format(task_id=task_id)
        metadata = redis_client.get(meta_key)

        # Get Celery state
        result = AsyncResult(task_id, app=celery_app)
        state = result.state

        # If PENDING with no metadata, it's stale
        if state == "PENDING" and metadata is None:
            redis_client.lrem(TASKS_LIST_KEY, 0, task_id)
            removed += 1
            logger.info(f"Removed stale task: {task_id}")

    return {"removed": removed}
