"""Deploy loop: run video-driven SUMO and let RL model(s) control TL(s).

Supports both single-agent (DQN/PPO) and multi-agent (CoLight) models.

Multi-agent flow:
  1. Use the saved OSM network from the frontend selection
  2. Spawn vehicles at boundary edges based on video tracking with ±20% clone deviation
  3. AI-controlled intersections use the trained model; others get fixed-time control
     (33s green - 3s yellow - 30s red per direction)
"""

from __future__ import annotations

import json
import logging
import random
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
    RESULT_DIR,
)
from service.rl_model import RLModel
from service.sumo_manager import SumoManager
from service.video_analyzer import (
    get_latest_frame,
    get_tracked_vehicles,
    is_video_complete,
    reset_video_complete_flag,
    reset_waiting_history,
    get_waiting_history,
    start_background_loop,
)
from service.chart_export import save_waiting_timeseries_chart, default_chart_path

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

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────

# Fixed-time durations for uncontrolled intersections
FIXED_GREEN = 33
FIXED_YELLOW = 3
FIXED_RED = 30

# Spawn deviation for cloned intersections (±20%)
SPAWN_CLONE_DEVIATION = 0.20

# CoLight duration-mode: must match DURATION_BUCKETS_SEC in colight_env.py
DURATION_BUCKETS_SEC = (10, 20, 30, 40)
_MAX_BUCKET = float(max(DURATION_BUCKETS_SEC))

# ── Shared state ──────────────────────────────────────────────────────

_deploy_lock = threading.Lock()
_deploy_active = False
_deploy_thread: threading.Thread | None = None
_agent_enabled = True  # Runtime toggle: False = fixed-time on all controlled TLs

