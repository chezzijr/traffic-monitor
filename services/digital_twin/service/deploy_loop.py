"""Deploy loop: run video-driven SUMO and let an RL model control the TL."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import numpy as np

from service.coordinate_mapper import DirectionTracker, STRAIGHT_ROUTES, get_incoming_edge
from service.config import (
    DEPLOY_DECISION_INTERVAL_STEPS,
    DEPLOY_MODEL_DIR,
    DEPLOY_SUMO_DIR,
    DEPLOY_VIDEO_DIR,
    FIXED_GREEN_DURATION,
    FIXED_YELLOW_DURATION,
    SIM_REALTIME_DIR,
    SAVED_NETWORKS_DIR,
)
from service.rl_model import RLModel
from service.sumo_manager import SumoManager
from service.video_analyzer import (
    get_latest_frame,
    get_tracked_vehicles,
    is_video_complete,
    reset_video_complete_flag,
    start_background_loop,
)

# Import grid network generation from script_network.py (at parent level)
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from script_network import (
    ensure_sumo_network,
    get_boundary_entry_edges,
    get_boundary_exit_edges,
    OPPOSITE_DIRECTION,
)
import random

logger = logging.getLogger(__name__)

# ── Shared state ──────────────────────────────────────────────────────

_deploy_lock = threading.Lock()
_deploy_active = False
_deploy_thread: threading.Thread | None = None
_deploy_status: dict = {
    "running": False,
    "step": 0,
    "num_sumo_vehicles": 0,
    "video_complete": False,
    "model_path": None,
    "tl_id": None,
    "network_id": None,
    "last_action": None,
}
_snapshot_data: dict = {}

# Components
_sumo = SumoManager(label="deploy")
_direction_tracker = DirectionTracker()
_model = RLModel()


# ── Helpers ─────────────────────────────────────────────────────────-


def _resolve_model_dir() -> Path:
    if DEPLOY_MODEL_DIR.exists():
        return DEPLOY_MODEL_DIR
    fallback = SIM_REALTIME_DIR / "model"
    return fallback


def _resolve_video_dir() -> Path:
    if DEPLOY_VIDEO_DIR.exists():
        return DEPLOY_VIDEO_DIR
    fallback = SIM_REALTIME_DIR / "data"
    return fallback


def _get_green_phase_indices(conn, tl_id: str) -> list[int]:
    logic = conn.trafficlight.getAllProgramLogics(tl_id)
    if not logic:
        return []
    phases = logic[0].phases
    green = [i for i, p in enumerate(phases) if "G" in p.state or "g" in p.state]
    return green or list(range(len(phases)))


def _build_observation(conn, tl_id: str, controlled_lanes: list[str], num_actions: int, green_indices: list[int]) -> np.ndarray:
    lane_counts = []
    for lane in controlled_lanes:
        try:
            lane_counts.append(float(conn.lane.getLastStepVehicleNumber(lane)))
        except Exception:
            lane_counts.append(0.0)

    try:
        sumo_phase = conn.trafficlight.getPhase(tl_id)
    except Exception:
        sumo_phase = 0

    current_green_idx = 0
    if green_indices and sumo_phase in green_indices:
        current_green_idx = green_indices.index(sumo_phase)

    phase_one_hot = np.zeros(num_actions, dtype=np.float32)
    if 0 <= current_green_idx < num_actions:
        phase_one_hot[current_green_idx] = 1.0

    return np.concatenate([np.array(lane_counts, dtype=np.float32), phase_one_hot])


def _feed_vehicles(tracked: list[dict], vehicle_ids: set[str], grid_rows: int, grid_cols: int) -> set[str]:
    visible_ids: set[str] = set()

    for veh in tracked:
        veh_id = f"v_{veh['id']}"
        region = veh.get("region")
        if region is None:
            continue

        visible_ids.add(veh_id)
        _direction_tracker.update(veh["id"], region)

        if veh_id not in vehicle_ids:
            # New vehicle detected in video
            # In the grid network, we spawn at ALL entry points for this direction
            entry_region = region
            exit_region = OPPOSITE_DIRECTION.get(entry_region, "south")
            
            # Use the logic from script_network: spawn at all boundary entry edges
            entry_edges = get_boundary_entry_edges(grid_rows, grid_cols).get(entry_region, [])
            exit_edges_list = get_boundary_exit_edges(grid_rows, grid_cols).get(exit_region, [])
            
            if not entry_edges:
                continue

            # We'll spawn at the first entry edge for the primary ID, 
            # and others as clones (consistent with script_network.py)
            spawned_any = False
            for idx, (_, _, entry_eid) in enumerate(entry_edges):
                if not exit_edges_list:
                    continue
                _, _, exit_eid = random.choice(exit_edges_list)
                
                # In TraCI, routes must exist. ensure_sumo_network should have created them.
                route_id = f"route_{entry_eid}_to_{exit_eid}"
                vid = veh_id if idx == 0 else f"{veh_id}_g{idx}"
                
                if _sumo.add_vehicle(vid, route_id, pos=0.1, speed=max(veh.get("speed", 0.0), 1.0)):
                    _sumo.update_vehicle_speed(vid, -1)
                    vehicle_ids.add(vid)
                    spawned_any = True
            
            if not spawned_any:
                visible_ids.discard(veh_id)
        else:
            # Known vehicle: check for turns and reroute in SUMO
            if _direction_tracker.is_route_updated(veh["id"]):
                new_exit_region = _direction_tracker.get_exit_direction(veh["id"]) # I need to check if this exists
                if new_exit_region:
                    exit_edges_list = get_boundary_exit_edges(grid_rows, grid_cols).get(new_exit_region, [])
                    if exit_edges_list:
                        _, _, exit_eid = random.choice(exit_edges_list)
                        _sumo.reroute_vehicle(veh_id, exit_eid)
                        # Also reroute clones
                        for idx in range(1, 10): # assuming max grid size isn't huge
                            clone_id = f"{veh_id}_g{idx}"
                            if clone_id in vehicle_ids:
                                _sumo.reroute_vehicle(clone_id, exit_eid)

    departed = vehicle_ids - visible_ids
    # Filter out clones from departed list for cleanup
    for vid in departed:
        _sumo.remove_vehicle(vid)
        # Only remove from tracker if it's the primary ID
        if vid.startswith("v_") and "_g" not in vid:
            try:
                orig_id = int(vid.split("_")[1])
                _direction_tracker.remove(orig_id)
            except Exception:
                pass
    vehicle_ids -= departed

    return vehicle_ids


# ── Public API ───────────────────────────────────────────────────────


def start_deploy(model_path: str, tl_id: str | None = None, grid_rows: int = 2, grid_cols: int = 3, network_id: str | None = None) -> dict:
    global _deploy_active, _deploy_thread, _snapshot_data

    with _deploy_lock:
        if _deploy_active:
            return {"status": "already_running"}

        _deploy_active = True
        _snapshot_data = {}

        _deploy_status.update({
            "running": True,
            "step": 0,
            "num_sumo_vehicles": 0,
            "video_complete": False,
            "model_path": model_path,
            "tl_id": tl_id,
            "network_id": network_id,
            "grid_rows": grid_rows,
            "grid_cols": grid_cols,
            "last_action": None,
        })

    _model.load(model_path)

    _deploy_thread = threading.Thread(
        target=_deploy_loop,
        args=(tl_id, grid_rows, grid_cols, network_id),
        daemon=True,
        name="deploy-loop",
    )
    _deploy_thread.start()

    return {"status": "started"}


def stop_deploy() -> dict:
    global _deploy_active

    with _deploy_lock:
        _deploy_active = False
        _deploy_status["running"] = False

    _sumo.stop()
    return {"status": "stopped", "step": _deploy_status["step"]}


def get_deploy_status() -> dict:
    with _deploy_lock:
        return dict(_deploy_status)


def get_deploy_snapshot() -> dict:
    with _deploy_lock:
        return dict(_snapshot_data) if _snapshot_data else {"step": 0, "running": False}


def list_models() -> list[dict]:
    model_dir = _resolve_model_dir()
    if not model_dir.exists():
        return []

    models = []
    for file_path in sorted(model_dir.glob("**/*.pt")):
        stat = file_path.stat()
        models.append({
            "name": file_path.name,
            "path": str(file_path),
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
        })
    return models


def list_videos() -> list[dict]:
    video_dir = _resolve_video_dir()
    if not video_dir.exists():
        return []

    videos = []
    for file_path in sorted(video_dir.glob("**/*")):
        if file_path.suffix.lower() not in {".mp4", ".mov", ".mkv", ".avi"}:
            continue
        stat = file_path.stat()
        videos.append({
            "name": file_path.name,
            "path": str(file_path),
            "folder": file_path.parent.name,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
        })
    return videos


# ── Internal loop ─────────────────────────────────────────────────────


def _deploy_loop(tl_id: str | None, grid_rows: int, grid_cols: int, network_id: str | None = None) -> None:
    global _deploy_active, _snapshot_data

    try:
        # Resolve network path
        net_path = None
        if network_id:
            # Look for saved network in SAVED_NETWORKS_DIR
            saved_path = SAVED_NETWORKS_DIR / f"{network_id}.net.xml"
            if saved_path.exists():
                net_path = saved_path
                logger.info("Using saved network: %s", net_path)
            else:
                logger.warning("Saved network not found: %s. Falling back to grid.", saved_path)

        if net_path is None:
            # Generate the network with the specified dimensions
            ensure_sumo_network(DEPLOY_SUMO_DIR, rows=grid_rows, cols=grid_cols, rebuild=True)
            net_path = DEPLOY_SUMO_DIR / "grid_network.net.xml"
        
        if not net_path.exists():
            raise FileNotFoundError(f"SUMO network not found: {net_path}")

        _sumo.start(net_path)

        # Resolve TL and install a baseline program (AI will override phases)
        target_tl_id = tl_id
        if target_tl_id is None:
            target_tl_id = _sumo.get_tl_id()

        _sumo.install_fixed_time_program(
            FIXED_GREEN_DURATION,
            FIXED_YELLOW_DURATION,
            tl_id=target_tl_id,
        )

        conn = _sumo.get_connection()
        controlled_lanes = _sumo.get_controlled_lanes(target_tl_id)
        green_indices = _get_green_phase_indices(conn, target_tl_id)

        logger.info("Deploy loop started (tl_id=%s)", target_tl_id)

        start_background_loop()
        reset_video_complete_flag()

        veh_ids: set[str] = set()
        _direction_tracker.__init__()

        while _deploy_active:
            # Keep the video stream alive (start_stream is idempotent)
            start_background_loop()
            tracked = get_tracked_vehicles()
            veh_ids = _feed_vehicles(tracked, veh_ids, grid_rows, grid_cols)

            metrics = _sumo.step()

            last_action = _deploy_status.get("last_action")
            if DEPLOY_DECISION_INTERVAL_STEPS > 0 and metrics["step"] % DEPLOY_DECISION_INTERVAL_STEPS == 0:
                observation = _build_observation(
                    conn,
                    target_tl_id,
                    controlled_lanes,
                    _model.num_actions,
                    green_indices,
                )
                action_green_idx = _model.predict(observation)
                if green_indices:
                    if action_green_idx < len(green_indices):
                        sumo_action = green_indices[action_green_idx]
                    else:
                        sumo_action = green_indices[0]
                else:
                    sumo_action = action_green_idx
                conn.trafficlight.setPhase(target_tl_id, int(sumo_action))
                last_action = int(sumo_action)

            frame_data = get_latest_frame()
            snapshot = {
                "step": metrics["step"],
                "running": True,
                "video_frame": frame_data.get("image_annotated") or frame_data.get("image"),
                "video_timestamp": frame_data.get("timestamp", 0.0),
                "vehicles": _sumo.get_vehicles() if _sumo.running else [],
                "tl_state": _sumo.get_traffic_light_state(target_tl_id) if _sumo.running else {},
                "metrics": {
                    "num_vehicles": metrics["num_vehicles"],
                    "total_waiting_time": round(metrics["total_waiting_time"], 1),
                    "avg_speed": round(metrics["avg_speed"], 2),
                    "arrived": metrics["arrived"],
                },
                "ai_action": last_action,
            }

            with _deploy_lock:
                _snapshot_data = snapshot
                _deploy_status["step"] = metrics["step"]
                _deploy_status["num_sumo_vehicles"] = metrics["num_vehicles"]
                _deploy_status["tl_id"] = target_tl_id
                _deploy_status["last_action"] = last_action

            if is_video_complete():
                logger.info("Video completed — deploy run finished")
                with _deploy_lock:
                    _deploy_status["video_complete"] = True
                break

            time.sleep(0.1)

        _sumo.stop()

        with _deploy_lock:
            _snapshot_data["running"] = False

        logger.info("Deploy loop finished")

    except Exception:
        logger.exception("Deploy loop error")
    finally:
        with _deploy_lock:
            _deploy_active = False
            _deploy_status["running"] = False
        if _sumo.running:
            _sumo.stop()
