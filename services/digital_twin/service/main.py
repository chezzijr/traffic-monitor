"""Digital Twin video analysis microservice.

Exposes ``GET /waiting_count?id_camera=<id>`` on port 8001.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from service.video_analyzer import (
    get_waiting_count,
    get_latest_frame,
    get_traffic_light_state,
    start_stream,
    stop_stream,
    get_stream_status,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Digital Twin – Video Analysis Service",
    version="0.1.0",
)


class WaitingCountResponse(BaseModel):
    id_camera: str
    north: int
    south: int
    east: int
    west: int
    total: int


class DirectionLightState(BaseModel):
    state: str
    duration: int


class TrafficLightStateResponse(BaseModel):
    north: DirectionLightState
    south: DirectionLightState
    east: DirectionLightState
    west: DirectionLightState


@app.get("/waiting_count", response_model=WaitingCountResponse)
def waiting_count(
    id_camera: str = Query(..., description="Camera identifier"),
) -> WaitingCountResponse:
    """Analyse ~1 second of traffic video and return waiting vehicle counts."""
    try:
        result = get_waiting_count(id_camera)
    except Exception as exc:
        logger.exception("Video processing failed for camera %s", id_camera)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process video: {exc}",
        ) from exc

    return WaitingCountResponse(**result)


@app.get("/frame")
def frame():
    """Return the latest video frame as base64 JPEG (original + annotated).

    Response format:
    ``{ frames: [{ number: 1, image: "<base64>", image_annotated: "<base64>" }] }``
    """
    data = get_latest_frame()
    img = data.get("image")
    img_ann = data.get("image_annotated")

    if img is None:
        return {"frames": []}

    return {
        "frames": [{
            "number": 1,
            "image": img,
            "image_annotated": img_ann,
        }],
    }


@app.get("/traffic_light_state", response_model=TrafficLightStateResponse)
def traffic_light_state() -> TrafficLightStateResponse:
    """Infer traffic light states from waiting vehicle behaviour.

    Logic:
      - North & East are observed from the camera.
      - If waiting vehicles >= threshold → RED, otherwise GREEN.
      - South mirrors North, West mirrors East.
      - Duration is always -1 (unknown).
    """
    try:
        result = get_traffic_light_state()
    except Exception as exc:
        logger.exception("Traffic light inference failed")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to infer traffic light state: {exc}",
        ) from exc

    return TrafficLightStateResponse(**result)


@app.get("/health")
def health():
    """Simple health check."""
    return {"status": "ok"}


# ── Stream lifecycle ──────────────────────────────────────────────────

@app.post("/stream/start")
def stream_start():
    """Start (or keep alive) the video analysis stream.

    Call this when the user opens the camera view.
    Also acts as a keepalive heartbeat — re-call it periodically so the
    stream doesn't auto-stop due to the idle timeout.
    """
    return start_stream()


@app.post("/stream/stop")
def stream_stop():
    """Stop the video analysis stream.

    Call this when the user closes the camera view.
    """
    return stop_stream()


@app.get("/stream/status")
def stream_status():
    """Return whether the video analysis stream is currently active."""
    return get_stream_status()


# ── Sync pipeline endpoints ───────────────────────────────────────────

from service.sync_loop import (
    start_sync,
    stop_sync,
    get_sync_status,
    get_sync_vehicles,
    get_evaluation,
    get_snapshot,
)


class SyncStartRequest(BaseModel):
    model_path: str | None = None


@app.post("/sync/start")
def sync_start(req: SyncStartRequest | None = None):
    """Start the video-to-SUMO sync pipeline.

    If ``model_path`` is provided, the RL model controls the traffic
    light.  Otherwise runs with fixed-time baseline.
    """
    model_path = req.model_path if req else None
    try:
        return start_sync(model_path)
    except Exception as exc:
        logger.exception("Failed to start sync")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/sync/stop")
def sync_stop():
    """Stop the sync pipeline."""
    return stop_sync()


@app.get("/sync/status")
def sync_status():
    """Return sync pipeline status."""
    return get_sync_status()


@app.get("/sync/vehicles")
def sync_vehicles():
    """Return current vehicles in the SUMO simulation."""
    return get_sync_vehicles()


@app.get("/sync/evaluation")
def sync_evaluation():
    """Return RL vs fixed-time baseline comparison."""
    result = get_evaluation()
    if result is None:
        return {"status": "not_ready", "detail": "Evaluation not yet complete"}
    return result


@app.get("/sync/snapshot")
def sync_snapshot():
    """Return combined snapshot for live monitoring page.

    Includes video frame, vehicle positions, TL states and metrics
    from both RL and baseline SUMO instances.
    """
    return get_snapshot()


@app.get("/sync/models")
def sync_models():
    """List available RL models in the models directory."""
    from service.config import RL_MODEL_DIR
    models = []
    model_dir = RL_MODEL_DIR
    if model_dir.exists():
        for f in sorted(model_dir.iterdir()):
            if f.suffix in (".pt", ".zip"):
                models.append({
                    "name": f.name,
                    "path": str(f),
                    "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
                })
    return models


@app.get("/sync/videos")
def sync_videos():
    """List available video files for evaluation."""
    from service.config import BASE_DIR
    video_dir = BASE_DIR / "data" / "traffic_video"
    videos = []
    if video_dir.exists():
        for subdir in sorted(video_dir.iterdir()):
            if subdir.is_dir():
                for f in sorted(subdir.iterdir()):
                    if f.suffix.lower() in (".mov", ".mp4", ".avi", ".mkv"):
                        videos.append({
                            "name": f.name,
                            "path": str(f),
                            "folder": subdir.name,
                            "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
                        })
    return videos


@app.post("/sync/traffic_light")
def sync_traffic_light(phase: int = Query(..., description="Phase index")):
    """Manually set the traffic light phase in the RL SUMO simulation."""
    from service.sync_loop import _sumo_rl

    if not _sumo_rl.running:
        raise HTTPException(status_code=400, detail="Sync not running")
    try:
        _sumo_rl.set_traffic_light_phase(phase)
        return _sumo_rl.get_traffic_light_state()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

