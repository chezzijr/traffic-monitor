"""Training API routes."""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.models.schemas import (
    MultiJunctionTrainingRequest,
    TrainingRequest,
    TrainingTaskResponse,
)
from app.services import validation_service, task_service

router = APIRouter(prefix="/training", tags=["training"])


@router.post("/single", response_model=TrainingTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def start_single_training(request: TrainingRequest) -> TrainingTaskResponse:
    """Start single-junction training."""
    errors = validation_service.validate_training_request(
        request.network_id, request.tl_id, request.algorithm,
    )
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    task_id = task_service.create_training_task(
        network_id=request.network_id,
        tl_id=request.tl_id,
        algorithm=request.algorithm,
        total_timesteps=request.total_timesteps,
        scenario=request.scenario.value,
    )
    return TrainingTaskResponse(task_id=task_id, status="queued")


@router.post("/multi", response_model=TrainingTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def start_multi_training(request: MultiJunctionTrainingRequest) -> TrainingTaskResponse:
    """Start multi-junction training."""
    errors = validation_service.validate_multi_training_request(
        request.network_id, request.tl_ids, request.algorithm,
    )
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    task_id = task_service.create_multi_training_task(
        network_id=request.network_id,
        tl_ids=request.tl_ids,
        algorithm=request.algorithm,
        total_timesteps=request.total_timesteps,
        scenario=request.scenario.value,
    )
    return TrainingTaskResponse(task_id=task_id, status="queued")


@router.get("/status/{task_id}")
def get_training_status(task_id: str):
    """Get training task status."""
    return task_service.get_task_status(task_id)


@router.get("/stream/{task_id}")
async def stream_training(task_id: str) -> StreamingResponse:
    """Stream training progress via SSE."""
    return StreamingResponse(
        task_service.stream_task_updates(task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
