"""
Real-Time Video → SUMO Digital Twin via TraCI

This script processes a traffic video frame-by-frame using YOLO detection/tracking,
and mirrors each detected vehicle's actual position into a running SUMO simulation
using traci.vehicle.moveToXY(). This creates a true digital twin where SUMO reflects
the real-world traffic state observed in the video.

Another application can connect to SUMO to read the live traffic state.

Usage:
    python script_realtime.py --video data/tphcm/tphcm-2p.MOV [--gui] [--sumo-port 8813]
"""

import cv2
import os
import sys
import math
import json
import argparse
import time as _time
import threading
import queue
from pathlib import Path
import numpy as np
import xml.etree.ElementTree as ET
from ultralytics import YOLO
import yaml
from ultralytics.cfg import IterableSimpleNamespace
from ultralytics.trackers.bot_sort import BOTSORT
from ultralytics.engine.results import Boxes
import torch

# SAHI imports for sliced inference (small object detection)
from sahi import AutoDetectionModel
from sahi.predict import get_sliced_prediction

# --- SUMO/TraCI imports ---
if "SUMO_HOME" in os.environ:
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
else:
    print("WARNING: SUMO_HOME environment variable is not set.")
    print("Please set it to your SUMO installation directory.")

import traci
import traci.constants as tc

# ============================================================
# Helper Functions (formerly from stash.script_stream)
# ============================================================

def generate_type_file(output_file):
    """
    Generate Type.XML file for SUMO with both 1-lane and 2-lane road types.
    """
    root = ET.Element("types")

    # 1-lane type (for South and West)
    ET.SubElement(root, "type", 
                  id="1L45", 
                  numLanes="1", 
                  speed="12.5")  # 45 km/h = 12.5 m/s

    # 2-lane type (for North and East)
    ET.SubElement(root, "type", 
                  id="2L45", 
                  numLanes="2", 
                  speed="12.5")  # 45 km/h = 12.5 m/s

    tree = ET.ElementTree(root)
    tree.write(output_file, encoding="utf-8", xml_declaration=True)


def draw_polygonal_region(frame, regions, alpha=0.4):
    """
    Draw region of interest (polygons) for better understanding and analyzing.
    """
    for region, data in regions.items():
        points = np.array(data["points"], dtype=np.int32)
        color = tuple(data["color"])
        light_color = tuple(min(c + 50, 255) for c in color)

        temp_frame = frame.copy()
        cv2.fillPoly(temp_frame, [points], light_color)
        cv2.addWeighted(temp_frame, alpha, frame, 1 - alpha, 0, frame)
        cv2.polylines(frame, [points], isClosed=True, color=color, thickness=2)

        # Draw text in the center of the polygon
        cx, cy = np.mean(points, axis=0).astype(int)
        cv2.putText(
            frame,
            region.upper(),
            (cx - 50, cy),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6, 
            color, 
            2
        )


def detect_region(cx, cy, regions):
    """
    Detect the region (north, south, etc.) based on the given point (cx,cy). 
    """
    detected_region = None
    for region, data in regions.items():
        points = np.array(data["points"], dtype=np.int32)
        is_inside = cv2.pointPolygonTest(points, (cx, cy), False)

        if is_inside >= 0:
            detected_region = region
            break
    return detected_region


def load_regions_from_json(json_file_path):
    """
    Load region definitions from a JSON file.
    """
    try:
        with open(json_file_path, 'r') as f:
            regions_data = json.load(f)
        
        # Convert lists to tuples for OpenCV compatibility
        regions = {}
        for region_name, data in regions_data.items():
            regions[region_name] = {
                "points": [tuple(point) for point in data["points"]],
                "color": tuple(data["color"])
            }
        print(f"Loaded {len(regions)} regions from {json_file_path}")
        return regions
    except FileNotFoundError:
        print(f"Error: JSON file not found at {json_file_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON file: {e}")
        return None

# ============================================================
# Constants
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
SIM_REALTIME_DIR = BASE_DIR / "simulate_real_traffic"
DEFAULT_VIDEO_PATH = SIM_REALTIME_DIR / "data" / "tphcm" / "output-2p-light.MOV"
DEFAULT_REGIONS_DIR = SIM_REALTIME_DIR / "regions" / "tphcm"
DEFAULT_SUMO_DIR = SIM_REALTIME_DIR / "sumo"
DEFAULT_MODEL_DIR = SIM_REALTIME_DIR / "model"
DEFAULT_BOTSORT_CFG = SIM_REALTIME_DIR / "botsort.yaml"

# Map YOLO class indices to vehicle class names
VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

# YOLO class IDs we want to track
TRACKED_CLASS_IDS = {2, 3, 5, 8}

# Pre-defined vehicle type dimensions for SUMO
# Default acceleration = 1.5 m/s², max velocity = 10 m/s for all types
VTYPE_DIMENSIONS = {
    "motorcycle": {
        "length": "2.2", "width": "0.8", "minGap": "0.5",
        "minGapLat": "0.3", "maxSpeedLat": "1.0", "latAlignment": "center",
        "accel": "2", "decel": "6.0", "sigma": "0.5",
        "guiShape": "motorcycle",
    },
    "car": {
        "length": "4.5", "width": "1.8", "minGap": "2.0",
        "minGapLat": "0.6", "maxSpeedLat": "0.5", "latAlignment": "center",
        "accel": "1.5", "decel": "5.0", "sigma": "0.5",
        "guiShape": "passenger",
    },
    "bus": {
        "length": "12.0", "width": "2.5", "minGap": "2.5",
        "minGapLat": "0.8", "maxSpeedLat": "0.3", "latAlignment": "center",
        "accel": "1.5", "decel": "4.0", "sigma": "0.5",
        "guiShape": "bus",
    },
    "truck": {
        "length": "8.0", "width": "2.3", "minGap": "2.5",
        "minGapLat": "0.7", "maxSpeedLat": "0.4", "latAlignment": "center",
        "accel": "1.5", "decel": "4.5", "sigma": "0.5",
        "guiShape": "truck",
    },
}

# ============================================================
# 3×2 Grid Network Layout
# ============================================================
#
#  3 columns (c0, c1, c2) × 2 rows (r0=top, r1=bottom) = 6 intersections
#
#        c0         c1         c2
#  r0:  i_0_0 --- i_0_1 --- i_0_2      (top row)
#         |          |          |
#  r1:  i_1_0 --- i_1_1 --- i_1_2      (bottom row)
#
#  Outside boundary edges (where vehicles can enter/exit):
#    North: top of row 0    (i_0_0, i_0_1, i_0_2)
#    South: bottom of row 1 (i_1_0, i_1_1, i_1_2)
#    West:  left of col 0   (i_0_0, i_1_0)
#    East:  right of col 2  (i_0_2, i_1_2)
#

import random
from collections import deque

GRID_ROWS = 2
GRID_COLS = 3
EDGE_LENGTH = 100  # meters between intersections

OPPOSITE_DIRECTION = {
    "north": "south", "south": "north",
    "east": "west",   "west": "east",
}

# Variance applied to spawn count per intersection (±10%)
SPAWN_VARIANCE = 0.10

# Number of frames a vehicle can be missing before being removed
LOST_VEHICLE_THRESHOLD = 30  # ~1 second at 30fps

# Minimum cumulative pixel displacement before a vehicle is injected into SUMO.
MIN_MOVEMENT_PX = 20.0

# Default max speed in m/s
DEFAULT_MAX_SPEED_MS = 15.0

# --- Phase 1: Trajectory-based entry detection ---
ENTRY_VELOCITY_VECTORS = {
    "north": (0.0,  1.0),
    "south": (0.0, -1.0),
    "east":  (-1.0, 0.0),
    "west":  (1.0,  0.0),
}
MIN_TRAJECTORY_POINTS = 5
MIN_DIRECTION_CONFIDENCE = 0.4

# Ground truth vehicle counts for validation
GROUND_TRUTH_COUNTS = {
    "east": 78,
    "north": 91,
    "south": 49,
    "west": 103,
}


def _node_id(row, col):
    """Intersection node ID for grid position (row, col)."""
    return f"i_{row}_{col}"


def _boundary_node_id(direction, row, col):
    """Boundary node ID for an outside entry/exit point."""
    return f"b_{direction}_{row}_{col}"


