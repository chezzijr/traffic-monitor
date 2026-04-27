"""Configuration for the Digital Twin video analysis service."""

from pathlib import Path
import os

# Base directory: services/digital_twin/
BASE_DIR = Path(__file__).resolve().parent.parent

# Video file to loop (simulates a surveillance camera)
VIDEO_PATH = Path(os.getenv(
    "VIDEO_PATH",
    str(BASE_DIR / "data" / "traffic_video" / "tphcm-2p" / "tphcm-2p.MOV"),
))

# YOLO model weights
MODEL_PATH = Path(os.getenv(
    "MODEL_PATH",
    str(BASE_DIR / "model" / "yolo11x.pt"),
))

# Region polygon definitions (sits next to the video file)
REGIONS_PATH = Path(os.getenv(
    "REGIONS_PATH",
    str(BASE_DIR / "data" / "traffic_video" / "tphcm-2p" / "regions.json"),
))

# Service port
PORT = int(os.getenv("PORT", "8001"))

# YOLO tracking constants
TRACKED_CLASS_IDS = {1, 2, 3, 5, 7}   # bicycle, car, motorcycle, bus, truck
METERS_PER_PIXEL = 50 / 1420
WAITING_SPEED_THRESHOLD = 2.0       # m/s — below this, vehicle is "waiting"
YOLO_CONF = float(os.getenv("YOLO_CONF", "0.25"))  # detection confidence
YOLO_VID_STRIDE = int(os.getenv("YOLO_VID_STRIDE", "3"))  # process every Nth frame
YOLO_IMGSZ = int(os.getenv("YOLO_IMGSZ", "960"))

# Traffic light inference: if waiting vehicles >= this threshold, direction is RED
WAITING_VEHICLE_RED_THRESHOLD = int(os.getenv("WAITING_VEHICLE_RED_THRESHOLD", "3"))

# Minimum seconds a light state must hold before it can switch
MIN_LIGHT_DURATION_SECS = int(os.getenv("MIN_LIGHT_DURATION_SECS", "20"))

# ── SUMO Sync Pipeline ───────────────────────────────────────────────

SUMO_HOME = os.getenv("SUMO_HOME", r"C:\Program Files (x86)\Eclipse\Sumo")
SUMO_NETWORK_DIR = Path(os.getenv(
    "SUMO_NETWORK_DIR",
    str(BASE_DIR / "data" / "sumo_network"),
))
SUMO_EDGE_LENGTH = float(os.getenv("SUMO_EDGE_LENGTH", "15.0"))
SUMO_NUM_LANES = int(os.getenv("SUMO_NUM_LANES", "2"))
SUMO_GUI = os.getenv("SUMO_GUI", "0") == "1"

# Steps per action — must match the training env's steps_per_action
STEPS_PER_ACTION = int(os.getenv("STEPS_PER_ACTION", "5"))

# Directory containing trained RL models
RL_MODEL_DIR = Path(os.getenv(
    "RL_MODEL_DIR",
    str(BASE_DIR.parent.parent / "simulation" / "models"),
))

# Fixed-time baseline durations (seconds)
FIXED_GREEN_DURATION = int(os.getenv("FIXED_GREEN_DURATION", "35"))
FIXED_YELLOW_DURATION = int(os.getenv("FIXED_YELLOW_DURATION", "3"))
