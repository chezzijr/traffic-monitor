"""Task management API routes.

Provides endpoints for managing background training tasks:
- Create training tasks
- List and query tasks
- Stream task updates via SSE
- Cancel running tasks
"""

import json
import logging

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.models.schemas import (
    CancelTaskResponse,
    CreateTrainingTaskRequest,
    CreateTrainingTaskResponse,
    TaskInfo,
    TaskMetadata,
    TaskResponse,
)
from app.services import task_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post(
    "/training",
    response_model=CreateTrainingTaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create training task",
    description="Create and dispatch a new background training task.",
)
def create_training_task(request: CreateTrainingTaskRequest) -> CreateTrainingTaskResponse:
    """Create a new training task.

    The task will be dispatched to a Celery worker and run in the background.
    Progress can be monitored via the /tasks/{id}/stream SSE endpoint.
    """
    result = task_service.create_training_task(
        network_id=request.network_id,
        tl_id=request.traffic_light_id,
        algorithm=request.algorithm.value.lower(),
        total_timesteps=request.total_timesteps,
        scenario=request.scenario.value,
    )

    return CreateTrainingTaskResponse(
        task_id=result["task_id"],
        status=result["status"],
        created_at=result["created_at"],
    )


@router.get(
    "",
    response_model=list[TaskResponse],
    status_code=status.HTTP_200_OK,
    summary="List tasks",
    description="List all tasks with optional status filter.",
)
def list_tasks(
    status_filter: str | None = Query(
        None,
        alias="status",
        description="Filter by task status (PENDING, STARTED, SUCCESS, FAILURE, REVOKED)",
    ),
) -> list[TaskResponse]:
    """List all tasks with optional filtering.

    Returns tasks sorted by creation time (newest first).
    """
    tasks = task_service.list_tasks(status=status_filter)

    return [
        TaskResponse(
            task_id=task["task_id"],
            status=task["status"],
            metadata=TaskMetadata(**task.get("metadata", {})),
            info=TaskInfo(**task.get("info", {})) if isinstance(task.get("info"), dict) else TaskInfo(),
            error=task.get("error"),
        )
        for task in tasks
    ]


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Get task details",
    description="Get detailed information about a specific task.",
)
def get_task(task_id: str) -> TaskResponse:
    """Get details of a specific task.

    Returns full task information including metadata and runtime info.
    """
    task = task_service.get_task(task_id)

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found",
        )

    return TaskResponse(
        task_id=task["task_id"],
        status=task["status"],
        metadata=TaskMetadata(**task.get("metadata", {})),
        info=TaskInfo(**task.get("info", {})) if isinstance(task.get("info"), dict) else TaskInfo(),
        error=task.get("error"),
    )


async def _task_stream_generator(task_id: str):
    """SSE generator for task updates.

    Yields SSE events from Redis pub/sub until task completes.

    Args:
        task_id: ID of the task to stream updates for

    Yields:
        SSE-formatted event strings
    """
    try:
        for update in task_service.get_task_stream(task_id):
            event_type = update.get("status", "progress")

            # Map status to event type
            if event_type == "running":
                event_type = "progress"
            elif event_type == "completed":
                event_type = "completed"
            elif event_type == "failed":
                event_type = "error"
            elif event_type == "cancelled":
                event_type = "cancelled"

            yield f"event: {event_type}\ndata: {json.dumps(update)}\n\n"

            # Stop streaming on terminal states
            if update.get("status") in ("completed", "failed", "cancelled"):
                break

    except Exception as e:
        logger.error(f"Error streaming task {task_id}: {e}")
        error_data = {"error": str(e), "task_id": task_id}
        yield f"event: error\ndata: {json.dumps(error_data)}\n\n"


@router.get(
    "/{task_id}/stream",
    summary="Stream task updates via SSE",
    description="Stream real-time task updates via Server-Sent Events.",
)
async def stream_task(task_id: str) -> StreamingResponse:
    """Stream task updates via Server-Sent Events (SSE).

    Event types:
    - progress: Training progress update with timestep and metrics
    - metrics: Detailed training metrics (mean_reward, episode_count)
    - completed: Task completed successfully with model_path
    - error: Task failed with error message
    - cancelled: Task was cancelled

    The stream will automatically close when the task reaches a terminal state.
    """
    # Verify task exists
    task = task_service.get_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found",
        )

    return StreamingResponse(
        _task_stream_generator(task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/{task_id}/cancel",
    response_model=CancelTaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel task",
    description="Cancel a running or pending task.",
)
def cancel_task(task_id: str) -> CancelTaskResponse:
    """Cancel a running or pending task.

    Cannot cancel tasks that have already completed or failed.
    """
    try:
        result = task_service.cancel_task(task_id)
        return CancelTaskResponse(
            status=result["status"],
            task_id=result["task_id"],
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