def _edge_id(from_node, to_node):
    """Generate a unique edge ID from two node IDs."""
    return f"e_{from_node}_to_{to_node}"


# ============================================================
# Network Setup Functions (3×2 Grid)
# ============================================================

def _build_all_edge_ids():
    """Return a list of all edge IDs in the 3×2 grid."""
    edges = []
    # Internal horizontal
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS - 1):
            n1, n2 = _node_id(r, c), _node_id(r, c + 1)
            edges.extend([_edge_id(n1, n2), _edge_id(n2, n1)])
    # Internal vertical
    for r in range(GRID_ROWS - 1):
        for c in range(GRID_COLS):
            n1, n2 = _node_id(r, c), _node_id(r + 1, c)
            edges.extend([_edge_id(n1, n2), _edge_id(n2, n1)])
    # Boundary edges
    for c in range(GRID_COLS):
        bn, inode = _boundary_node_id("north", 0, c), _node_id(0, c)
        edges.extend([_edge_id(bn, inode), _edge_id(inode, bn)])
    for c in range(GRID_COLS):
        bn, inode = _boundary_node_id("south", GRID_ROWS - 1, c), _node_id(GRID_ROWS - 1, c)
        edges.extend([_edge_id(bn, inode), _edge_id(inode, bn)])
    for r in range(GRID_ROWS):
        bn, inode = _boundary_node_id("west", r, 0), _node_id(r, 0)
        edges.extend([_edge_id(bn, inode), _edge_id(inode, bn)])
    for r in range(GRID_ROWS):
        bn, inode = _boundary_node_id("east", r, GRID_COLS - 1), _node_id(r, GRID_COLS - 1)
        edges.extend([_edge_id(bn, inode), _edge_id(inode, bn)])
    return edges


def generate_grid_nod_file(output_file):
    """Generate nodes for the 3×2 grid network."""
    root = ET.Element("nodes")
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            x = c * EDGE_LENGTH
            y = (GRID_ROWS - 1 - r) * EDGE_LENGTH
            ET.SubElement(root, "node", id=_node_id(r, c),
                          x=str(x), y=str(y), type="traffic_light")
    # Boundary nodes
    for c in range(GRID_COLS):
        ET.SubElement(root, "node", id=_boundary_node_id("north", 0, c),
                      x=str(c * EDGE_LENGTH),
                      y=str((GRID_ROWS - 1) * EDGE_LENGTH + EDGE_LENGTH), type="priority")
    for c in range(GRID_COLS):
        ET.SubElement(root, "node", id=_boundary_node_id("south", GRID_ROWS - 1, c),
                      x=str(c * EDGE_LENGTH), y=str(-EDGE_LENGTH), type="priority")
    for r in range(GRID_ROWS):
        ET.SubElement(root, "node", id=_boundary_node_id("west", r, 0),
                      x=str(-EDGE_LENGTH),
                      y=str((GRID_ROWS - 1 - r) * EDGE_LENGTH), type="priority")
    for r in range(GRID_ROWS):
        ET.SubElement(root, "node", id=_boundary_node_id("east", r, GRID_COLS - 1),
                      x=str((GRID_COLS - 1) * EDGE_LENGTH + EDGE_LENGTH),
                      y=str((GRID_ROWS - 1 - r) * EDGE_LENGTH), type="priority")
    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ")
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    print(f"Generated 3×2 grid node file: {output_file}")


def generate_grid_edg_file(output_file):
    """Generate edges for the 3×2 grid (bidirectional internal + boundary)."""
    root = ET.Element("edges")
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS - 1):
            n1, n2 = _node_id(r, c), _node_id(r, c + 1)
            ET.SubElement(root, "edge", **{"from": n1, "to": n2, "id": _edge_id(n1, n2), "type": "2L45", "numLanes": "2"})
            ET.SubElement(root, "edge", **{"from": n2, "to": n1, "id": _edge_id(n2, n1), "type": "2L45", "numLanes": "2"})
    for r in range(GRID_ROWS - 1):
        for c in range(GRID_COLS):
            n1, n2 = _node_id(r, c), _node_id(r + 1, c)
            ET.SubElement(root, "edge", **{"from": n1, "to": n2, "id": _edge_id(n1, n2), "type": "2L45", "numLanes": "2"})
            ET.SubElement(root, "edge", **{"from": n2, "to": n1, "id": _edge_id(n2, n1), "type": "2L45", "numLanes": "2"})
    for c in range(GRID_COLS):
        bn, inode = _boundary_node_id("north", 0, c), _node_id(0, c)
        ET.SubElement(root, "edge", **{"from": bn, "to": inode, "id": _edge_id(bn, inode), "type": "2L45", "numLanes": "2"})
        ET.SubElement(root, "edge", **{"from": inode, "to": bn, "id": _edge_id(inode, bn), "type": "2L45", "numLanes": "2"})
    for c in range(GRID_COLS):
        bn, inode = _boundary_node_id("south", GRID_ROWS - 1, c), _node_id(GRID_ROWS - 1, c)
        ET.SubElement(root, "edge", **{"from": bn, "to": inode, "id": _edge_id(bn, inode), "type": "2L45", "numLanes": "2"})
        ET.SubElement(root, "edge", **{"from": inode, "to": bn, "id": _edge_id(inode, bn), "type": "2L45", "numLanes": "2"})
    for r in range(GRID_ROWS):
        bn, inode = _boundary_node_id("west", r, 0), _node_id(r, 0)
        ET.SubElement(root, "edge", **{"from": bn, "to": inode, "id": _edge_id(bn, inode), "type": "2L45", "numLanes": "2"})
        ET.SubElement(root, "edge", **{"from": inode, "to": bn, "id": _edge_id(inode, bn), "type": "2L45", "numLanes": "2"})
    for r in range(GRID_ROWS):
        bn, inode = _boundary_node_id("east", r, GRID_COLS - 1), _node_id(r, GRID_COLS - 1)
        ET.SubElement(root, "edge", **{"from": bn, "to": inode, "id": _edge_id(bn, inode), "type": "2L45", "numLanes": "2"})
        ET.SubElement(root, "edge", **{"from": inode, "to": bn, "id": _edge_id(inode, bn), "type": "2L45", "numLanes": "2"})
    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ")
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    print(f"Generated 3×2 grid edge file: {output_file}")


def get_boundary_entry_edges():
    """Return dict: direction → list of (boundary_node, intersection_node, entry_edge_id)."""
    entries = {"north": [], "south": [], "west": [], "east": []}
    for c in range(GRID_COLS):
        bn, inode = _boundary_node_id("north", 0, c), _node_id(0, c)
        entries["north"].append((bn, inode, _edge_id(bn, inode)))
    for c in range(GRID_COLS):
        bn, inode = _boundary_node_id("south", GRID_ROWS - 1, c), _node_id(GRID_ROWS - 1, c)
        entries["south"].append((bn, inode, _edge_id(bn, inode)))
    for r in range(GRID_ROWS):
        bn, inode = _boundary_node_id("west", r, 0), _node_id(r, 0)
        entries["west"].append((bn, inode, _edge_id(bn, inode)))
    for r in range(GRID_ROWS):
        bn, inode = _boundary_node_id("east", r, GRID_COLS - 1), _node_id(r, GRID_COLS - 1)
        entries["east"].append((bn, inode, _edge_id(bn, inode)))
    return entries


def get_boundary_exit_edges():
    """Return dict: direction → list of (intersection_node, boundary_node, exit_edge_id)."""
    exits = {"north": [], "south": [], "west": [], "east": []}
    for c in range(GRID_COLS):
        bn, inode = _boundary_node_id("north", 0, c), _node_id(0, c)
        exits["north"].append((inode, bn, _edge_id(inode, bn)))
    for c in range(GRID_COLS):
        bn, inode = _boundary_node_id("south", GRID_ROWS - 1, c), _node_id(GRID_ROWS - 1, c)
        exits["south"].append((inode, bn, _edge_id(inode, bn)))
    for r in range(GRID_ROWS):
        bn, inode = _boundary_node_id("west", r, 0), _node_id(r, 0)
        exits["west"].append((inode, bn, _edge_id(inode, bn)))
    for r in range(GRID_ROWS):
        bn, inode = _boundary_node_id("east", r, GRID_COLS - 1), _node_id(r, GRID_COLS - 1)
        exits["east"].append((inode, bn, _edge_id(inode, bn)))
    return exits