_deploy_status: dict = {
    "running": False,
    "step": 0,
    "num_sumo_vehicles": 0,
    "video_complete": False,
    "model_path": None,
    "tl_id": None,
    "tl_ids": [],
    "network_id": None,
    "last_action": None,
    "is_multi_agent": False,
    "controlled_tl_ids": [],
    "fixed_tl_ids": [],
    "agent_enabled": True,
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


def _find_boundary_edges_in_network(conn) -> dict:
    """Find edges at the boundary of the real OSM network for vehicle spawning.

    A boundary edge is one whose 'from' or 'to' node is a dead-end
    (degree 1 in the network graph, or connects to only boundary nodes).
    We look for edges whose source node has no other incoming internal edges.
    """
    all_edges = conn.edge.getIDList()
    # Filter out internal edges (start with ':')
    external_edges = [e for e in all_edges if not e.startswith(':')]

    # Build node degree map
    node_in_edges: dict[str, list[str]] = {}
    node_out_edges: dict[str, list[str]] = {}
    edge_from: dict[str, str] = {}
    edge_to: dict[str, str] = {}

    for eid in external_edges:
        try:
            from_node = conn.edge.getParameter(eid, "from")
            to_node = conn.edge.getParameter(eid, "to")
        except Exception:
            # Fallback: get from lane info
            lanes = conn.edge.getLaneNumber(eid)
            if lanes == 0:
                continue
            lane_id = f"{eid}_0"
            try:
                shape = conn.lane.getShape(lane_id)
                from_node = f"node_{shape[0]}"
                to_node = f"node_{shape[-1]}"
            except Exception:
                continue

        edge_from[eid] = from_node
        edge_to[eid] = to_node
        node_out_edges.setdefault(from_node, []).append(eid)
        node_in_edges.setdefault(to_node, []).append(eid)

    # Boundary nodes: nodes with only outgoing or only incoming edges
    boundary_entry_edges = []  # edges going INTO the network from boundary
    boundary_exit_edges = []   # edges going OUT of the network to boundary

    all_nodes = set(list(node_in_edges.keys()) + list(node_out_edges.keys()))
    for node in all_nodes:
        in_count = len(node_in_edges.get(node, []))
        out_count = len(node_out_edges.get(node, []))

        # Dead-end nodes (only have edges in one direction)
        if in_count > 0 and out_count == 0:
            # This node only receives traffic — edges TO this node are exit edges
            for eid in node_in_edges[node]:
                boundary_exit_edges.append(eid)
        elif out_count > 0 and in_count == 0:
            # This node only sends traffic — edges FROM this node are entry edges
            for eid in node_out_edges[node]:
                boundary_entry_edges.append(eid)

    return {
        "entry": boundary_entry_edges,
        "exit": boundary_exit_edges,
    }


def _feed_vehicles_osm_network(
    tracked: list[dict],
    vehicle_ids: set[str],
    entry_edges: list[str],
    exit_edges: list[str],
) -> set[str]:
    """Feed vehicles into OSM network. Spawns at boundary entry edges with ±20% cloning.

    ±20% deviation means:
      - Each clone has a 20% chance to be SKIPPED (so ~80% spawn)
      - There's also a 20% chance to spawn an EXTRA vehicle at a random entry edge
    This creates natural variation in spawn counts across intersections.
    """
    visible_ids: set[str] = set()

    for veh in tracked:
        veh_id = f"v_{veh['id']}"
        region = veh.get("region")
        if region is None:
            continue

        visible_ids.add(veh_id)
        _direction_tracker.update(veh["id"], region)

        if veh_id not in vehicle_ids:
            # New vehicle detected in video — spawn at boundary edges
            if not entry_edges or not exit_edges:
                continue

            # Pick a primary entry edge (randomly)
            primary_entry = random.choice(entry_edges)
            primary_exit = random.choice(exit_edges)

            # Spawn primary vehicle
            route = [primary_entry, primary_exit]
            if _sumo.add_vehicle(veh_id, route, pos=0.1, speed=max(veh.get("speed", 0.0), 1.0)):
                _sumo.update_vehicle_speed(veh_id, -1)
                vehicle_ids.add(veh_id)

                # Clone to other entry edges with ±20% deviation
                for idx, edge in enumerate(entry_edges):
                    if edge == primary_entry:
                        continue
                    # -20%: skip this clone with 20% probability
                    if random.random() < SPAWN_CLONE_DEVIATION:
                        continue  # Skipped (-20% deviation)

                    clone_id = f"{veh_id}_c{idx}"
                    clone_exit = random.choice(exit_edges)
                    clone_route = [edge, clone_exit]
                    if _sumo.add_vehicle(clone_id, clone_route, pos=0.1, speed=max(veh.get("speed", 0.0), 1.0)):
                        _sumo.update_vehicle_speed(clone_id, -1)
                        vehicle_ids.add(clone_id)

                # +20%: chance to spawn extra vehicle at a random entry edge
                if random.random() < SPAWN_CLONE_DEVIATION:
                    extra_entry = random.choice(entry_edges)
                    extra_exit = random.choice(exit_edges)
                    extra_id = f"{veh_id}_extra"
                    extra_route = [extra_entry, extra_exit]
                    if _sumo.add_vehicle(extra_id, extra_route, pos=0.1, speed=max(veh.get("speed", 0.0), 1.0)):
                        _sumo.update_vehicle_speed(extra_id, -1)
                        vehicle_ids.add(extra_id)
        else:
            # Known vehicle — also mark all its clones as visible
            for cid in list(vehicle_ids):
                if cid.startswith(veh_id + "_"):
                    visible_ids.add(cid)

    # Remove departed vehicles (primary + all clones)
    departed = vehicle_ids - visible_ids
    for vid in departed:
        _sumo.remove_vehicle(vid)
        if vid.startswith("v_") and "_c" not in vid and "_extra" not in vid:
            try:
                orig_id = int(vid.split("_")[1])
                _direction_tracker.remove(orig_id)
            except Exception:
                pass
    vehicle_ids -= departed

    return vehicle_ids


def _feed_vehicles_grid(tracked: list[dict], vehicle_ids: set[str], grid_rows: int, grid_cols: int) -> set[str]:
    """Feed vehicles into grid network with ±20% clone deviation."""
    visible_ids: set[str] = set()

    for veh in tracked:
        veh_id = f"v_{veh['id']}"
        region = veh.get("region")
        if region is None:
            continue

        visible_ids.add(veh_id)
        _direction_tracker.update(veh["id"], region)

        if veh_id not in vehicle_ids:
            entry_region = region
            exit_region = OPPOSITE_DIRECTION.get(entry_region, "south")

            entry_edges = get_boundary_entry_edges(grid_rows, grid_cols).get(entry_region, [])
            exit_edges_list = get_boundary_exit_edges(grid_rows, grid_cols).get(exit_region, [])

            if not entry_edges:
                continue

            spawned_any = False
            for idx, (_, _, entry_eid) in enumerate(entry_edges):
                if not exit_edges_list:
                    continue

                # Primary vehicle always spawns at idx 0
                if idx > 0:
                    # -20%: skip this clone with 20% probability
                    if random.random() < SPAWN_CLONE_DEVIATION:
                        continue

                _, _, exit_eid = random.choice(exit_edges_list)
                route_id = f"route_{entry_eid}_to_{exit_eid}"
                vid = veh_id if idx == 0 else f"{veh_id}_g{idx}"

                if _sumo.add_vehicle(vid, route_id, pos=0.1, speed=max(veh.get("speed", 0.0), 1.0)):
                    _sumo.update_vehicle_speed(vid, -1)
                    vehicle_ids.add(vid)
                    spawned_any = True

            # +20%: chance to spawn extra vehicle at a random entry edge
            if spawned_any and random.random() < SPAWN_CLONE_DEVIATION and entry_edges and exit_edges_list:
                _, _, extra_entry_eid = random.choice(entry_edges)
                _, _, extra_exit_eid = random.choice(exit_edges_list)
                extra_route_id = f"route_{extra_entry_eid}_to_{extra_exit_eid}"
                extra_vid = f"{veh_id}_extra"
                if _sumo.add_vehicle(extra_vid, extra_route_id, pos=0.1, speed=max(veh.get("speed", 0.0), 1.0)):
                    _sumo.update_vehicle_speed(extra_vid, -1)
                    vehicle_ids.add(extra_vid)

            if not spawned_any:
                visible_ids.discard(veh_id)
        else:
            # Known vehicle — mark all its clones as visible too
            for cid in list(vehicle_ids):
                if cid.startswith(veh_id + "_"):
                    visible_ids.add(cid)

            if _direction_tracker.is_route_updated(veh["id"]):
                new_exit_region = _direction_tracker.get_exit_direction(veh["id"])
                if new_exit_region:
                    exit_edges_list = get_boundary_exit_edges(grid_rows, grid_cols).get(new_exit_region, [])
                    if exit_edges_list:
                        _, _, exit_eid = random.choice(exit_edges_list)
                        _sumo.reroute_vehicle(veh_id, exit_eid)
                        for idx in range(1, 10):
                            clone_id = f"{veh_id}_g{idx}"
                            if clone_id in vehicle_ids:
                                _sumo.reroute_vehicle(clone_id, exit_eid)

    departed = vehicle_ids - visible_ids
    for vid in departed:
        _sumo.remove_vehicle(vid)
        if vid.startswith("v_") and "_g" not in vid and "_extra" not in vid:
            try:
                orig_id = int(vid.split("_")[1])
                _direction_tracker.remove(orig_id)
            except Exception:
                pass
    vehicle_ids -= departed

    return vehicle_ids


# ── Public API ───────────────────────────────────────────────────────


def start_deploy(model_path: str, tl_id: str | None = None, grid_rows: int = 2, grid_cols: int = 3, network_id: str | None = None) -> dict:
    global _deploy_active, _deploy_thread, _snapshot_data, _agent_enabled

    with _deploy_lock:
        if _deploy_active:
            return {"status": "already_running"}

        _deploy_active = True
        _agent_enabled = True
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
            "is_multi_agent": False,
            "controlled_tl_ids": [],
            "fixed_tl_ids": [],
            "agent_enabled": True,
        })

    # Load model first to determine if it's multi-agent
    load_result = _model.load(model_path)
    logger.info("Model loaded: %s", load_result)

    with _deploy_lock:
        _deploy_status["is_multi_agent"] = _model.is_multi_agent
        if _model.is_multi_agent:
            _deploy_status["tl_ids"] = _model.tl_ids

    _deploy_thread = threading.Thread(
        target=_deploy_loop,
        args=(tl_id, grid_rows, grid_cols, network_id),
        daemon=True,
        name="deploy-loop",
    )
    _deploy_thread.start()

    return {"status": "started", "is_multi_agent": _model.is_multi_agent}


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
        if _snapshot_data:
            snapshot = dict(_snapshot_data)
        else:
            snapshot = {"step": 0, "running": _deploy_status.get("running", False)}

    # Backfill geometry if snapshot exists but geometry is missing/empty.
    geometry = snapshot.get("network_geometry")
    has_geometry = bool(
        geometry
        and isinstance(geometry, dict)
        and geometry.get("junctions")
        and geometry.get("edges")
    )
    if snapshot.get("running") and not has_geometry:
        try:
            if _sumo.running:
                geom = _sumo.get_network_geometry()
                if geom.get("junctions") and geom.get("edges"):
                    snapshot["network_geometry"] = geom
                    with _deploy_lock:
                        if _snapshot_data:
                            _snapshot_data["network_geometry"] = geom
        except Exception:
            pass

    return snapshot


