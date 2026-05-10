import os
import json
from pathlib import Path
from dotenv import load_dotenv
from service.topology import CAM_TO_INTERSECTION

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", 10))

# Docker sets DATASET_DIR=/data/dataset; host fallback is repo-relative ./dataset
DATASET_DIR = Path(
    os.getenv("DATASET_DIR") or os.getenv("DATASET_PATH") or "dataset"
)

CAMERA_IDS = list(CAM_TO_INTERSECTION.keys())