def _find_route_edges(entry_edge_id, exit_edge_id):
    """BFS to find shortest route (edge list) between two boundary edges."""
    all_edges = _build_all_edge_ids()
    edge_to_nodes = {}
    node_to_outgoing = {}
    for eid in all_edges:
        parts = eid.split("_to_")
        fn = parts[0][2:]  # strip 'e_'
        tn = parts[1]
        edge_to_nodes[eid] = (fn, tn)
        node_to_outgoing.setdefault(fn, []).append(eid)

    q = deque([[entry_edge_id]])
    visited = {entry_edge_id}
    while q:
        path = q.popleft()
        _, current_to = edge_to_nodes[path[-1]]
        for next_edge in node_to_outgoing.get(current_to, []):
            if next_edge == exit_edge_id:
                return " ".join(path + [next_edge])
            if next_edge not in visited:
                visited.add(next_edge)
                q.append(path + [next_edge])
    return None


def generate_grid_route_file(output_file):
    """Generate route file with vehicle types and all boundary-to-boundary routes."""
    root = ET.Element("routes")
    for cls_name, dims in VTYPE_DIMENSIONS.items():
        attrs = {"id": f"vType_{cls_name}", "maxSpeed": str(DEFAULT_MAX_SPEED_MS)}
        attrs.update(dims)
        ET.SubElement(root, "vType", **attrs)

    entry_edges = get_boundary_entry_edges()
    exit_edges = get_boundary_exit_edges()
    route_count = 0
    for entry_dir, entry_list in entry_edges.items():
        for exit_dir, exit_list in exit_edges.items():
            if entry_dir == exit_dir:
                continue
            for _, _, entry_eid in entry_list:
                for _, _, exit_eid in exit_list:
                    route_str = _find_route_edges(entry_eid, exit_eid)
                    if route_str:
                        route_id = f"route_{entry_eid}_to_{exit_eid}"
                        ET.SubElement(root, "route", id=route_id, edges=route_str)
                        route_count += 1

    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ")
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    print(f"Generated grid route file with {route_count} routes: {output_file}")


def generate_realtime_config(output_file, step_length=0.033):
    """Generate a SUMO config for real-time use with sublane model."""
    root = ET.Element("configuration")
    input_el = ET.SubElement(root, "input")
    ET.SubElement(input_el, "net-file", value="grid_network.net.xml")
    ET.SubElement(input_el, "route-files", value="route.rou.xml")
    time_el = ET.SubElement(root, "time")
    ET.SubElement(time_el, "begin", value="0")
    ET.SubElement(time_el, "step-length", value=f"{step_length:.4f}")
    processing_el = ET.SubElement(root, "processing")
    ET.SubElement(processing_el, "lateral-resolution", value="0.8")
    ET.SubElement(processing_el, "collision.action", value="warn")
    ET.SubElement(processing_el, "collision.mingap-factor", value="0")
    report_el = ET.SubElement(root, "report")
    ET.SubElement(report_el, "verbose", value="true")
    ET.SubElement(report_el, "no-step-log", value="true")
    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ")
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    print(f"Generated real-time config: {output_file}")


def setup_sumo_network(output_dir):
    """Generate all SUMO network files for the 3×2 grid and run netconvert."""
    os.makedirs(output_dir, exist_ok=True)
    nod_path = os.path.join(output_dir, "nod.xml")
    edg_path = os.path.join(output_dir, "edg.xml")
    type_path = os.path.join(output_dir, "type.xml")
    route_path = os.path.join(output_dir, "route.rou.xml")
    net_path = os.path.join(output_dir, "grid_network.net.xml")

    generate_grid_nod_file(nod_path)
    generate_grid_edg_file(edg_path)
    generate_type_file(type_path)
    generate_grid_route_file(route_path)

    netconvert_cmd = (
        f'netconvert --node-files "{nod_path}" '
        f'--edge-files "{edg_path}" '
        f'--type-files "{type_path}" '
        f'-o "{net_path}"'
    )
    print(f"Running: {netconvert_cmd}")
    ret = os.system(netconvert_cmd)
    if ret != 0:
        raise RuntimeError(f"netconvert failed with return code {ret}")
    print("3×2 grid SUMO network files generated successfully!")


def ensure_sumo_network(output_dir, rebuild=False):
    """Return SUMO config path, generating files only when requested.

    By default we reuse the pre-generated network in simulate_real_traffic/sumo.
    """
    output_dir = Path(output_dir)
    config_path = output_dir / "sumo_config.sumocfg"
    net_path = output_dir / "grid_network.net.xml"
    route_path = output_dir / "route.rou.xml"

    if not rebuild and config_path.exists() and net_path.exists() and route_path.exists():
        return config_path

    setup_sumo_network(str(output_dir))
    generate_realtime_config(str(config_path))
    return config_path


