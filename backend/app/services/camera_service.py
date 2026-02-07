"""Camera and snapshot management service.

This service manages camera snapshots and stream information for intersections.
Currently uses in-memory storage; can be extended with database backend.
"""

import logging
from datetime import datetime
from typing import Any

from app.models.schemas import CameraSnapshot, CameraStreamInfo, CameraResponse

logger = logging.getLogger(__name__)

# In-memory storage for camera data
# Structure: { intersection_id: { 'stream': CameraStreamInfo, 'snapshots': [CameraSnapshot] } }
_camera_store: dict[str, dict[str, Any]] = {}


def initialize_camera(intersection_id: str, stream_url: str | None = None) -> CameraStreamInfo:
    """Initialize camera for an intersection.
    
    Args:
        intersection_id: ID of the intersection
        stream_url: URL to the live stream (optional)
    
    Returns:
        CameraStreamInfo object
    """
    if intersection_id not in _camera_store:
        _camera_store[intersection_id] = {
            'stream': CameraStreamInfo(
                intersection_id=intersection_id,
                stream_url=stream_url,
                is_available=stream_url is not None,
                last_snapshot_timestamp=None,
            ),
            'snapshots': []
        }
        logger.info(f"Initialized camera for intersection {intersection_id}")
    
    return _camera_store[intersection_id]['stream']


def add_snapshot(intersection_id: str, snapshot_data: str, media_type: str = "image/jpeg", step: int = 0) -> CameraSnapshot:
    """Add a snapshot for an intersection.
    
    Args:
        intersection_id: ID of the intersection
        snapshot_data: Base64 encoded image/video data
        media_type: MIME type of the media
        step: Simulation step
    
    Returns:
        The created CameraSnapshot
    """
    if intersection_id not in _camera_store:
        initialize_camera(intersection_id)
    
    snapshot_id = f"{intersection_id}_{datetime.now().timestamp()}"
    snapshot = CameraSnapshot(
        id=snapshot_id,
        intersection_id=intersection_id,
        timestamp=datetime.now(),
        snapshot_data=snapshot_data,
        media_type=media_type,
        step=step,
    )
    
    # Keep only last 10 snapshots
    snapshots = _camera_store[intersection_id]['snapshots']
    snapshots.append(snapshot)
    if len(snapshots) > 10:
        snapshots.pop(0)
    
    # Update last snapshot timestamp
    _camera_store[intersection_id]['stream'].last_snapshot_timestamp = snapshot.timestamp
    
    logger.debug(f"Added snapshot for intersection {intersection_id}")
    return snapshot


def get_camera_data(intersection_id: str) -> CameraResponse:
    """Get camera data (latest snapshot and stream info) for an intersection.
    
    Args:
        intersection_id: ID of the intersection
    
    Returns:
        CameraResponse with snapshot and stream info
    """
    if intersection_id not in _camera_store:
        initialize_camera(intersection_id)
    
    store = _camera_store[intersection_id]
    snapshots = store['snapshots']
    
    return CameraResponse(
        snapshot=snapshots[-1] if snapshots else None,
        stream=store['stream'],
        available_snapshots=snapshots[-5:] if snapshots else [],  # Last 5 snapshots
    )


def get_snapshot(intersection_id: str, snapshot_id: str) -> CameraSnapshot | None:
    """Get a specific snapshot by ID.
    
    Args:
        intersection_id: ID of the intersection
        snapshot_id: ID of the snapshot
    
    Returns:
        CameraSnapshot if found, None otherwise
    """
    if intersection_id not in _camera_store:
        return None
    
    snapshots = _camera_store[intersection_id]['snapshots']
    for snapshot in snapshots:
        if snapshot.id == snapshot_id:
            return snapshot
    
    return None


def set_stream_url(intersection_id: str, stream_url: str | None) -> CameraStreamInfo:
    """Set or update the stream URL for an intersection.
    
    Args:
        intersection_id: ID of the intersection
        stream_url: New stream URL (None to disable)
    
    Returns:
        Updated CameraStreamInfo
    """
    if intersection_id not in _camera_store:
        initialize_camera(intersection_id, stream_url)
    else:
        stream = _camera_store[intersection_id]['stream']
        stream.stream_url = stream_url
        stream.is_available = stream_url is not None
    
    logger.info(f"Updated stream URL for intersection {intersection_id}: {stream_url}")
    return _camera_store[intersection_id]['stream']


def get_all_cameras() -> dict[str, CameraStreamInfo]:
    """Get camera information for all intersections.
    
    Returns:
        Dictionary mapping intersection_id to CameraStreamInfo
    """
    return {
        int_id: store['stream']
        for int_id, store in _camera_store.items()
    }


def get_snapshots_for_intersection(intersection_id: str, limit: int = 10) -> list[CameraSnapshot]:
    """Get recent snapshots for an intersection.
    
    Args:
        intersection_id: ID of the intersection
        limit: Maximum number of snapshots to return
    
    Returns:
        List of snapshots
    """
    if intersection_id not in _camera_store:
        return []
    
    snapshots = _camera_store[intersection_id]['snapshots']
    return snapshots[-limit:] if snapshots else []
