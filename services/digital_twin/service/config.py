"""Configuration for the Digital Twin video analysis service."""

from pathlib import Path
import os

# Base directory: services/digital_twin/
BASE_DIR = Path(__file__).resolve().parent.parent

# Real-time digital twin assets
SIM_REALTIME_DIR = Path(os.getenv(
    "SIM_REALTIME_DIR",
    str(BASE_DIR / "simulate_real_traffic"),
))

# Video file to loop (simulates a surveillance camera)
VIDEO_PATH = Path(os.getenv(
    "VIDEO_PATH",
    str(SIM_REALTIME_DIR / "data" / "tphcm" / "output-2p-light.MOV"),
))

# YOLO model weights (Prefer TensorRT engine if available)
_PT_PATH = SIM_REALTIME_DIR / "model" / "yolo11x.pt"
# Check for common engine names
_ENGINE_PATH = SIM_REALTIME_DIR / "model" / "yolo11x.engine"
if not _ENGINE_PATH.exists():
    _ENGINE_PATH = SIM_REALTIME_DIR / "model" / "yolo11x_1280.engine"

MODEL_PATH = Path(os.getenv(
    "MODEL_PATH",
    str(_ENGINE_PATH if _ENGINE_PATH.exists() else _PT_PATH),
))

# Region polygon definitions (sits next to the video file)
REGIONS_PATH = Path(os.getenv(
    "REGIONS_PATH",
    str(SIM_REALTIME_DIR / "regions" / "tphcm" / "regions.json"),
))

# Tracker config (BoT-SORT)
TRACKER_CONFIG = Path(os.getenv(
    "TRACKER_CONFIG",
    str(SIM_REALTIME_DIR / "botsort.yaml"),
))

# Video time annotation base (HH:MM:SS)
VIDEO_START_TIME = os.getenv("VIDEO_START_TIME", "12:00:00")

# Service port
PORT = int(os.getenv("PORT", "8001"))

# YOLO tracking constants
TRACKED_CLASS_IDS = {2, 3, 5, 7}   # car, motorcycle, bus, truck
METERS_PER_PIXEL = 50 / 1420
WAITING_SPEED_THRESHOLD = 2.0       # m/s — below this, vehicle is "waiting"
YOLO_CONF = float(os.getenv("YOLO_CONF", "0.1"))  # detection confidence
YOLO_VID_STRIDE = int(os.getenv("YOLO_VID_STRIDE", "1"))  # process every Nth frame
YOLO_IMGSZ = int(os.getenv("YOLO_IMGSZ", "1280"))
DETECTION_MODE = os.getenv("DETECTION_MODE", "track").lower()  # track | predict
COMPARE_PREDICT = os.getenv("COMPARE_PREDICT", "0") == "1"

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

# Deploy pipeline assets
DEPLOY_SUMO_DIR = Path(os.getenv(
    "DEPLOY_SUMO_DIR",
    str(SIM_REALTIME_DIR / "sumo"),
))
DEPLOY_MODEL_DIR = Path(os.getenv(
    "DEPLOY_MODEL_DIR",
    str(Path("/simulation/models")),
))
DEPLOY_VIDEO_DIR = Path(os.getenv(
    "DEPLOY_VIDEO_DIR",
    str(SIM_REALTIME_DIR / "data"),
))

SAVED_NETWORKS_DIR = Path(os.getenv(
    "SAVED_NETWORKS_DIR",
    str(BASE_DIR.parent.parent / "simulation" / "networks"),
))

# Deploy loop timing
DEPLOY_DECISION_INTERVAL_STEPS = int(os.getenv("DEPLOY_DECISION_INTERVAL_STEPS", "5"))





# Fixed-time baseline durations (seconds)
FIXED_GREEN_DURATION = int(os.getenv("FIXED_GREEN_DURATION", "35"))
FIXED_YELLOW_DURATION = int(os.getenv("FIXED_YELLOW_DURATION", "3"))