class VehicleManager:
    """
    Manages the lifecycle of vehicles in the SUMO simulation.

    Spawn-and-release strategy:
      - When a new vehicle is detected and has moved enough pixels (not parked),
        spawn it at the start of its entry edge with a default straight-through route.
      - Immediately release it to SUMO's autonomous driving (accel=1.5, maxSpeed=10).
      - Do NOT control the vehicle's position after spawn.

    Turn detection:
      - Each frame, check the vehicle's current region from the video (via regions.json).
      - If the current region differs from the entry region, the vehicle has turned.
      - Change the vehicle's route in SUMO to match the observed turn direction.
    """

    def __init__(self):
        self.active_vehicles = {}    # object_id -> {sumo_id, class, entry, last_seen_frame, current_route_exit}
        self.pending_vehicles = {}   # object_id -> {last_cx, last_cy, cumulative_dist, class, entry, last_frame, trajectory}
        self.total_added = 0
        self.total_removed = 0
        self.total_filtered = 0      # Parked vehicles that were never injected
        self.total_rerouted = 0      # Vehicles whose route was changed due to turn detection
        self.total_entry_corrected = 0  # Vehicles whose entry was corrected by trajectory

        # Statistics tracking
        self.spawn_counts = {}       # entry_region -> count
        self.od_counts = {}          # (entry_region, exit_region) -> count

    def update_vehicle(self, object_id, px_cx, px_cy, vehicle_class,
                       entry_region, current_region, frame_count):
        """
        Update a vehicle. If new, check movement filter then spawn.
        If already active, check for turn detection and reroute if needed.

        :param object_id: YOLO tracker ID
        :param px_cx: Pixel center X
        :param px_cy: Pixel center Y
        :param vehicle_class: 'car', 'motorcycle', 'bus', 'truck'
        :param entry_region: The region where the vehicle first appeared
        :param current_region: The region the vehicle is currently in
        :param frame_count: Current frame number
        """

        # ---- Movement Distance Filter for new vehicles ----
        if object_id not in self.active_vehicles:
            if object_id not in self.pending_vehicles:
                # First time seeing this vehicle — start tracking displacement
                self.pending_vehicles[object_id] = {
                    "last_cx": px_cx,
                    "last_cy": px_cy,
                    "cumulative_dist": 0.0,
                    "class": vehicle_class,
                    "entry": entry_region,
                    "last_frame": frame_count,
                    "trajectory": [(px_cx, px_cy)],
                }
                return False  # Not added to SUMO yet

            # Accumulate displacement
            pending = self.pending_vehicles[object_id]
            dx = px_cx - pending["last_cx"]
            dy = px_cy - pending["last_cy"]
            pending["cumulative_dist"] += math.hypot(dx, dy)
            pending["last_cx"] = px_cx
            pending["last_cy"] = px_cy
            pending["last_frame"] = frame_count
            pending["trajectory"].append((px_cx, px_cy))

            # Update entry if it was None before and now we have a region
            if pending["entry"] is None and entry_region is not None:
                pending["entry"] = entry_region

            if pending["cumulative_dist"] < MIN_MOVEMENT_PX:
                return False  # Still hasn't moved enough — probably parked

            # Vehicle has moved enough! Promote to active with spawn-and-release.
            # Use trajectory-based entry detection to correct misattributed directions
            initial_entry = pending["entry"]
            entry_region = self._resolve_entry_by_trajectory(
                pending["trajectory"], initial_entry
            )
            del self.pending_vehicles[object_id]

            if entry_region is None:
                return False  # Can't spawn without knowing entry direction

            sumo_id = f"veh_{object_id}"
            if not self._spawn_vehicle(sumo_id, vehicle_class, entry_region):
                return False

            # Default route exit is straight through (opposite direction)
            actual_entry = entry_region if entry_region in OPPOSITE_DIRECTION else "north"
            default_exit = OPPOSITE_DIRECTION.get(entry_region, "south")
            self.active_vehicles[object_id] = {
                "sumo_id": sumo_id,
                "class": vehicle_class,
                "entry": actual_entry,
                "last_seen_frame": frame_count,
                "current_route_exit": default_exit,
            }
            self.total_added += 1

            # Update stats
            self.spawn_counts[actual_entry] = self.spawn_counts.get(actual_entry, 0) + 1
            self.od_counts[(actual_entry, default_exit)] = self.od_counts.get((actual_entry, default_exit), 0) + 1

            return True

        # ---- Known active vehicle: check for turn detection ----
        info = self.active_vehicles[object_id]
        info["last_seen_frame"] = frame_count

        if current_region is not None and current_region != info["entry"]:
            # Vehicle is now in a different region than where it entered.
            # This means it turned! Update route if not already set.
            if info["current_route_exit"] != current_region:
                self._reroute_vehicle(info, current_region)

        return True

    def _spawn_vehicle(self, sumo_id, vehicle_class, entry_region):
        """
        Spawn a vehicle at ALL boundary entry edges for the given direction
        across the 3×2 grid, with ±10% variance per intersection.
        
        E.g., if entry_region="south", spawns at all 3 south boundary edges
        (one per column), each with ~10% chance to skip or spawn an extra.
        """
        vtype_id = f"vType_{vehicle_class}"
        exit_region = OPPOSITE_DIRECTION.get(entry_region, "south")
        if entry_region not in OPPOSITE_DIRECTION:
            entry_region = "north"
            exit_region = "south"

        entry_edges = get_boundary_entry_edges()[entry_region]
        exit_edges_list = get_boundary_exit_edges()[exit_region]
        preferred_lane = 0 if vehicle_class == "motorcycle" else 1

        spawned_any = False
        for idx, (_, _, entry_eid) in enumerate(entry_edges):
            _, _, exit_eid = random.choice(exit_edges_list)
            route_id = f"route_{entry_eid}_to_{exit_eid}"

            if idx == 0:
                vid = sumo_id
            else:
                # ±10% variance: ~10% chance to skip this intersection
                if random.random() < SPAWN_VARIANCE:
                    continue
                vid = f"{sumo_id}_g{idx}"

            try:
                traci.vehicle.add(
                    vehID=vid, routeID=route_id, typeID=vtype_id,
                    depart="now", departLane=str(preferred_lane),
                    departSpeed="max", departPos="0.1",
                )
                traci.vehicle.setSpeedMode(vid, 31)
                traci.vehicle.setLaneChangeMode(vid, 1621)
                traci.vehicle.setSpeed(vid, -1)
                print(f"  [+] Spawned {vid} ({vehicle_class}) on {entry_eid}")
                spawned_any = True
            except traci.exceptions.TraCIException as e:
                print(f"  [!] Failed to add {vid}: {e}")

        # ~10% chance to spawn one extra clone at a random entry for this direction
        if random.random() < SPAWN_VARIANCE and entry_edges:
            _, _, entry_eid = random.choice(entry_edges)
            _, _, exit_eid = random.choice(exit_edges_list)
            route_id = f"route_{entry_eid}_to_{exit_eid}"
            extra_vid = f"{sumo_id}_extra"
            try:
                traci.vehicle.add(
                    vehID=extra_vid, routeID=route_id, typeID=vtype_id,
                    depart="now", departLane=str(preferred_lane),
                    departSpeed="max", departPos="0.1",
                )
                traci.vehicle.setSpeedMode(extra_vid, 31)
                traci.vehicle.setLaneChangeMode(extra_vid, 1621)
                traci.vehicle.setSpeed(extra_vid, -1)
                print(f"  [+] Extra spawn {extra_vid} ({vehicle_class}) on {entry_eid}")
            except traci.exceptions.TraCIException:
                pass

        return spawned_any

    def _reroute_vehicle(self, info, new_exit_region):
        """
        Change a vehicle's route when a turn is detected in the video.

        The vehicle entered from info['entry'] and is now observed in
        new_exit_region, so we change its SUMO route accordingly.
        """
        sumo_id = info["sumo_id"]
        entry = info["entry"]

        # In the grid network, rerouting is done by changing the vehicle's target edge
        # to a random exit edge on the new exit direction
        exit_edges_list = get_boundary_exit_edges().get(new_exit_region, [])
        if not exit_edges_list:
            return

        try:
            _, _, exit_eid = random.choice(exit_edges_list)
            traci.vehicle.changeTarget(sumo_id, exit_eid)

            old_exit = info["current_route_exit"]
            info["current_route_exit"] = new_exit_region
            self.total_rerouted += 1

            # Update stats
            if (entry, old_exit) in self.od_counts:
                self.od_counts[(entry, old_exit)] -= 1
                if self.od_counts[(entry, old_exit)] <= 0:
                    del self.od_counts[(entry, old_exit)]
            self.od_counts[(entry, new_exit_region)] = self.od_counts.get((entry, new_exit_region), 0) + 1

            print(f"  [↪] Rerouted {sumo_id}: "
                  f"{entry}→{old_exit} => {entry}→{new_exit_region}")
        except traci.exceptions.TraCIException as e:
            print(f"  [!] Failed to reroute {sumo_id}: {e}")

    def _resolve_entry_by_trajectory(self, trajectory, initial_region):
        """
        Use the accumulated trajectory (list of (cx, cy) pixel coords) to
        determine the true entry direction based on the vehicle's movement
        vector, rather than relying solely on the region of first detection.

        This fixes the North→South misattribution problem: vehicles from the
        North that are first detected in the South region will be correctly
        identified by their downward movement vector.
        """
        if len(trajectory) < MIN_TRAJECTORY_POINTS:
            return initial_region  # Not enough data, use region-based detection

        if initial_region is None:
            return None

        # Use first N points to compute average velocity vector
        n = min(len(trajectory), 15)
        points = trajectory[:n]
        avg_dx = (points[-1][0] - points[0][0]) / max(n - 1, 1)
        avg_dy = (points[-1][1] - points[0][1]) / max(n - 1, 1)

        # Normalize the velocity vector
        mag = math.hypot(avg_dx, avg_dy)
        if mag < 1e-6:
            return initial_region  # No meaningful movement
        avg_dx /= mag
        avg_dy /= mag

        # Compute cosine similarity with each entry direction vector
        best_dir = initial_region
        best_sim = -1.0
        for direction, (ref_dx, ref_dy) in ENTRY_VELOCITY_VECTORS.items():
            sim = avg_dx * ref_dx + avg_dy * ref_dy
            if sim > best_sim:
                best_sim = sim
                best_dir = direction

        # Only override if confidence is above threshold
        if best_dir != initial_region and best_sim > MIN_DIRECTION_CONFIDENCE:
            print(f"  [📐] Entry corrected by trajectory: {initial_region} → {best_dir} "
                  f"(cosine_sim={best_sim:.2f}, points={n})")
            self.total_entry_corrected += 1
            return best_dir

        return initial_region

    def cleanup_pending_vehicles(self, current_frame):
        """
        Remove pending vehicles that haven't been seen for a while.
        These are parked cars that never moved enough to be injected.
        """
        to_remove = []
        for object_id, info in self.pending_vehicles.items():
            if current_frame - info["last_frame"] > LOST_VEHICLE_THRESHOLD:
                to_remove.append(object_id)

        for object_id in to_remove:
            del self.pending_vehicles[object_id]
            self.total_filtered += 1

    def cleanup_lost_vehicles(self, current_frame):
        """
        Remove vehicles from tracking that haven't been detected for
        LOST_VEHICLE_THRESHOLD frames. The vehicle continues to exist
        in SUMO and drives itself out of the network autonomously.
        """
        to_cleanup = []

        for object_id, info in self.active_vehicles.items():
            frames_missing = current_frame - info["last_seen_frame"]

            if frames_missing > LOST_VEHICLE_THRESHOLD:
                sumo_id = info["sumo_id"]
                try:
                    # Verify vehicle still exists in simulation
                    traci.vehicle.getPosition(sumo_id)
                    # Vehicle is still driving — just stop tracking it
                    self.total_removed += 1
                    print(f"  [~] Released tracking of {sumo_id} "
                          f"(still driving autonomously in SUMO)")
                except traci.exceptions.TraCIException:
                    # Vehicle already left the network
                    self.total_removed += 1
                to_cleanup.append(object_id)

        for object_id in to_cleanup:
            del self.active_vehicles[object_id]


