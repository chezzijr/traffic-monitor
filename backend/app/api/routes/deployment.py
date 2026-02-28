"""Deployment API routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models.schemas import DeployModelRequest, ToggleAIControlRequest
from app.services import deployment_service

router = APIRouter(prefix="/deployment", tags=["deployment"])


class UndeployRequest(BaseModel):
    """Request to undeploy a model from a traffic light."""

    tl_id: str = Field(..., description="Traffic light to undeploy from")


@router.get("/")
def list_deployments() -> list[dict]:
    """List all active deployments."""
    return deployment_service.list_deployments()


@router.post("/deploy")
def deploy_model(request: DeployModelRequest) -> dict:
    """Deploy a trained model to a traffic light."""
    try:
        return deployment_service.deploy_model(
            tl_id=request.tl_id,
            model_path=request.model_path,
            network_id=request.network_id,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/undeploy")
def undeploy_model(request: UndeployRequest) -> dict:
    """Remove a deployed model from a traffic light."""
    try:
        return deployment_service.undeploy_model(tl_id=request.tl_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{tl_id}/toggle")
def toggle_ai_control(tl_id: str, request: ToggleAIControlRequest) -> dict:
    """Toggle AI control for a deployed model."""
    try:
        return deployment_service.toggle_ai_control(tl_id=tl_id, enabled=request.enabled)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
