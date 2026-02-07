"""Camera-related API routes."""

import base64
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, File, Query, UploadFile, status

from app.models.schemas import CameraResponse, CameraSnapshot, CameraStreamInfo
from app.services import camera_service

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/camera", tags=["camera"])


@router.get(
    "/intersections/{intersection_id}",
    response_model=CameraResponse,
    status_code=status.HTTP_200_OK,
    summary="Get camera data for intersection",
    description="Get latest snapshot and stream info for an intersection.",
)
def get_camera_data(intersection_id: str) -> CameraResponse:
    """Get camera data (snapshot + stream) for an intersection."""
    try:
        data = camera_service.get_camera_data(intersection_id)
        return data
    except Exception as e:
        logger.error(f"Error getting camera data for intersection {intersection_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve camera data"
        )


@router.get(
    "/snapshots/{intersection_id}",
    response_model=list[CameraSnapshot],
    status_code=status.HTTP_200_OK,
    summary="Get recent snapshots for intersection",
    description="Get list of recent snapshots for an intersection.",
)
def get_snapshots(
    intersection_id: str,
    limit: int = Query(10, ge=1, le=100, description="Maximum number of snapshots to return")
) -> list[CameraSnapshot]:
    """Get recent snapshots for an intersection."""
    try:
        snapshots = camera_service.get_snapshots_for_intersection(intersection_id, limit=limit)
        return snapshots
    except Exception as e:
        logger.error(f"Error getting snapshots for intersection {intersection_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve snapshots"
        )


@router.post(
    "/snapshots/{intersection_id}",
    response_model=CameraSnapshot,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a snapshot for intersection",
    description="Upload a new snapshot (image/video) for an intersection.",
)
async def upload_snapshot(
    intersection_id: str,
    file: UploadFile = File(..., description="Image or video file"),
    step: int = Query(0, ge=0, description="Simulation step (if applicable)")
) -> CameraSnapshot:
    """Upload a new snapshot for an intersection.
    
    Supports image and video files. Data is base64 encoded and stored.
    """
    try:
        # Read file data
        contents = await file.read()
        
        # Base64 encode
        snapshot_data = base64.b64encode(contents).decode('utf-8')
        
        # Determine media type
        media_type = file.content_type or "application/octet-stream"
        
        # Add snapshot
        snapshot = camera_service.add_snapshot(
            intersection_id=intersection_id,
            snapshot_data=snapshot_data,
            media_type=media_type,
            step=step,
        )
        
        logger.info(f"Uploaded snapshot for intersection {intersection_id}: {file.filename}")
        return snapshot
    
    except Exception as e:
        logger.error(f"Error uploading snapshot for intersection {intersection_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload snapshot"
        )


@router.post(
    "/stream/{intersection_id}",
    response_model=CameraStreamInfo,
    status_code=status.HTTP_200_OK,
    summary="Set stream URL for intersection",
    description="Set or update the live stream URL for an intersection.",
)
def set_stream_url(
    intersection_id: str,
    stream_url: str | None = Query(None, description="Stream URL (RTSP, MJPEG, etc)")
) -> CameraStreamInfo:
    """Set or update the stream URL for an intersection."""
    try:
        stream_info = camera_service.set_stream_url(intersection_id, stream_url)
        return stream_info
    except Exception as e:
        logger.error(f"Error setting stream URL for intersection {intersection_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set stream URL"
        )


@router.get(
    "/stream/{intersection_id}",
    response_model=CameraStreamInfo,
    status_code=status.HTTP_200_OK,
    summary="Get stream info for intersection",
    description="Get stream information for an intersection.",
)
def get_stream_info(intersection_id: str) -> CameraStreamInfo:
    """Get stream information for an intersection."""
    try:
        data = camera_service.get_camera_data(intersection_id)
        return data.stream
    except Exception as e:
        logger.error(f"Error getting stream info for intersection {intersection_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve stream info"
        )


@router.get(
    "/snapshot/{intersection_id}/{snapshot_id}",
    response_model=CameraSnapshot,
    status_code=status.HTTP_200_OK,
    summary="Get specific snapshot",
    description="Get a specific snapshot by ID.",
)
def get_snapshot_by_id(intersection_id: str, snapshot_id: str) -> CameraSnapshot:
    """Get a specific snapshot by ID."""
    try:
        snapshot = camera_service.get_snapshot(intersection_id, snapshot_id)
        if not snapshot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Snapshot '{snapshot_id}' not found for intersection '{intersection_id}'"
            )
        return snapshot
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting snapshot {snapshot_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve snapshot"
        )


@router.get(
    "/list",
    response_model=dict[str, CameraStreamInfo],
    status_code=status.HTTP_200_OK,
    summary="List all cameras",
    description="Get list of all cameras with their stream information.",
)
def list_all_cameras() -> dict[str, CameraStreamInfo]:
    """Get list of all cameras."""
    try:
        cameras = camera_service.get_all_cameras()
        return cameras
    except Exception as e:
        logger.error(f"Error listing cameras: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list cameras"
        )
