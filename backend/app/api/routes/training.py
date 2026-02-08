"""ML Training API routes."""

import asyncio
import json

from fastapi import APIRouter, HTTPException, Path, status
from fastapi.responses import StreamingResponse

from app.models.schemas import (
    DeploymentInfo,
    DeployRequest,
    ModelInfo,
    ToggleAIRequest,
    TrainingJobInfo,
    TrainingStartRequest,
    TrainingStatusResponse,
)
from app.services import deployment_service, ml_service

router = APIRouter(tags=["training"])


@router.post(
    "/training/start",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Start training job",
    description="Start a new RL training job for a traffic light.",
)
def start_training(request: TrainingStartRequest) -> dict:
    """Start a training job."""
    try:
        result = ml_service.start_training(
            network_id=request.network_id,
            tl_id=request.tl_id,
            algorithm=request.algorithm.value,
            total_timesteps=request.total_timesteps,
        )
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/training/stop",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Stop training job",
    description="Stop the currently running training job.",
)
def stop_training() -> dict:
    """Stop the current training job."""
    try:
        return ml_service.stop_training()
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/training/status",
    response_model=TrainingStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get training status",
    description="Get the current training job status and metrics.",
)
def get_training_status() -> TrainingStatusResponse:
    """Get current training status."""
    result = ml_service.get_training_status()
    job_data = result.get("job")
    job = TrainingJobInfo(**job_data) if job_data else None
    return TrainingStatusResponse(status=result["status"], job=job)


async def _training_status_generator():
    """SSE generator for training status updates."""
    try:
        while True:
            result = ml_service.get_training_status()
            yield f"event: status\ndata: {json.dumps(result)}\n\n"

            # Stop streaming if training is not running
            if result["status"] not in ("running", "stopping"):
                yield f"event: completed\ndata: {json.dumps(result)}\n\n"
                break

            await asyncio.sleep(1.0)  # Update every second
    except Exception as e:
        error_data = {"error": str(e)}
        yield f"event: error\ndata: {json.dumps(error_data)}\n\n"


@router.get(
    "/training/status/stream",
    summary="Stream training status via SSE",
    description="Stream training status updates via Server-Sent Events.",
)
async def stream_training_status() -> StreamingResponse:
    """Stream training status via SSE."""
    return StreamingResponse(
        _training_status_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/models",
    response_model=list[ModelInfo],
    status_code=status.HTTP_200_OK,
    summary="List trained models",
    description="List all available trained models.",
)
def list_models() -> list[ModelInfo]:
    """List all trained models."""
    models = ml_service.list_models()
    return [ModelInfo(id=m["filename"].replace(".zip", ""), **m) for m in models]


@router.get(
    "/models/{model_id}",
    response_model=ModelInfo,
    status_code=status.HTTP_200_OK,
    summary="Get model details",
    description="Get details of a specific trained model.",
)
def get_model(model_id: str = Path(..., description="Model ID (filename without .zip)")) -> ModelInfo:
    """Get a specific model's details."""
    models = ml_service.list_models()
    for m in models:
        if m["filename"].replace(".zip", "") == model_id:
            return ModelInfo(id=model_id, **m)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Model '{model_id}' not found")


@router.delete(
    "/models/{model_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Delete model",
    description="Delete a trained model.",
)
def delete_model(model_id: str = Path(..., description="Model ID (filename without .zip)")) -> dict:
    """Delete a trained model."""
    # Find model path
    models = ml_service.list_models()
    model_path = None
    for m in models:
        if m["filename"].replace(".zip", "") == model_id:
            model_path = m["path"]
            break

    if not model_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Model '{model_id}' not found")

    try:
        return ml_service.delete_model(model_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/models/{model_id}/deploy",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Deploy model to traffic light",
    description="Deploy a trained model to control a specific traffic light.",
)
def deploy_model(
    request: DeployRequest,
    model_id: str = Path(..., description="Model ID (filename without .zip)"),
) -> dict:
    """Deploy a model to a traffic light."""
    # Find model path
    models = ml_service.list_models()
    model_path = None
    for m in models:
        if m["filename"].replace(".zip", "") == model_id:
            model_path = m["path"]
            break

    if not model_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{model_id}' not found",
        )

    try:
        return deployment_service.deploy_model(model_path, request.tl_id)
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/models/{model_id}/undeploy",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Undeploy model",
    description="Remove a model deployment from its traffic light.",
)
def undeploy_model(
    model_id: str = Path(..., description="Model ID (filename without .zip)"),
) -> dict:
    """Undeploy a model from its traffic light."""
    # Find which TL this model is deployed to
    deployments = deployment_service.get_deployments()
    tl_id = None
    for d in deployments:
        if d["model_id"] == model_id:
            tl_id = d["tl_id"]
            break

    if not tl_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{model_id}' is not deployed",
        )

    try:
        return deployment_service.undeploy_model(tl_id)
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/deployment/status",
    response_model=list[DeploymentInfo],
    status_code=status.HTTP_200_OK,
    summary="Get deployment status",
    description="Get all active model deployments.",
)
def get_deployment_status() -> list[DeploymentInfo]:
    """Get all active deployments."""
    deployments = deployment_service.get_deployments()
    return [DeploymentInfo(**d) for d in deployments]


@router.post(
    "/deployment/toggle",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Toggle AI control",
    description="Enable or disable AI control for a deployed traffic light.",
)
def toggle_ai_control(request: ToggleAIRequest) -> dict:
    """Toggle AI control for a traffic light."""
    try:
        return deployment_service.toggle_ai_control(request.tl_id, request.enabled)
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
