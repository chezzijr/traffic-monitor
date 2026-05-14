"""Digital Twin video analysis microservice.

Exposes ``GET /waiting_count?id_camera=<id>`` on port 8001.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from fastapi.responses import FileResponse

from service.video_analyzer import (
    get_waiting_count,
    get_latest_frame,
    get_traffic_light_state,
    start_stream,
    stop_stream,
    get_stream_status,
    set_debug_mode,
    get_debug_mode,
    get_waiting_history,
)
from service.chart_export import save_waiting_timeseries_chart, default_chart_path
from service.config import RESULT_DIR

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


class DeployStartRequest(BaseModel):
    model_path: str
    tl_id: str | None = None
    tl_ids: list[str] | None = None
    grid_rows: int = 2
    grid_cols: int = 3
    network_id: str | None = None


@app.get("/waiting_count", response_model=WaitingCountResponse)
def waiting_count(
    id_camera: str = Query(..., description="Camera identifier"),
) -> WaitingCountResponse:
    """Return waiting vehicle counts, auto-starting the video stream if needed.

    The video analysis stream starts on the first call and stays alive as
    long as this endpoint keeps being polled (each call acts as a
    keepalive).  When polling stops the stream auto-stops after an idle
    timeout.
    """
    try:
        # Ensure the stream is running (idempotent / acts as keepalive)
        start_stream()
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
    # Keep the stream alive when the frontend only polls /frame.
    start_stream()
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

    Auto-starts the video stream if not already running.

    Logic:
      - North & East are observed from the camera.
      - If waiting vehicles >= threshold → RED, otherwise GREEN.
      - South mirrors North, West mirrors East.
      - Duration is always -1 (unknown).
    """
    try:
        start_stream()
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


# ── Debug mode ────────────────────────────────────────────────────────

@app.api_route("/debug/toggle", methods=["GET", "POST"])
def debug_toggle(enabled: bool = Query(..., description="true to enable debug overlays, false to disable")):
    """Toggle debug mode on the annotated frame.

    When enabled, the annotated frame draws semi-transparent region overlays
    (north / south / east / west) so you can verify that the direction
    polygons cover the correct areas of the video.
    """
    set_debug_mode(enabled)
    return {"debug_mode": get_debug_mode()}


@app.get("/debug/status")
def debug_status():
    """Return the current debug mode state."""
    return {"debug_mode": get_debug_mode()}


# ── Result export endpoints ───────────────────────────────────────────

@app.get("/result/waiting-count-timeseries")
def result_waiting_timeseries():
    """Generate and return the waiting-count time-series chart as a PNG.

    Uses the history accumulated since the last sync/deploy run started.
    Also saves the chart to the ``result/`` directory.
    Saved filename: ``images/DT-results/waiting-count-timeseries.png``
    """
    history = get_waiting_history()
    if not history:
        raise HTTPException(
            status_code=404,
            detail="No waiting-count history yet. Start a sync or deploy run first.",
        )
    try:
        fixed_path = RESULT_DIR / "images" / "DT-results" / "waiting-count-timeseries.png"
        save_waiting_timeseries_chart(history, fixed_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return FileResponse(
        path=str(fixed_path),
        media_type="image/png",
        filename="waiting-count-timeseries.png",
    )


# ── Sync pipeline endpoints ───────────────────────────────────────────

from service.sync_loop import (
    start_sync,
    stop_sync,
    get_sync_status,
    get_sync_vehicles,
    get_snapshot,
)

from service.deploy_loop import (
    start_deploy,
    stop_deploy,
    get_deploy_status,
    get_deploy_snapshot,
    toggle_agent,
    list_models as list_deploy_models,
    list_videos as list_deploy_videos,
)


@app.post("/sync/start")
def sync_start():
    """Start the video-to-SUMO sync pipeline."""
    try:
        return start_sync()
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


@app.get("/sync/snapshot")
def sync_snapshot():
    """Return combined snapshot for live monitoring page.

    Includes video frame, vehicle positions, TL states and metrics.
    """
    return get_snapshot()


# ── Deploy (AI control) endpoints ───────────────────────────────────


@app.get("/deploy/models")
def deploy_models():
    """List available trained models for deploy."""
    return list_deploy_models()


@app.get("/deploy/videos")
def deploy_videos():
    """List available videos for deploy."""
    return list_deploy_videos()


@app.post("/deploy/start")
def deploy_start(request: DeployStartRequest):
    """Start the deploy loop with the selected model.

    Returns 409 with a structured body if a deploy is already running.
    Backend orchestration is expected to issue /deploy/stop first to swap.
    """
    try:
        result = start_deploy(
            request.model_path,
            request.tl_id,
            grid_rows=request.grid_rows,
            grid_cols=request.grid_cols,
            network_id=request.network_id,
        )
    except Exception as exc:
        logger.exception("Failed to start deploy")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if result.get("status") == "already_running":
        raise HTTPException(status_code=409, detail=result)
    return result


@app.get("/deploy/videos/check")
def deploy_videos_check():
    """Pre-flight check that the configured video file exists and is readable.

    Returns ``{exists, path, error, hint}``. Used by the backend /precheck
    proxy to block deploy attempts when git-LFS files are missing.
    """
    from service.config import VIDEO_PATH

    path_str = str(VIDEO_PATH)
    try:
        exists = VIDEO_PATH.exists() and VIDEO_PATH.is_file()
    except Exception as exc:
        return {
            "exists": False,
            "path": path_str,
            "error": f"stat_failed: {exc}",
            "hint": "Check VIDEO_PATH env var and DT container mounts.",
        }

    if not exists:
        return {
            "exists": False,
            "path": path_str,
            "error": "video_missing",
            "hint": "Run `git lfs pull` in the repo root, then restart the digital-twin container.",
        }

    # Detect LFS pointer files (small text stub instead of binary). Git-LFS
    # pointers are ~130 bytes and start with "version https://git-lfs.github.com".
    try:
        size = VIDEO_PATH.stat().st_size
        if size < 1024:
            with open(VIDEO_PATH, "rb") as fp:
                head = fp.read(64)
            if head.startswith(b"version https://git-lfs"):
                return {
                    "exists": False,
                    "path": path_str,
                    "error": "lfs_pointer_only",
                    "hint": "Video file is a git-LFS pointer (not pulled). Run `git lfs pull`.",
                    "size_bytes": size,
                }
    except Exception as exc:
        return {
            "exists": False,
            "path": path_str,
            "error": f"read_failed: {exc}",
            "hint": "Check file permissions inside the DT container.",
        }

    return {
        "exists": True,
        "path": path_str,
        "error": None,
        "hint": None,
        "size_bytes": size,
    }


@app.post("/deploy/stop")
def deploy_stop():
    """Stop the deploy loop."""
    return stop_deploy()


@app.get("/deploy/status")
def deploy_status():
    """Return deploy loop status."""
    return get_deploy_status()


@app.get("/deploy/snapshot")
def deploy_snapshot():
    """Return deploy loop snapshot for the frontend."""
    return get_deploy_snapshot()


@app.post("/deploy/agent/toggle")
def deploy_agent_toggle(enabled: bool = Query(..., description="true to enable AI agent control, false to switch to fixed-time")):
    """Toggle the RL agent on or off while the deploy loop is running.

    When disabled, AI-controlled intersections fall back to fixed-time control
    (33s green / 3s yellow / 30s red). When re-enabled, the agent resumes
    setting phases on the next decision interval.
    """
    return toggle_agent(enabled)

