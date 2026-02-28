import os
import json
from pathlib import Path
from dotenv import load_dotenv
from service.topology import CAM_TO_INTERSECTION

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", 10))

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Default to /data/dataset in Docker, fallback to project dataset folder
DATASET_DIR = Path(
    os.getenv("DATASET_DIR", os.getenv("DATASET_PATH", PROJECT_ROOT / "dataset"))
)

CAMERA_IDS = list(CAM_TO_INTERSECTION.keys())