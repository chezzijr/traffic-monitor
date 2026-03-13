"""Waiting count API routes."""

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import WaitingCountResponse
from app.services import waiting_count_service

router = APIRouter(prefix="/waiting_count", tags=["waiting_count"])


@router.get("", response_model=WaitingCountResponse)
async def get_waiting_count(
    id_camera: str = Query(..., description="Camera identifier"),
) -> WaitingCountResponse:
    """Analyse ~1 second of traffic video and return waiting vehicle counts.

    Args:
        id_camera: Camera identifier (placeholder – always uses default video).

    Returns:
        WaitingCountResponse with per-direction waiting vehicle counts.

    Raises:
        HTTPException 500: If video processing fails.
    """
    try:
        result = waiting_count_service.get_waiting_count(id_camera)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process video: {exc}",
        ) from exc

    return WaitingCountResponse(**result)