def toggle_agent(enabled: bool) -> dict:
    global _agent_enabled
    with _deploy_lock:
        _agent_enabled = enabled
        _deploy_status["agent_enabled"] = enabled
    logger.info("Agent control %s", "ENABLED" if enabled else "DISABLED")
    return {"agent_enabled": enabled}


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
        is_multi = _model.is_multi_agent
        use_saved_network = False
        net_path = None
        route_path = None

        # ── Step 1: Resolve network ──────────────────────────────────
        if network_id:
            saved_net = SAVED_NETWORKS_DIR / f"{network_id}.net.xml"
            if saved_net.exists():
                net_path = saved_net
                use_saved_network = True
                logger.info("Using saved OSM network: %s", net_path)

                # Check for existing route file
                saved_route = SAVED_NETWORKS_DIR / f"{network_id}_moderate.rou.xml"
                if saved_route.exists():
                    route_path = saved_route
                    logger.info("Using saved route file: %s", route_path)
            else:
                logger.warning("Saved network not found: %s. Falling back to grid.", saved_net)

        if net_path is None:
            # Generate grid network
            ensure_sumo_network(DEPLOY_SUMO_DIR, rows=grid_rows, cols=grid_cols, rebuild=True)
            net_path = DEPLOY_SUMO_DIR / "grid_network.net.xml"
            route_path = DEPLOY_SUMO_DIR / "route.rou.xml"

        if not net_path.exists():
            raise FileNotFoundError(f"SUMO network not found: {net_path}")

        # ── Step 2: Start SUMO ───────────────────────────────────────
        _sumo.start(net_path, route_file=route_path)
        conn = _sumo.get_connection()

        # ── Step 3: Configure traffic lights ─────────────────────────
        all_tl_ids = _sumo.get_all_tl_ids()
        logger.info("Network has %d traffic lights: %s", len(all_tl_ids), all_tl_ids)

        if is_multi:
            # Multi-agent: AI controls trained intersections, fixed-time for the rest
            controlled_tl_ids = [t for t in _model.tl_ids if t in all_tl_ids]
            fixed_tl_ids = [t for t in all_tl_ids if t not in controlled_tl_ids]

            if not controlled_tl_ids:
                logger.warning(
                    "No trained TL IDs found in network! Trained: %s, Available: %s",
                    _model.tl_ids, all_tl_ids,
                )
                # Fall back to controlling the first N TLs
                n = min(_model.num_intersections, len(all_tl_ids))
                controlled_tl_ids = all_tl_ids[:n]
                fixed_tl_ids = all_tl_ids[n:]

            # Install fixed-time on uncontrolled intersections
            _sumo.install_fixed_time_on_all(
                green_duration=FIXED_GREEN,
                yellow_duration=FIXED_YELLOW,
                red_duration=FIXED_RED,
                exclude_tl_ids=controlled_tl_ids,
            )

            logger.info(
                "Multi-agent deploy: AI controls %s, fixed-time on %s",
                controlled_tl_ids, fixed_tl_ids,
            )

            with _deploy_lock:
                _deploy_status["controlled_tl_ids"] = controlled_tl_ids
                _deploy_status["fixed_tl_ids"] = fixed_tl_ids
                _deploy_status["tl_ids"] = controlled_tl_ids

        else:
            # Single-agent: one TL controlled by AI
            target_tl_id = tl_id
            if target_tl_id is None:
                target_tl_id = _sumo.get_tl_id()

            controlled_tl_ids = [target_tl_id]
            fixed_tl_ids = [t for t in all_tl_ids if t != target_tl_id]

            # Install fixed-time baseline on the controlled TL (AI will override)
            _sumo.install_fixed_time_program(
                FIXED_GREEN_DURATION,
                FIXED_YELLOW_DURATION,
                tl_id=target_tl_id,
            )

            # Install fixed-time on all other TLs
            if fixed_tl_ids:
                _sumo.install_fixed_time_on_all(
                    green_duration=FIXED_GREEN,
                    yellow_duration=FIXED_YELLOW,
                    red_duration=FIXED_RED,
                    exclude_tl_ids=controlled_tl_ids,
                )

            with _deploy_lock:
                _deploy_status["controlled_tl_ids"] = controlled_tl_ids
                _deploy_status["fixed_tl_ids"] = fixed_tl_ids

        # ── Step 4: Prepare observation helpers for single-agent ─────
        if not is_multi:
            target_tl_id = controlled_tl_ids[0]
            controlled_lanes = _sumo.get_controlled_lanes(target_tl_id)
            green_indices = _get_green_phase_indices(conn, target_tl_id)
        else:
            target_tl_id = None
            controlled_lanes = []
            green_indices = []

        # Per-TL state for CoLight duration-bucket mode
        _elapsed_in_green: dict[str, int] = {tid: 0 for tid in controlled_tl_ids}
        _current_green_idx_map: dict[str, int] = {tid: 0 for tid in controlled_tl_ids}

        # Compute max_lanes across all controlled TLs for uniform obs padding
        _max_lanes: int = 0
        if is_multi and controlled_tl_ids:
            for ctl_id in controlled_tl_ids:
                try:
                    lanes = list(set(conn.trafficlight.getControlledLanes(ctl_id)))
                    _max_lanes = max(_max_lanes, len(lanes))
                except Exception:
                    pass

        # ── Step 5: Detect boundary edges for spawning ───────────────
        boundary_edges = None
        if use_saved_network:
            try:
                boundary_edges = _find_boundary_edges_in_network(conn)
                logger.info(
                    "Found %d entry edges, %d exit edges in OSM network",
                    len(boundary_edges["entry"]), len(boundary_edges["exit"]),
                )
            except Exception as exc:
                logger.warning("Failed to detect boundary edges: %s", exc)

        # ── Step 6: Main loop ────────────────────────────────────────
        logger.info("Deploy loop started (multi=%s, controlled=%s)", is_multi, controlled_tl_ids)

        # ── Cache network geometry (static — only needs to be fetched once) ─
        network_geometry = _sumo.get_network_geometry() if _sumo.running else {}

        start_background_loop()
        reset_video_complete_flag()
        reset_waiting_history()

        veh_ids: set[str] = set()
        _direction_tracker.__init__()
        _prev_agent_on = True  # track previous tick to detect transitions

        while _deploy_active:
            start_background_loop()
            tracked = get_tracked_vehicles()

            # Feed vehicles
            if use_saved_network and boundary_edges:
                veh_ids = _feed_vehicles_osm_network(
                    tracked, veh_ids,
                    boundary_edges["entry"],
                    boundary_edges["exit"],
                )
            else:
                veh_ids = _feed_vehicles_grid(tracked, veh_ids, grid_rows, grid_cols)

            metrics = _sumo.step()
            last_action = _deploy_status.get("last_action")

            # ── Agent toggle: install fixed-time when agent is switched off ──
            agent_on = _agent_enabled
            if not agent_on and _prev_agent_on:
                # Switched OFF: put AI-controlled TLs onto fixed-time so they keep cycling
                _sumo.install_fixed_time_on_all(
                    green_duration=FIXED_GREEN,
                    yellow_duration=FIXED_YELLOW,
                    red_duration=FIXED_RED,
                    exclude_tl_ids=fixed_tl_ids,
                )
                logger.info("Agent disabled — installed fixed-time on controlled TLs")
            _prev_agent_on = agent_on

            # ── AI decision step ─────────────────────────────────────
            if agent_on and DEPLOY_DECISION_INTERVAL_STEPS > 0 and metrics["step"] % DEPLOY_DECISION_INTERVAL_STEPS == 0:
                if is_multi:
                    # Multi-agent: build observations for all controlled TLs
                    observations = []
                    for ctl_id in controlled_tl_ids:
                        obs = _sumo.build_observation_for_tl(
                            ctl_id,
                            _model.num_actions,
                            max_lanes=_max_lanes if _max_lanes > 0 else None,
                            elapsed_in_green=_elapsed_in_green.get(ctl_id, 0),
                            max_bucket=_MAX_BUCKET,
                        )
                        obs_arr = np.array(obs, dtype=np.float32)
                        if obs_arr.size < _model.ob_length:
                            obs_arr = np.concatenate([
                                obs_arr,
                                np.zeros(_model.ob_length - obs_arr.size, dtype=np.float32),
                            ])
                        elif obs_arr.size > _model.ob_length:
                            obs_arr = obs_arr[:_model.ob_length]
                        observations.append(obs_arr)

                    # Pad if we have fewer controlled TLs than model expects
                    while len(observations) < _model.num_intersections:
                        observations.append(np.zeros(_model.ob_length, dtype=np.float32))

                    obs_matrix = np.stack(observations[:_model.num_intersections])
                    actions = _model.predict_multi(obs_matrix)

                    # Apply duration-bucket logic (matches CoLight training in colight_env.py)
                    for i, ctl_id in enumerate(controlled_tl_ids):
                        if i >= len(actions):
                            break
                        action = int(actions[i])
                        gi = _get_green_phase_indices(conn, ctl_id)
                        num_green = len(gi)
                        current_idx = _current_green_idx_map.get(ctl_id, 0)

                        if num_green > 1:
                            bucket = action % len(DURATION_BUCKETS_SEC)
                            target_age = DURATION_BUCKETS_SEC[bucket]
                            elapsed = _elapsed_in_green.get(ctl_id, 0)

                            if elapsed >= target_age:
                                new_idx = (current_idx + 1) % num_green
                                sumo_phase = gi[new_idx]
                                try:
                                    conn.trafficlight.setPhase(ctl_id, int(sumo_phase))
                                except Exception as exc:
                                    logger.debug("Failed to set phase on %s: %s", ctl_id, exc)
                                _current_green_idx_map[ctl_id] = new_idx
                                _elapsed_in_green[ctl_id] = 0

                    # Advance elapsed counters for all controlled TLs
                    for ctl_id in controlled_tl_ids:
                        _elapsed_in_green[ctl_id] = _elapsed_in_green.get(ctl_id, 0) + DEPLOY_DECISION_INTERVAL_STEPS

                    last_action = actions.tolist() if len(actions) > 1 else int(actions[0])

                else:
                    # Single-agent
                    observation = _build_observation(
                        conn, target_tl_id, controlled_lanes,
                        _model.num_actions, green_indices,
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

            # ── Build snapshot ───────────────────────────────────────
            frame_data = get_latest_frame()

            # Get all TL states for multi-agent view
            if is_multi:
                tl_states = _sumo.get_all_traffic_light_states() if _sumo.running else {}
            else:
                tl_states = _sumo.get_traffic_light_state(target_tl_id) if _sumo.running else {}

            snapshot = {
                "step": metrics["step"],
                "running": True,
                "video_frame": frame_data.get("image"),
                "video_frame_annotated": frame_data.get("image_annotated"),
                "video_timestamp": frame_data.get("timestamp", 0.0),
                "vehicles": _sumo.get_vehicles() if _sumo.running else [],
                "tl_state": tl_states,
                "metrics": {
                    "num_vehicles": metrics["num_vehicles"],
                    "total_waiting_time": round(metrics["total_waiting_time"], 1),
                    "avg_speed": round(metrics["avg_speed"], 2),
                    "arrived": metrics["arrived"],
                },
                "ai_action": last_action,
                "is_multi_agent": is_multi,
                "agent_enabled": agent_on,
                "controlled_tl_ids": controlled_tl_ids,
                "fixed_tl_ids": fixed_tl_ids,
                "network_geometry": network_geometry,
            }

            with _deploy_lock:
                _snapshot_data = snapshot
                _deploy_status["step"] = metrics["step"]
                _deploy_status["num_sumo_vehicles"] = metrics["num_vehicles"]
                _deploy_status["tl_id"] = target_tl_id if not is_multi else None
                _deploy_status["last_action"] = last_action

            if is_video_complete():
                logger.info("Video completed — deploy run finished")
                with _deploy_lock:
                    _deploy_status["video_complete"] = True
                try:
                    history = get_waiting_history()
                    chart_path = default_chart_path(RESULT_DIR, tag="deploy")
                    save_waiting_timeseries_chart(history, chart_path)
                    logger.info("Waiting-count chart saved: %s", chart_path)
                except Exception:
                    logger.exception("Failed to save waiting-count chart")
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
