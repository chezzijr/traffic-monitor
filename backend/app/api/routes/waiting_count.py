"""Waiting count API routes."""

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import WaitingCountResponse
from app.services import waiting_count_service

router = APIRouter(prefix="/waiting_count", tags=["waiting_count"])


@router.get("", response_model=WaitingCountResponse)
async def get_waiting_count(
    id_camera: str = Query(..., description="Camera identifier"),
) -> WaitingCountResponse:
    """Proxy waiting-count request to the Digital Twin service.

    Args:
        id_camera: Camera identifier forwarded to the video analysis service.

    Returns:
        WaitingCountResponse with per-direction waiting vehicle counts.
    """
    try:
        result = await waiting_count_service.get_waiting_count(id_camera)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Digital Twin service error: {exc}",
        ) from exc

    return WaitingCountResponse(**result)