# ============================================================
# Threaded Pipeline Components
# ============================================================

class FrameReader:
    """Background thread that decodes video frames into a queue (sequential, no skipping)."""

    def __init__(self, video_path, max_queue_size=2):
        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
            raise IOError(f"Error opening video file: {video_path}")
        
        # Read the rotation metadata to apply it manually
        self.rotation_angle = self.cap.get(cv2.CAP_PROP_ORIENTATION_META)
        
        # Disable auto-orientation so we can manually rotate it correctly
        if hasattr(cv2, 'CAP_PROP_ORIENTATION_AUTO'):
            self.cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 0)

        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # Swap width/height if rotated 90 or 270 degrees
        if self.rotation_angle in [90.0, 270.0]:
            self.width, self.height = self.height, self.width
            
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._queue = queue.Queue(maxsize=max_queue_size)
        self._stop_event = threading.Event()
        self._frame_index = 0
        self._total_skipped = 0
        self._lock = threading.Lock()
        self._wall_start = _time.monotonic()
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def _reader_loop(self):
        """Read every frame sequentially — no skipping for tracking accuracy."""
        while not self._stop_event.is_set():
            with self._lock:
                ret, frame = self.cap.read()
                if not ret:
                    self._queue.put(None)
                    return
                
                # Apply rotation manually if needed
                if self.rotation_angle == 180.0:
                    frame = cv2.rotate(frame, cv2.ROTATE_180)
                elif self.rotation_angle == 90.0:
                    frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                elif self.rotation_angle == 270.0:
                    frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
                    
                self._frame_index += 1
                idx = self._frame_index
            try:
                self._queue.put((idx, frame), timeout=1.0)
            except queue.Full:
                if self._stop_event.is_set():
                    return
                continue

    def read(self):
        try:
            return self._queue.get(timeout=2.0)
        except queue.Empty:
            return None

    @property
    def frame_index(self):
        with self._lock:
            return self._frame_index

    @property
    def total_skipped(self):
        with self._lock:
            return self._total_skipped

    def stop(self):
        self._stop_event.set()
        self._thread.join(timeout=3.0)
        self.cap.release()


class TraCIWorker:
    """
    Background thread for all SUMO/TraCI communication.
    Main thread queues commands; this thread executes them serially,
    hiding ~5-10ms IPC latency behind the next YOLO inference.
    """

    def __init__(self):
        self._queue = queue.Queue(maxsize=64)
        self._stop_event = threading.Event()
        self._error = None
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()

    def _worker_loop(self):
        while not self._stop_event.is_set():
            try:
                cmd = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if cmd is None:
                return
            try:
                cmd()
            except traci.exceptions.TraCIException as e:
                self._error = e

    def submit(self, fn):
        """Queue a callable to be executed on the TraCI thread."""
        self._queue.put(fn)

    def flush(self):
        """Wait until all queued commands are processed."""
        self._queue.join() if hasattr(self._queue, 'join') else None

    @property
    def error(self):
        return self._error

    def stop(self):
        self._stop_event.set()
        self._queue.put(None)
        self._thread.join(timeout=3.0)


