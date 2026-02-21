"""Task service for managing Celery task state and queries.

This module provides functions for managing training tasks including:
- Creating and dispatching Celery tasks
- Querying task status and metadata
- Listing all tasks
- Cancelling running tasks
- Caching task progress in Redis for SSE polling
"""

import json
import logging
from datetime import datetime
from typing import Any

import redis
from celery.result import AsyncResult

from app.celery_app import celery_app
from app.tasks.training_task import train_multi_junction, train_traffic_light

logger = logging.getLogger(__name__)

# Redis key patterns
TASK_META_KEY = "task:{task_id}:meta"
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
    tl_id: str | None = None,
    tl_ids: list[str] | None = None,
    mode: str = "single",
    algorithm: str = "dqn",
    total_timesteps: int = 10000,
    scenario: str = "moderate",
) -> dict[str, Any]:
    """Create and dispatch a training task.

    Dispatches either a single-junction or multi-junction Celery task based
    on the mode and provided traffic light IDs.

    Args:
        network_id: ID of the SUMO network to train on
        tl_id: ID of the traffic light to optimize (single-junction mode)
        tl_ids: List of traffic light IDs (multi-junction mode)
        mode: Training mode ('single' or 'all')
        algorithm: RL algorithm to use ('dqn' or 'ppo')
        total_timesteps: Total timesteps to train for
        scenario: Traffic scenario for training

    Returns:
        dict with task_id, status, and created_at
    """
    # Determine whether to dispatch single or multi-junction task
    use_multi = mode == "all" or (tl_ids is not None and len(tl_ids) > 1)

    if use_multi:
        if not tl_ids:
            raise ValueError("tl_ids must be provided for multi-junction training")
        async_result = train_multi_junction.delay(
            network_id=network_id,
            traffic_light_ids=tl_ids,
            algorithm=algorithm,
            total_timesteps=total_timesteps,
            scenario=scenario,
        )
    else:
        if not tl_id:
            raise ValueError("tl_id must be provided for single-junction training")
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
    metadata: dict[str, Any] = {
        "network_id": network_id,
        "tl_id": tl_id,
        "tl_ids": tl_ids,
        "mode": mode,
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

    logger.info(f"Created training task: {task_id} (mode={mode})")

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

    # Get progress from Redis (stored by training callback)
    progress_json = redis_client.get(f"task:{task_id}:progress")
    progress_data = json.loads(progress_json) if progress_json else {}

    # Build result dict
    task_data = {
        "task_id": task_id,
        "status": state,
        "metadata": metadata,
        "info": {
            "progress": progress_data.get("progress"),
            "timestep": progress_data.get("timestep"),
            "mean_reward": progress_data.get("mean_reward"),
            "episode_count": progress_data.get("episode_count"),
            "model_path": progress_data.get("model_path"),
            "avg_waiting_time": progress_data.get("avg_waiting_time"),
            "avg_queue_length": progress_data.get("avg_queue_length"),
            "throughput": progress_data.get("throughput"),
            "baseline_avg_waiting_time": progress_data.get("baseline_avg_waiting_time"),
            "baseline_avg_queue_length": progress_data.get("baseline_avg_queue_length"),
            "baseline_throughput": progress_data.get("baseline_throughput"),
        },
    }

    # Handle different states
    if state == "FAILURE":
        # For failed tasks, info is the exception
        task_data["error"] = str(info) if info else "Unknown error"

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

        # Get progress from Redis (stored by training callback)
        progress_json = redis_client.get(f"task:{task_id}:progress")
        progress_data = json.loads(progress_json) if progress_json else {}

        task_data = {
            "task_id": task_id,
            "status": state,
            "metadata": metadata,
            "info": {
                "progress": progress_data.get("progress"),
                "timestep": progress_data.get("timestep"),
                "mean_reward": progress_data.get("mean_reward"),
                "episode_count": progress_data.get("episode_count"),
                "model_path": progress_data.get("model_path"),
                "avg_waiting_time": progress_data.get("avg_waiting_time"),
                "avg_queue_length": progress_data.get("avg_queue_length"),
                "throughput": progress_data.get("throughput"),
                "baseline_avg_waiting_time": progress_data.get("baseline_avg_waiting_time"),
                "baseline_avg_queue_length": progress_data.get("baseline_avg_queue_length"),
                "baseline_throughput": progress_data.get("baseline_throughput"),
            },
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
