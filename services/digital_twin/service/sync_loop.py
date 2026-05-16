"""Synchronization orchestrator — bridges video tracking with SUMO.

Runs as a background thread. For each video frame:
  1. Get tracked vehicles from the video analyzer snapshot
  2. Map new vehicles to SUMO edges and add them
  3. Update existing vehicle speeds / correct routes
  4. Remove vehicles that left the video
  5. Step SUMO instance forward
  6. Collect metrics
"""

from __future__ import annotations

import logging
import threading
import time

from service.coordinate_mapper import (
    DirectionTracker,
    STRAIGHT_ROUTES,
    get_incoming_edge,
)
from service.config import (
    FIXED_GREEN_DURATION,
    FIXED_YELLOW_DURATION,
    RESULT_DIR,
)
from service.network_gen import get_network_path
from service.sumo_manager import SumoManager
from service.chart_export import save_waiting_timeseries_chart, default_chart_path

logger = logging.getLogger(__name__)

# ── Shared state ──────────────────────────────────────────────────────

_sync_lock = threading.Lock()
_sync_active = False
_sync_thread: threading.Thread | None = None
_sync_status: dict = {
    "running": False,
    "step": 0,
    "num_sumo_vehicles": 0,
    "video_complete": False,
}

# Components — single SUMO instance
_sumo = SumoManager(label="sync")
_direction_tracker = DirectionTracker()

# Snapshot data for the live monitoring page
_snapshot_data: dict = {}


def start_sync() -> dict:
    """Start the video-to-SUMO sync pipeline."""
    global _sync_active, _sync_thread, _snapshot_data

    with _sync_lock:
        if _sync_active:
            return {"status": "already_running"}

        _sync_active = True
        _snapshot_data = {}

        _sync_status.update({
            "running": True,
            "step": 0,
            "num_sumo_vehicles": 0,
            "video_complete": False,
        })

    _sync_thread = threading.Thread(
        target=_sync_loop,
        daemon=True,
        name="sync-loop",
    )
    _sync_thread.start()

    return {"status": "started"}


def stop_sync() -> dict:
    """Stop the sync pipeline."""
    global _sync_active

    with _sync_lock:
        _sync_active = False
        _sync_status["running"] = False

    _sumo.stop()
    return {"status": "stopped", "step": _sync_status["step"]}


def get_sync_status() -> dict:
    with _sync_lock:
        return dict(_sync_status)


def get_sync_vehicles() -> list[dict]:
    """Return vehicles from the SUMO simulation."""
    if _sumo.running:
        return _sumo.get_vehicles()
    return []


def get_snapshot() -> dict:
    """Return a combined snapshot for the live monitoring page."""
    with _sync_lock:
        return dict(_snapshot_data) if _snapshot_data else {
            "step": 0,
            "running": False,
        }


# ── Internal: feed vehicles to a SUMO instance ───────────────────────

def _feed_vehicles(
    tracked: list[dict],
    vehicle_ids: set[str],
) -> set[str]:
    """Sync tracked vehicles into the SUMO instance. Returns updated ID set."""
    visible_ids: set[str] = set()

    for veh in tracked:
        veh_id = f"v_{veh['id']}"
        region = veh.get("region")
        speed = veh.get("speed", 0.0)

        if region is None:
            continue

        visible_ids.add(veh_id)
        _direction_tracker.update(veh["id"], region)

        if veh_id not in vehicle_ids:
            # New vehicle → spawn at edge start, let SUMO drive
            edge = get_incoming_edge(region)
            if edge is None:
                continue
            route = STRAIGHT_ROUTES.get(region)
            if route is None:
                continue
            # Always spawn at start of incoming edge (pos=0.1)
            # with a minimum speed so it enters the network
            if _sumo.add_vehicle(veh_id, route, pos=0.1, speed=max(speed, 1.0)):
                vehicle_ids.add(veh_id)
                # Release to SUMO control — let the simulator drive
                _sumo.update_vehicle_speed(veh_id, -1)
        else:
            # Existing → only update route if direction changed
            # Speed is managed by SUMO autonomously
            updated_route = _direction_tracker.get_route(veh["id"])
            if updated_route and _direction_tracker.is_route_updated(veh["id"]):
                _sumo.reroute_vehicle(veh_id, updated_route)

    # Remove departed vehicles
    departed = vehicle_ids - visible_ids
    for vid in departed:
        _sumo.remove_vehicle(vid)
        orig_id = int(vid.split("_")[1])
        _direction_tracker.remove(orig_id)
    vehicle_ids -= departed

    return vehicle_ids


# ── Main sync loop ───────────────────────────────────────────────────

def _sync_loop() -> None:
    """Main synchronization loop."""
    global _sync_active, _snapshot_data

    try:
        net_path = get_network_path()

        # Start SUMO with fixed-time traffic light
        _sumo.start(net_path)
        _sumo.install_fixed_time_program(
            FIXED_GREEN_DURATION, FIXED_YELLOW_DURATION,
        )

        logger.info("Sync loop started")

        from service.video_analyzer import (
            get_tracked_vehicles,
            is_video_complete,
            reset_video_complete_flag,
            reset_waiting_history,
            get_waiting_history,
            start_background_loop,
            get_latest_frame,
        )

        start_background_loop()
        reset_video_complete_flag()
        reset_waiting_history()

        veh_ids: set[str] = set()
        _direction_tracker.__init__()  # reset

        while _sync_active:
            tracked = get_tracked_vehicles()

            # Feed vehicles to SUMO
            veh_ids = _feed_vehicles(tracked, veh_ids)

            # Step SUMO
            metrics = _sumo.step()

            # Build snapshot for live monitoring
            frame_data = get_latest_frame()

            snapshot = {
                "step": metrics["step"],
                "running": True,
                "video_frame": frame_data.get("image"),
                "video_frame_annotated": frame_data.get("image_annotated"),
                "video_timestamp": frame_data.get("timestamp", 0.0),
                "vehicles": _sumo.get_vehicles() if _sumo.running else [],
                "tl_state": _sumo.get_traffic_light_state() if _sumo.running else {},
                "metrics": {
                    "num_vehicles": metrics["num_vehicles"],
                    "total_waiting_time": round(metrics["total_waiting_time"], 1),
                    "avg_speed": round(metrics["avg_speed"], 2),
                    "arrived": metrics["arrived"],
                },
            }

            with _sync_lock:
                _snapshot_data = snapshot
                _sync_status["step"] = metrics["step"]
                _sync_status["num_sumo_vehicles"] = metrics["num_vehicles"]

            # Check if video completed
            if is_video_complete():
                logger.info("Video completed — sync run finished")
                with _sync_lock:
                    _sync_status["video_complete"] = True
                try:
                    history = get_waiting_history()
                    chart_path = default_chart_path(RESULT_DIR, tag="sync")
                    save_waiting_timeseries_chart(history, chart_path)
                    logger.info("Waiting-count chart saved: %s", chart_path)
                except Exception:
                    logger.exception("Failed to save waiting-count chart")
                break

            time.sleep(0.1)  # ~10 Hz

        # Stop SUMO
        _sumo.stop()

        # Update final snapshot
        with _sync_lock:
            _snapshot_data["running"] = False

        logger.info("Sync loop finished")

    except Exception:
        logger.exception("Sync loop error")
    finally:
        with _sync_lock:
            _sync_active = False
            _sync_status["running"] = False
        if _sumo.running:
            _sumo.stop()