def process_video_realtime(
    video_path,
    regions_dir,
    output_dir,
    use_gui=True,
    sumo_port=None,
    rebuild_network=False,
):
    """
    3-thread real-time pipeline:
      Thread 1 (FrameReader):  CPU video decode → queue
      Thread 2 (Main):         YOLO inference (GPU) + detection processing
      Thread 3 (TraCIWorker):  SUMO IPC (spawn, reroute, simulationStep)

    Plus: YOLO runs every 2nd frame (INFER_STRIDE=2) to halve GPU load.
    On non-inference frames, only SUMO time is advanced.
    """

    # --- Load YOLO model ---
    # Prefer TensorRT engine if available (3-5× faster), fall back to .pt
    # Engine must be exported at imgsz=1280 to match inference size
    engine_path = DEFAULT_MODEL_DIR / "yolo11x_1280.engine"
    pt_path = DEFAULT_MODEL_DIR / "yolo11x.pt"
    if os.path.exists(engine_path):
        model_name = engine_path
        print(f"Using TensorRT engine: {engine_path} (optimized for imgsz=1280)")
    else:
        model_name = pt_path
        print(f"Using PyTorch model: {pt_path}")
        print("  TIP: Export TensorRT engine at 1280 for 3-5× speedup:")
        print(f'       python -c "from ultralytics import YOLO; YOLO(\'{pt_path}\').export(format=\'engine\', half=True, imgsz=1280)"')
        print(f"       Then rename the output to {engine_path}")
    model = YOLO(model_name)
    model.verbose = False

    # --- Initialize SAHI detection model (wraps the same YOLO model) ---
    # SAHI slices the frame into overlapping tiles for better small-object
    # detection (e.g. distant motorcycles), then merges the results via NMS.
    sahi_model = AutoDetectionModel.from_pretrained(
        model_type="ultralytics",   # matches sahi.models.ultralytics module
        model_path=model_name,
        confidence_threshold=0.15,
        image_size=1280,            # match original imgsz for per-slice inference
        device="cuda:0" if torch.cuda.is_available() else "cpu",
    )
    print(f"SAHI detection model initialized (device={'cuda:0' if torch.cuda.is_available() else 'cpu'})")

    # --- Initialize standalone BoTSORT tracker ---
    # We manage the tracker ourselves because SAHI replaces model.track().
    # Load the same botsort.yaml config to keep behavior identical.
    with open(DEFAULT_BOTSORT_CFG, "r") as f:
        tracker_cfg = yaml.safe_load(f)
    tracker_args = IterableSimpleNamespace(**tracker_cfg)
    # The tracker needs a 'model' attribute for ReID; set to 'auto' (disabled)
    if not hasattr(tracker_args, 'model'):
        tracker_args.model = 'auto'
    
    # CRITICAL: Match tracker threshold with YOLO confidence so we don't drop low-conf vehicles
    # By default new_track_thresh is 0.7 and track_high_thresh is 0.5, which causes BOTSORT
    # to completely ignore distant vehicles or SAHI detections with confidence between 0.25 and 0.5.
    tracker_args.track_high_thresh = 0.15
    tracker_args.track_low_thresh = 0.05
    tracker_args.new_track_thresh = 0.15
    
    sahi_tracker = None  # Will be created once we know the FPS

    # --- Start threaded frame reader ---
    reader = FrameReader(video_path, max_queue_size=2)
    fps = reader.fps
    width = reader.width
    height = reader.height
    step_length = 1.0 / fps

    print(f"Video: {width}x{height} @ {fps:.2f} FPS (step_length={step_length:.4f}s)")
    print(f"Pipeline: Threaded reader (queue=2) + SAHI sliced inference + BoTSORT")

    # Create the BoTSORT tracker now that we know the video FPS
    sahi_tracker = BOTSORT(args=tracker_args, frame_rate=int(fps))
    print(f"SAHI BoTSORT tracker initialized (frame_rate={int(fps)}, track_buffer={tracker_args.track_buffer})")

    # SAHI slice parameters — tuned for traffic surveillance
    # Slices of 640×640 with 20% overlap give good coverage for small motorcycles
    SAHI_SLICE_HEIGHT = 640
    SAHI_SLICE_WIDTH = 640
    SAHI_OVERLAP_RATIO = 0.2

    # --- Setup SUMO network ---
    config_path = ensure_sumo_network(output_dir, rebuild=rebuild_network)

    # --- Start SUMO ---
    sumo_binary = "sumo-gui" if use_gui else "sumo"
    sumo_cmd = [sumo_binary, "-c", str(config_path), "--start"]

    if sumo_port:
        traci.start(sumo_cmd, port=sumo_port)
    else:
        traci.start(sumo_cmd)

    print(f"SUMO started ({'GUI' if use_gui else 'headless'}) with config: {config_path}")

    # --- Configure traffic lights for all 6 grid intersections ---
    # Logic: N/S green together, E/W green together, opposite to each other.
    # We inspect each intersection's controlled links to determine which
    # signal indices correspond to N/S edges vs E/W edges.
    tl_ids = traci.trafficlight.getIDList()
    print(f"Configuring traffic lights for {len(tl_ids)} intersections: {tl_ids}")
    for tl_id in tl_ids:
        controlled_links = traci.trafficlight.getControlledLinks(tl_id)
        current_logic = traci.trafficlight.getAllProgramLogics(tl_id)
        if not current_logic:
            continue
        state_len = len(current_logic[0].phases[0].state)

        # Classify each signal index as N/S or E/W based on the incoming edge
        # In our grid, vertical edges connect rows (N/S direction),
        # horizontal edges connect columns (E/W direction),
        # boundary north/south edges are vertical, boundary east/west are horizontal.
        ns_indices = set()
        ew_indices = set()
        for idx, links in enumerate(controlled_links):
            if not links:
                continue
            incoming_edge = links[0][0]  # (incoming_edge, outgoing_edge, via_lane)
            # Determine direction from edge name
            # Vertical (N/S): edges between rows or north/south boundary
            # Horizontal (E/W): edges between columns or east/west boundary
            if "_north_" in incoming_edge or "_south_" in incoming_edge:
                # Boundary north/south edges → vertical → N/S direction
                ns_indices.add(idx)
            elif "_east_" in incoming_edge or "_west_" in incoming_edge:
                # Boundary east/west edges → horizontal → E/W direction
                ew_indices.add(idx)
            else:
                # Internal edges: check if it connects rows (vertical) or columns (horizontal)
                # e_i_R1_C1_to_i_R2_C2: if columns match → vertical (N/S), if rows match → horizontal (E/W)
                parts = incoming_edge.replace("e_i_", "").split("_to_i_")
                if len(parts) == 2:
                    src_parts = parts[0].split("_")
                    dst_parts = parts[1].split("_")
                    if len(src_parts) >= 2 and len(dst_parts) >= 2:
                        src_col, dst_col = src_parts[1], dst_parts[1]
                        src_row, dst_row = src_parts[0], dst_parts[0]
                        if src_col == dst_col:
                            ns_indices.add(idx)  # Same column = vertical = N/S
                        elif src_row == dst_row:
                            ew_indices.add(idx)  # Same row = horizontal = E/W
                        else:
                            ns_indices.add(idx)  # Fallback
                else:
                    ns_indices.add(idx)  # Fallback

        # Build state strings: N/S green + E/W red, then swap
        ns_green_state = list("r" * state_len)
        for i in ns_indices:
            if i < state_len:
                ns_green_state[i] = "G"
        ns_green_str = "".join(ns_green_state)

        ns_yellow_state = list("r" * state_len)
        for i in ns_indices:
            if i < state_len:
                ns_yellow_state[i] = "y"
        ns_yellow_str = "".join(ns_yellow_state)

        ew_green_state = list("r" * state_len)
        for i in ew_indices:
            if i < state_len:
                ew_green_state[i] = "G"
        ew_green_str = "".join(ew_green_state)

        ew_yellow_state = list("r" * state_len)
        for i in ew_indices:
            if i < state_len:
                ew_yellow_state[i] = "y"
        ew_yellow_str = "".join(ew_yellow_state)

        phases = [
            traci.trafficlight.Phase(24, ns_green_str),   # N/S green, E/W red
            traci.trafficlight.Phase(3,  ns_yellow_str),   # N/S yellow, E/W red
            traci.trafficlight.Phase(20, ew_green_str),    # E/W green, N/S red
            traci.trafficlight.Phase(3,  ew_yellow_str),   # E/W yellow, N/S red
        ]
        logic = traci.trafficlight.Logic(
            programID="custom", type=0, currentPhaseIndex=0, phases=phases,
        )
        traci.trafficlight.setProgramLogic(tl_id, logic)
        traci.trafficlight.setProgram(tl_id, "custom")
        traci.trafficlight.setPhase(tl_id, 0)
        traci.trafficlight.setPhaseDuration(tl_id, 14)
        print(f"  TL {tl_id}: {len(ns_indices)} N/S links, {len(ew_indices)} E/W links, state_len={state_len}")
    print(f"Traffic lights configured for {len(tl_ids)} intersections")

    # --- Load regions ---
    regions_path = os.path.join(regions_dir, "regions.json")
    regions = load_regions_from_json(regions_path)
    if regions is None:
        print(f"ERROR: Could not load {regions_path}")
        reader.stop()
        traci.close()
        return

    # --- Load road mask ---
    road_mask_poly = None
    road_mask_path = os.path.join(regions_dir, "road_mask.json")
    if os.path.exists(road_mask_path):
        with open(road_mask_path, "r") as f:
            road_mask_data = json.load(f)
        if "road" in road_mask_data:
            road_mask_poly = np.array(road_mask_data["road"]["points"], dtype=np.int32)
            print(f"Road mask loaded: {len(road_mask_poly)} vertices")
            
    # --- Load SAHI zones ---
    sahi_zones = {}
    sahi_zones_path = os.path.join(regions_dir, "sahi_zones.json")
    if os.path.exists(sahi_zones_path):
        with open(sahi_zones_path, "r") as f:
            sahi_zones = json.load(f)
        print(f"Loaded {len(sahi_zones)} SAHI zones")

    # Pre-compute SAHI zone bounding rectangles (for fast ROI cropping)
    sahi_zone_rects = {}  # zone_name -> (x_min, y_min, x_max, y_max, polygon_np)
    for zone_name, zone_data in sahi_zones.items():
        pts = np.array(zone_data["points"], dtype=np.int32)
        x_min, y_min = pts.min(axis=0)
        x_max, y_max = pts.max(axis=0)
        sahi_zone_rects[zone_name] = {
            "x_min": int(x_min), "y_min": int(y_min),
            "x_max": int(x_max), "y_max": int(y_max),
            "polygon": pts,
            "slice_height": zone_data.get("slice_height", 640),
            "slice_width": zone_data.get("slice_width", 640),
            "overlap_ratio": zone_data.get("overlap_ratio", 0.0),  # Reduced to 0 for performance
        }
    # --- Create vehicle manager (spawn-and-release + turn detection) ---
    vehicle_mgr = VehicleManager()

    # --- Start async TraCI worker ---
    traci_worker = TraCIWorker()


    # --- Tracking state ---
    track_data = {}  # object_id -> list of (frame, cx, cy, speed, label, entry, region)
    processed_count = 0      # frames actually run through YOLO
    infer_count = 0          # frames that actually ran YOLO

    # Only run YOLO every INFER_STRIDE frames — biggest perf win
    INFER_STRIDE = 4

    # Display every N processed frames
    DISPLAY_INTERVAL = 10

    # Cleanup SUMO stale vehicles every N frames
    CLEANUP_INTERVAL = 30

    # Run SAHI only every Nth YOLO inference to avoid lag-induced frame skipping
    SAHI_STRIDE = 3
    ENABLE_SAHI = False  # Set to True to enable SAHI small-object detection

    # --- Process video with YOLO ---
    print("\n=== Starting real-time digital twin ===")
    print(f"Pipeline: reader thread + SAHI(stride={INFER_STRIDE}, slice={SAHI_SLICE_HEIGHT}×{SAHI_SLICE_WIDTH}) + BoTSORT + async TraCI")
    print("Press 'q' in the OpenCV window to stop.\n")

    wall_start = reader._wall_start
    t_infer_ms = 0.0

    try:
        residual_lag_frames = 0
        
        while True:
            # --- Pull next pre-decoded frame from reader thread ---
            item = reader.read()
            if item is None:
                print("End of video.")
                break

            frame_count, frame = item
            processed_count += 1
            current_time = frame_count / fps

            # --- Dynamic Frame Skipping to maintain Real-Time ---
            wall_time = _time.monotonic() - wall_start
            video_time = frame_count / fps
            lag_sec = wall_time - video_time
            
            frames_to_skip = 0
            if lag_sec > 0:
                frames_behind = int(lag_sec * fps)
                if frames_behind > 0:
                    frames_to_skip = min(frames_behind, 8)
                    residual_lag_frames = max(0, frames_behind - 8)
            else:
                residual_lag_frames = 0
                # Running faster than real-time — throttle to match video pace
                if lag_sec < -0.01:  # more than 10ms ahead
                    _time.sleep(min(-lag_sec, 0.5))
            
            if frames_to_skip > 0:
                for _ in range(frames_to_skip):
                    skip_item = reader.read()
                    if skip_item is None:
                        break
                    skip_fc, _ = skip_item
                    processed_count += 1
                    # Step SUMO for skipped frames to keep time synced
                    traci_worker.submit(lambda t=(skip_fc/fps): traci.simulationStep(t))
                
                # Fetch the next valid frame after fast-forwarding
                item = reader.read()
                if item is None:
                    print("End of video after skipping.")
                    break
                frame_count, frame = item
                processed_count += 1
                current_time = frame_count / fps

            # --- Run YOLO only on stride frames OR if we just skipped frames ---
            run_yolo = (processed_count % INFER_STRIDE == 0) or (frames_to_skip > 0)

            if run_yolo:
                infer_count += 1
                t_infer_start = _time.monotonic()
                results_list = model.track(
                    source=frame,
                    imgsz=1280,
                    conf=0.25,
                    half=True,
                    show=False,
                    stream=False,
                    verbose=False,
                    persist=True,
                    tracker="botsort.yaml",
                )
                results = results_list[0] if results_list else None

                all_detections = []
                if results is not None:
                    for box in results.boxes:
                        if box.id is None:
                            continue
                        object_id = int(box.id[0])
                        cls = int(box.cls[0])
                        conf_val = float(box.conf[0])
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        label = model.names.get(cls, f"cls{cls}")
                        all_detections.append({
                            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                            "id": object_id, "conf": conf_val,
                            "cls": cls, "label": label,
                            "source": "yolo",
                        })

                # SAHI on specific zones (only every SAHI_STRIDE-th inference to reduce lag)
                sahi_extra_dets = []
                run_sahi = ENABLE_SAHI and (infer_count % SAHI_STRIDE == 0)
                if run_sahi:
                    for zone_name, zr in sahi_zone_rects.items():
                        pad = 30
                        crop_x1 = max(0, zr["x_min"] - pad)
                        crop_y1 = max(0, zr["y_min"] - pad)
                        crop_x2 = min(width, zr["x_max"] + pad)
                        crop_y2 = min(height, zr["y_max"] + pad)
                        crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]

                        if crop.size == 0:
                            continue

                        sahi_result = get_sliced_prediction(
                            image=crop,
                            detection_model=sahi_model,
                            slice_height=zr["slice_height"],
                            slice_width=zr["slice_width"],
                            overlap_height_ratio=zr["overlap_ratio"],
                            overlap_width_ratio=zr["overlap_ratio"],
                            perform_standard_pred=False,
                            postprocess_type="NMS",
                            postprocess_match_threshold=0.5,
                            verbose=0,
                        )

                        for pred in sahi_result.object_prediction_list:
                            bbox = pred.bbox
                            sx1 = int(bbox.minx) + crop_x1
                            sy1 = int(bbox.miny) + crop_y1
                            sx2 = int(bbox.maxx) + crop_x1
                            sy2 = int(bbox.maxy) + crop_y1
                            sconf = pred.score.value
                            scls = pred.category.id
                            slabel = model.names.get(scls, f"cls{scls}")

                            if scls not in TRACKED_CLASS_IDS:
                                continue

                            scx = (sx1 + sx2) / 2
                            scy = (sy1 + sy2) / 2
                            is_duplicate = False
                            for det in all_detections:
                                dcx = (det["x1"] + det["x2"]) / 2
                                dcy = (det["y1"] + det["y2"]) / 2
                                if abs(scx - dcx) < 50 and abs(scy - dcy) < 50:
                                    ix1 = max(sx1, det["x1"])
                                    iy1 = max(sy1, det["y1"])
                                    ix2 = min(sx2, det["x2"])
                                    iy2 = min(sy2, det["y2"])
                                    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                                    area_s = (sx2 - sx1) * (sy2 - sy1)
                                    area_d = (det["x2"] - det["x1"]) * (det["y2"] - det["y1"])
                                    union = area_s + area_d - inter
                                    if union > 0 and inter / union > 0.3:
                                        is_duplicate = True
                                        break

                            if not is_duplicate:
                                sahi_extra_dets.append({
                                    "x1": sx1, "y1": sy1, "x2": sx2, "y2": sy2,
                                    "id": None,
                                    "conf": sconf, "cls": scls, "label": slabel,
                                    "source": "sahi",
                                })

                t_infer_ms = (_time.monotonic() - t_infer_start) * 1000

                # Road mask filtering
                if road_mask_poly is not None:
                    filtered_dets = []
                    for det in all_detections:
                        dcx = (det["x1"] + det["x2"]) / 2
                        dcy = (det["y1"] + det["y2"]) / 2
                        if cv2.pointPolygonTest(road_mask_poly, (dcx, dcy), False) >= 0:
                            filtered_dets.append(det)
                    all_detections = filtered_dets

                    filtered_sahi = []
                    for det in sahi_extra_dets:
                        dcx = (det["x1"] + det["x2"]) / 2
                        dcy = (det["y1"] + det["y2"]) / 2
                        if cv2.pointPolygonTest(road_mask_poly, (dcx, dcy), False) >= 0:
                            filtered_sahi.append(det)
                    sahi_extra_dets = filtered_sahi

                # Track SAHI detections independently
                final_detections = list(all_detections)  # Start with YOLO tracked detections
                
                if len(sahi_extra_dets) > 0:
                    det_array = [[d["x1"], d["y1"], d["x2"], d["y2"], d["conf"], d["cls"]] for d in sahi_extra_dets]
                    # Put tensor on CPU so tracker's .numpy() calls don't crash
                    det_tensor = torch.tensor(det_array, dtype=torch.float32, device="cpu")
                    boxes = Boxes(det_tensor, orig_shape=frame.shape[:2])
                    tracked_sahi = sahi_tracker.update(boxes, frame)
                    
                    for t in tracked_sahi:
                        x1, y1, x2, y2, track_id, conf, cls, ind = t[:8]
                        # Offset SAHI ID by 100000 to prevent conflict with YOLO IDs
                        object_id = int(track_id) + 100000
                        final_detections.append({
                            "x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2),
                            "id": object_id, "conf": float(conf),
                            "cls": int(cls), "label": model.names.get(int(cls), f"cls{int(cls)}"),
                            "source": "sahi"
                        })
                else:
                    det_tensor = torch.empty((0, 6), dtype=torch.float32, device="cpu")
                    boxes = Boxes(det_tensor, orig_shape=frame.shape[:2])
                    sahi_tracker.update(boxes, frame)

                should_display = (infer_count % (DISPLAY_INTERVAL // INFER_STRIDE or 1) == 0)
                if should_display:
                    display_frame = frame.copy()
                    draw_polygonal_region(display_frame, regions)
                    for zone_name, zr in sahi_zone_rects.items():
                        cv2.polylines(display_frame, [zr["polygon"]], True, (255, 255, 0), 1)
                    if road_mask_poly is not None:
                        cv2.polylines(display_frame, [road_mask_poly], True, (128, 128, 128), 1)

                for det in final_detections:
                    x1, y1, x2, y2 = det["x1"], det["y1"], det["x2"], det["y2"]
                    cls = det["cls"]
                    conf = det["conf"]
                    label = det["label"]
                    object_id = det["id"]

                    if cls not in TRACKED_CLASS_IDS:
                        continue

                    cx = (x1 + x2) / 2
                    cy = (y1 + y2) / 2
                    region = detect_region(cx, cy, regions)
                    
                    if object_id not in track_data:
                        speed = 0.0
                        entry_point = region
                    else:
                        last_frame, last_cx, last_cy, last_speed, *_ = track_data[object_id][-1]
                        frame_diff = frame_count - last_frame
                        if frame_diff > 0:
                            meters_per_pixel = 50 / 1420
                            distance_px = math.hypot(cx - last_cx, cy - last_cy)
                            distance_m = distance_px * meters_per_pixel
                            time_sec = frame_diff / fps
                            speed = (distance_m / time_sec) * 3.6
                        else:
                            speed = last_speed
                        entry_point = None

                    track_data.setdefault(object_id, []).append(
                        (frame_count, cx, cy, speed, label, entry_point, region)
                    )

                    vehicle_class = VEHICLE_CLASSES.get(cls, "car")
                    effective_entry = entry_point if entry_point else (
                        track_data[object_id][0][5] if track_data[object_id] else None
                    )

                    vehicle_mgr.update_vehicle(
                        object_id=object_id,
                        px_cx=cx,
                        px_cy=cy,
                        vehicle_class=vehicle_class,
                        entry_region=effective_entry,
                        current_region=region,
                        frame_count=frame_count,
                    )

                    if should_display:
                        in_sumo = "◉" if object_id in vehicle_mgr.active_vehicles else ""
                        
                        # Use orange for SAHI, green for YOLO
                        color = (0, 165, 255) if det.get("source") == "sahi" else (0, 255, 0)
                        prefix = "SAHI " if det.get("source") == "sahi" else ""
                        
                        cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
                        cv2.putText(
                            display_frame,
                            f"{prefix}ID:{object_id} {label} {speed:.1f}km/h {in_sumo}",
                            (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, color, 2,
                        )

                # --- Cleanup vehicles (batched) ---
                if infer_count % CLEANUP_INTERVAL == 0:
                    vehicle_mgr.cleanup_lost_vehicles(frame_count)
                    vehicle_mgr.cleanup_pending_vehicles(frame_count)
            else:
                should_display = False

            # --- Advance SUMO (async on TraCI thread) ---
            step_time = current_time
            traci_worker.submit(lambda t=step_time: traci.simulationStep(t))

            if traci_worker.error:
                print(f"TraCI error: {traci_worker.error}")
                break

            # --- HUD overlay & display (only on display frames) ---
            if should_display:
                total_skipped = reader.total_skipped
                active_count = len(vehicle_mgr.active_vehicles)
                effective_fps = 1000.0 / t_infer_ms if t_infer_ms > 0 else 0
                wall_elapsed = _time.monotonic() - wall_start
                avg_skip_per_sec = total_skipped / wall_elapsed if wall_elapsed > 0 else 0
                
                if residual_lag_frames > 0:
                    cv2.putText(
                        display_frame,
                        f"WARNING: Behind {residual_lag_frames} frames",
                        (10, 90),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (0, 0, 255), 2,
                    )

                cv2.putText(
                    display_frame,
                    f"Frame: {frame_count} | Time: {current_time:.1f}s | "
                    f"YOLO: {t_infer_ms:.0f}ms ({effective_fps:.1f} FPS) | "
                    f"Skipped: {total_skipped} ({avg_skip_per_sec:.1f}/s)",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 255, 255), 2,
                )
                cv2.putText(
                    display_frame,
                    f"Active: {active_count} | Added: {vehicle_mgr.total_added} | "
                    f"Rerouted: {vehicle_mgr.total_rerouted}",
                    (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 255, 255), 2,
                )
                cv2.imshow("Real-Time Traffic Digital Twin", display_frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    print("\nUser pressed 'q' — stopping.")
                    break

    except KeyboardInterrupt:
        print("\nInterrupted by user.")

    finally:
        total_skipped = reader.total_skipped
        reader.stop()
        traci_worker.stop()

        total_wall = _time.monotonic() - wall_start
        avg_skip = total_skipped / total_wall if total_wall > 0 else 0
        print(f"\n=== Session Summary ===")
        print(f"Frames read (video):  {reader.frame_index}")
        print(f"Frames processed:    {processed_count}")
        print(f"YOLO inferences:     {infer_count}")
        print(f"Frames skipped:      {total_skipped} (avg {avg_skip:.1f}/s)")
        print(f"Vehicles added:      {vehicle_mgr.total_added}")
        print(f"Vehicles released:   {vehicle_mgr.total_removed}")
        print(f"Vehicles rerouted:   {vehicle_mgr.total_rerouted}")
        print(f"Entry corrected:     {vehicle_mgr.total_entry_corrected}")
        print(f"Parked filtered:     {vehicle_mgr.total_filtered}")
        print(f"Still active:        {len(vehicle_mgr.active_vehicles)}")
        print(f"Still pending:       {len(vehicle_mgr.pending_vehicles)}")
        print(f"Total tracked:       {len(track_data)}")


        print(f"\n--- Origin-Destination Statistics ---")
        for entry in sorted(vehicle_mgr.spawn_counts.keys()):
            count = vehicle_mgr.spawn_counts[entry]
            print(f"From {entry.capitalize()}: {count} vehicles")
            
        print("\nDirectional Flows (A -> B):")
        for (entry, exit_reg), count in sorted(vehicle_mgr.od_counts.items()):
            print(f"  {entry.capitalize()} -> {exit_reg.capitalize()}: {count}")

        # --- Validation against ground truth ---
        print(f"\n--- Validation vs Ground Truth ---")
        all_pass = True
        for direction in sorted(GROUND_TRUTH_COUNTS.keys()):
            gt = GROUND_TRUTH_COUNTS[direction]
            sim = vehicle_mgr.spawn_counts.get(direction, 0)
            if gt > 0:
                deviation = abs(sim - gt) / gt * 100
            else:
                deviation = 0.0 if sim == 0 else 100.0
            status = "✅" if deviation < 10 else "⚠️" if deviation < 20 else "❌"
            is_pass = deviation < 10
            if not is_pass:
                all_pass = False
            diff = sim - gt
            sign = "+" if diff >= 0 else ""
            print(f"  {direction.capitalize():6s}: GT={gt:3d}  Sim={sim:3d}  "
                  f"({sign}{diff:3d}, {deviation:5.1f}%) {status}")
        total_gt = sum(GROUND_TRUTH_COUNTS.values())
        total_sim = sum(vehicle_mgr.spawn_counts.get(d, 0) for d in GROUND_TRUTH_COUNTS)
        total_dev = abs(total_sim - total_gt) / total_gt * 100 if total_gt > 0 else 0
        print(f"  {'Total':6s}: GT={total_gt:3d}  Sim={total_sim:3d}  ({total_dev:.1f}%)")
        print(f"  Result: {'ALL PASS ✅' if all_pass else 'NEEDS IMPROVEMENT ⚠️'}")

        cv2.destroyAllWindows()
        try:
            traci.close()
            print("SUMO simulation closed.")
        except Exception:
            pass


# ============================================================
# Entry Point
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Real-Time Video → SUMO Digital Twin via TraCI"
    )
    parser.add_argument(
        "--video", type=str, default=str(DEFAULT_VIDEO_PATH),
        help="Path to the input video file",
    )
    parser.add_argument(
        "--regions-dir", type=str, default=str(DEFAULT_REGIONS_DIR),
        help="Path to the directory containing the regions JSON files (regions.json, road_mask.json, sahi_zones.json)",
    )
    parser.add_argument(
        "--gui", action="store_true", default=True,
        help="Launch SUMO with GUI (default: True)",
    )
    parser.add_argument(
        "--no-gui", action="store_true",
        help="Run SUMO headless (no GUI)",
    )
    parser.add_argument(
        "--output-dir", type=str, default=str(DEFAULT_SUMO_DIR),
        help="Directory for SUMO files (default: simulate_real_traffic/sumo)",
    )
    parser.add_argument(
        "--rebuild-network", action="store_true",
        help="Regenerate SUMO network files in the output directory",
    )
    parser.add_argument(
        "--sumo-port", type=int, default=None,
        help="TraCI port for SUMO (default: auto-assigned)",
    )

    args = parser.parse_args()
    use_gui = not args.no_gui

    if not os.path.exists(args.video):
        print(f"ERROR: Video file not found: {args.video}")
        sys.exit(1)

    process_video_realtime(
        video_path=args.video,
        regions_dir=args.regions_dir,
        output_dir=args.output_dir,
        use_gui=use_gui,
        sumo_port=args.sumo_port,
        rebuild_network=args.rebuild_network,
    )


if __name__ == "__main__":
    main()
