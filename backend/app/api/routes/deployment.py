"""Deployment API routes.

All simulation control is delegated to the Digital Twin service.
Backend acts as a thin proxy + stores deployment state in Redis.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.models.schemas import DeployModelRequest, ToggleAIControlRequest
from app.services import deployment_service
from app.services.deployment_service import DeployConflictError

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
    """Deploy a trained model — forwards to Digital Twin service.

    Always issues stop-then-start so consecutive deploys swap cleanly.
    Returns 409 if DT still reports an active deploy after the stop call
    (race condition; frontend should retry once).
    """
    try:
        return deployment_service.deploy_model(
            tl_id=request.tl_id,
            model_path=request.model_path,
            network_id=request.network_id,
            grid_rows=request.grid_rows,
            grid_cols=request.grid_cols,
        )
    except DeployConflictError as e:
        raise HTTPException(status_code=409, detail=e.detail)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/precheck")
def precheck(
    model_id: str | None = Query(
        None,
        description="Reserved for future per-model checks; currently unused — DT video file is global.",
    ),
) -> dict:
    """Pre-flight check before deploy: verifies the DT video file exists.

    Used by the frontend Deploy button to block early when git-LFS files
    are missing. ``model_id`` is accepted for forward-compat but ignored —
    the video file is currently a single global path in the DT config.
    """
    return deployment_service.precheck_video()


@router.post("/undeploy")
def undeploy_model(request: UndeployRequest) -> dict:
    """Remove a deployed model from a traffic light."""
    try:
        return deployment_service.undeploy_model(tl_id=request.tl_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/stop-all")
def stop_all_deployments() -> dict:
    """Stop the active DT deploy and wipe all Redis deployment entries.

    Single-button shutdown of the whole pipeline. Idempotent — returns
    success even if nothing is running.
    """
    return deployment_service.stop_all_deployments()


@router.post("/{tl_id}/toggle")
def toggle_ai_control(tl_id: str, request: ToggleAIControlRequest) -> dict:
    """Toggle AI control for a deployed model."""
    try:
        return deployment_service.toggle_ai_control(tl_id=tl_id, enabled=request.enabled)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{tl_id}/snapshot")
def get_deployment_snapshot(tl_id: str) -> dict:
    """Get a live snapshot — proxied from Digital Twin service."""
    try:
        return deployment_service.get_deployment_snapshot(tl_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
