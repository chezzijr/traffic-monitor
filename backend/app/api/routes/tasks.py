"""Task management API routes."""

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from app.models.schemas import TaskListResponse
from app.services import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/", response_model=TaskListResponse)
def list_tasks() -> TaskListResponse:
    """List all training tasks."""
    tasks = task_service.list_tasks()
    return TaskListResponse(tasks=tasks)


@router.get("/{task_id}")
def get_task(task_id: str):
    """Get task details."""
    return task_service.get_task_status(task_id)


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str):
    """Cancel a running task."""
    return task_service.cancel_task(task_id)


@router.get("/{task_id}/stream")
async def stream_task(task_id: str) -> StreamingResponse:
    """Stream task progress via SSE."""
    return StreamingResponse(
        task_service.stream_task_updates(task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
