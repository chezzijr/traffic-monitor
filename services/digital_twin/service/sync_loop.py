"""Synchronization orchestrator — bridges video tracking with SUMO.

Runs as a background thread. For each video frame:
  1. Get tracked vehicles from the video analyzer snapshot
  2. Map new vehicles to SUMO edges and add them
  3. Update existing vehicle speeds / correct routes
  4. Remove vehicles that left the video
  5. Step BOTH SUMO instances (RL + baseline) forward in parallel
  6. Run RL agent inference for traffic light control
  7. Collect metrics from both instances
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from service.agent_controller import AgentController
from service.coordinate_mapper import (
    DirectionTracker,
    STRAIGHT_ROUTES,
    get_incoming_edge,
)
from service.config import (
    STEPS_PER_ACTION,
    FIXED_GREEN_DURATION,
    FIXED_YELLOW_DURATION,
)
from service.evaluator import MetricsCollector, build_comparison
from service.network_gen import get_network_path
from service.sumo_manager import SumoManager

logger = logging.getLogger(__name__)

# ── Shared state ──────────────────────────────────────────────────────

_sync_lock = threading.Lock()
_sync_active = False
_sync_thread: threading.Thread | None = None
_sync_status: dict = {
    "running": False,
    "mode": None,          # "rl" | "baseline" | "both"
    "step": 0,
    "num_sumo_vehicles": 0,
    "video_complete": False,
}

# Evaluation results
_rl_collector = MetricsCollector()
_baseline_collector = MetricsCollector()
_evaluation_result: dict | None = None

# Components — two SUMO instances for parallel comparison
_sumo_rl = SumoManager(label="sync_rl")
_sumo_baseline = SumoManager(label="sync_baseline")
_agent = AgentController()
_direction_tracker = DirectionTracker()
_baseline_tracker = DirectionTracker()

# Snapshot data for the live monitoring page
_snapshot_data: dict = {}


def start_sync(model_path: str | None = None) -> dict:
    """Start the video-to-SUMO sync pipeline.

    If model_path is provided: runs RL + baseline in parallel.
    If None: runs baseline only.
    """
    global _sync_active, _sync_thread, _evaluation_result, _snapshot_data

    with _sync_lock:
        if _sync_active:
            return {"status": "already_running"}

        _sync_active = True
        _evaluation_result = None
        _snapshot_data = {}
        _rl_collector.reset()
        _baseline_collector.reset()

        try:
            if model_path:
                _agent.load_model(model_path)
                mode = "both"  # RL + baseline in parallel
            else:
                mode = "baseline"
        except Exception:
            _sync_active = False
            raise

        _sync_status.update({
            "running": True,
            "mode": mode,
            "step": 0,
            "num_sumo_vehicles": 0,
            "video_complete": False,
        })

    _sync_thread = threading.Thread(
        target=_sync_loop,
        args=(mode,),
        daemon=True,
        name="sync-loop",
    )
    _sync_thread.start()

    return {"status": "started", "mode": mode}


def stop_sync() -> dict:
    """Stop the sync pipeline."""
    global _sync_active

    with _sync_lock:
        _sync_active = False
        _sync_status["running"] = False

    _sumo_rl.stop()
    _sumo_baseline.stop()
    return {"status": "stopped", "step": _sync_status["step"]}


def get_sync_status() -> dict:
    with _sync_lock:
        return dict(_sync_status)


def get_sync_vehicles() -> list[dict]:
    """Return vehicles from RL SUMO (primary)."""
    if _sumo_rl.running:
        return _sumo_rl.get_vehicles()
    if _sumo_baseline.running:
        return _sumo_baseline.get_vehicles()
    return []


def get_evaluation() -> dict | None:
    return _evaluation_result


def get_snapshot() -> dict:
    """Return a combined snapshot for the live monitoring page."""
    with _sync_lock:
        return dict(_snapshot_data) if _snapshot_data else {
            "step": 0,
            "running": False,
        }


# ── Internal: feed vehicles to a SUMO instance ───────────────────────

def _feed_vehicles(
    sumo: SumoManager,
    tracked: list[dict],
    vehicle_ids: set[str],
    tracker: DirectionTracker,
) -> set[str]:
    """Sync tracked vehicles into a SUMO instance. Returns updated ID set."""
    visible_ids: set[str] = set()

    for veh in tracked:
        veh_id = f"v_{veh['id']}"
        region = veh.get("region")
        speed = veh.get("speed", 0.0)

        if region is None:
            continue

        visible_ids.add(veh_id)
        tracker.update(veh["id"], region)

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
            if sumo.add_vehicle(veh_id, route, pos=0.1, speed=max(speed, 1.0)):
                vehicle_ids.add(veh_id)
                # Release to SUMO control — let the simulator drive
                sumo.update_vehicle_speed(veh_id, -1)
        else:
            # Existing → only update route if direction changed
            # Speed is managed by SUMO autonomously
            updated_route = tracker.get_route(veh["id"])
            if updated_route and tracker.is_route_updated(veh["id"]):
                sumo.reroute_vehicle(veh_id, updated_route)

    # Remove departed vehicles
    departed = vehicle_ids - visible_ids
    for vid in departed:
        sumo.remove_vehicle(vid)
        orig_id = int(vid.split("_")[1])
        tracker.remove(orig_id)
    vehicle_ids -= departed

    return vehicle_ids


# ── Main sync loop ───────────────────────────────────────────────────

def _sync_loop(mode: str) -> None:
    """Main synchronization loop — runs both SUMO instances in parallel."""
    global _sync_active, _evaluation_result, _snapshot_data

    try:
        net_path = get_network_path()

        # Start baseline SUMO (always)
        _sumo_baseline.start(net_path)
        _sumo_baseline.install_fixed_time_program(
            FIXED_GREEN_DURATION, FIXED_YELLOW_DURATION,
        )

        # Start RL SUMO (if model loaded)
        run_rl = mode == "both"
        if run_rl:
            _sumo_rl.start(net_path)

        logger.info("Sync loop started (mode=%s)", mode)

        from service.video_analyzer import (
            get_tracked_vehicles,
            is_video_complete,
            reset_video_complete_flag,
            start_background_loop,
            get_latest_frame,
        )

        start_background_loop()
        reset_video_complete_flag()

        rl_veh_ids: set[str] = set()
        baseline_veh_ids: set[str] = set()
        _direction_tracker.__init__()  # reset
        _baseline_tracker.__init__()   # reset
        action_step_counter = 0

        while _sync_active:
            tracked = get_tracked_vehicles()

            # Feed vehicles to both SUMO instances
            if run_rl:
                rl_veh_ids = _feed_vehicles(
                    _sumo_rl, tracked, rl_veh_ids, _direction_tracker,
                )

            baseline_veh_ids = _feed_vehicles(
                _sumo_baseline, tracked, baseline_veh_ids, _baseline_tracker,
            )

            # RL agent decision (every STEPS_PER_ACTION steps)
            if run_rl and _agent.is_loaded:
                action_step_counter += 1
                if action_step_counter >= STEPS_PER_ACTION:
                    _agent.step(_sumo_rl)
                    action_step_counter = 0

            # Step both SUMO instances
            rl_metrics = None
            if run_rl:
                rl_metrics = _sumo_rl.step()
                _rl_collector.record(
                    step=rl_metrics["step"],
                    waiting_time=rl_metrics["total_waiting_time"],
                    queue_length=rl_metrics["num_vehicles"],
                    avg_speed=rl_metrics["avg_speed"],
                    arrived=rl_metrics["arrived"],
                )

            baseline_metrics = _sumo_baseline.step()
            _baseline_collector.record(
                step=baseline_metrics["step"],
                waiting_time=baseline_metrics["total_waiting_time"],
                queue_length=baseline_metrics["num_vehicles"],
                avg_speed=baseline_metrics["avg_speed"],
                arrived=baseline_metrics["arrived"],
            )

            # Build snapshot for live monitoring
            primary_metrics = rl_metrics if rl_metrics else baseline_metrics
            frame_data = get_latest_frame()

            snapshot = {
                "step": primary_metrics["step"],
                "running": True,
                "video_frame": frame_data.get("image_annotated") or frame_data.get("image"),
                "video_timestamp": frame_data.get("timestamp", 0.0),
                "baseline_vehicles": _sumo_baseline.get_vehicles() if _sumo_baseline.running else [],

                "baseline_tl_state": _sumo_baseline.get_traffic_light_state() if _sumo_baseline.running else {},
                "baseline_metrics": {
                    "num_vehicles": baseline_metrics["num_vehicles"],
                    "total_waiting_time": round(baseline_metrics["total_waiting_time"], 1),
                    "avg_speed": round(baseline_metrics["avg_speed"], 2),
                    "arrived": baseline_metrics["arrived"],
                },
            }

            if run_rl and rl_metrics:
                snapshot["rl_vehicles"] = _sumo_rl.get_vehicles() if _sumo_rl.running else []
                snapshot["rl_tl_state"] = _sumo_rl.get_traffic_light_state() if _sumo_rl.running else {}
                snapshot["rl_metrics"] = {
                    "num_vehicles": rl_metrics["num_vehicles"],
                    "total_waiting_time": round(rl_metrics["total_waiting_time"], 1),
                    "avg_speed": round(rl_metrics["avg_speed"], 2),
                    "arrived": rl_metrics["arrived"],
                }

            with _sync_lock:
                _snapshot_data = snapshot
                _sync_status["step"] = primary_metrics["step"]
                _sync_status["num_sumo_vehicles"] = primary_metrics["num_vehicles"]

            # Check if video completed
            if is_video_complete():
                logger.info("Video completed — sync run finished")
                with _sync_lock:
                    _sync_status["video_complete"] = True
                break

            time.sleep(0.1)  # ~10 Hz

        # Stop SUMO instances
        _sumo_rl.stop()
        _sumo_baseline.stop()

        # Build evaluation
        if run_rl:
            _evaluation_result = build_comparison(
                _rl_collector.summary(),
                _baseline_collector.summary(),
            )
        else:
            _evaluation_result = {
                "baseline_metrics": _baseline_collector.summary(),
            }

        # Update final snapshot
        with _sync_lock:
            _snapshot_data["running"] = False
            _snapshot_data["evaluation"] = _evaluation_result

        logger.info("Evaluation complete: %s", _evaluation_result)

    except Exception:
        logger.exception("Sync loop error")
    finally:
        with _sync_lock:
            _sync_active = False
            _sync_status["running"] = False
        if _sumo_rl.running:
            _sumo_rl.stop()
        if _sumo_baseline.running:
            _sumo_baseline.stop()
