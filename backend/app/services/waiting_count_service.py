"""Waiting count service – analyse ~1 second of traffic video with YOLO.

Adapted from ``script_count_waiting.py``.  All heavy-weight assets
(``regions.json``, ``script_stream.py``, YOLO weights) are expected in
``backend/app/digital_twin/``.
"""

from __future__ import annotations

import logging
import math
import sys
from collections import defaultdict
from pathlib import Path

import cv2

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# backend/app/digital_twin/
DIGITAL_TWIN_DIR = Path(__file__).resolve().parent.parent / "digital_twin"

# Default video used when we have no real camera feed
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "traffic_video"
DEFAULT_VIDEO = DATA_DIR / "video.MOV"

# YOLO model inside digital_twin/
MODEL_PATH = DIGITAL_TWIN_DIR / "yolo11x.pt"

# ---------------------------------------------------------------------------
# Constants (same as script_count_waiting.py)
# ---------------------------------------------------------------------------
TRACKED_CLASS_IDS = {2, 3, 5, 8}       # car, motorcycle, bus, truck
METERS_PER_PIXEL = 50 / 1420
WAITING_SPEED_THRESHOLD = 2.0           # m/s

# ---------------------------------------------------------------------------
# Region helpers – try to import from digital_twin/script_stream.py,
# fall back to simple quadrant-based detection.
# ---------------------------------------------------------------------------

_region_helpers_loaded = False

try:
    # Make the digital_twin folder importable
    if str(DIGITAL_TWIN_DIR) not in sys.path:
        sys.path.insert(0, str(DIGITAL_TWIN_DIR))
    from script_stream import detect_region, load_regions_from_json  # type: ignore
    _region_helpers_loaded = True
    logger.info("Loaded region helpers from digital_twin/script_stream.py")
except ImportError:
    logger.warning(
        "digital_twin/script_stream.py not found – "
        "using quadrant-based direction detection as fallback"
    )

    def detect_region(cx: float, cy: float, regions) -> str | None:  # noqa: D401
        """Fallback: assign direction based on frame quadrant."""
        if regions is None:
            return None
        w, h = regions  # (width, height) tuple used as fallback
        if cy < h / 2:
            return "north" if cx >= w / 2 else "west"
        else:
            return "east" if cx >= w / 2 else "south"

    def load_regions_from_json(path: str):
        """Fallback: return None (no polygon regions available)."""
        return None


# ---------------------------------------------------------------------------
# Speed calculator (from script_count_waiting.py)
# ---------------------------------------------------------------------------

class SpeedCalculator:
    """Track per-vehicle positions and compute smoothed instantaneous speed."""

    def __init__(self, fps: float, smoothing: float = 0.3):
        self.fps = fps
        self.smoothing = smoothing
        self.tracks: dict = {}

    def update(self, object_id: int, cx: float, cy: float,
               frame_count: int, region: str | None):
        if object_id not in self.tracks:
            self.tracks[object_id] = {
                "last_frame": frame_count,
                "last_cx": cx,
                "last_cy": cy,
                "speed_ms": 0.0,
                "entry_region": region,
            }
            return 0.0, region

        track = self.tracks[object_id]
        frame_diff = frame_count - track["last_frame"]

        if frame_diff > 0:
            distance_px = math.hypot(cx - track["last_cx"], cy - track["last_cy"])
            distance_m = distance_px * METERS_PER_PIXEL
            time_sec = frame_diff / self.fps
            raw_speed = distance_m / time_sec
            track["speed_ms"] = (
                self.smoothing * raw_speed
                + (1 - self.smoothing) * track["speed_ms"]
            )

        track["last_frame"] = frame_count
        track["last_cx"] = cx
        track["last_cy"] = cy
        return track["speed_ms"], track["entry_region"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_waiting_count(id_camera: str) -> dict:
    """Open the traffic video, track for ~1 s, return waiting counts.

    Parameters
    ----------
    id_camera:
        Camera identifier (placeholder – always uses the default video).

    Returns
    -------
    dict with keys ``id_camera``, ``north``, ``south``, ``east``, ``west``,
    ``total``.
    """
    from ultralytics import YOLO  # lazy import – heavy dependency

    video_path = str(DEFAULT_VIDEO)
    logger.info("Processing video %s for camera %s", video_path, id_camera)

    # --- Load YOLO model ---
    model = YOLO(str(MODEL_PATH))
    model.verbose = False

    # --- Open video ---
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video file: {video_path}")

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    frames_for_one_sec = int(fps)  # how many frames ≈ 1 second

    # --- Load regions ---
    regions_file = DIGITAL_TWIN_DIR / "regions.json"
    if _region_helpers_loaded and regions_file.exists():
        regions = load_regions_from_json(str(regions_file))
    else:
        # fallback: pass (width, height) so quadrant helper works
        regions = (width, height)

    # --- Run YOLO tracking for ~1 second of video ---
    speed_calc = SpeedCalculator(fps)
    waiting_by_dir: dict[str, set] = defaultdict(set)
    frame_count = 0

    vid_stride = 1
    track_results = model.track(
        source=video_path,
        imgsz=960,
        conf=0.4,
        show=False,
        stream=True,
        verbose=False,
        persist=True,
        tracker="botsort.yaml",
        vid_stride=vid_stride,
        half=False,
    )

    for results in track_results:
        frame_count += 1
        if frame_count > frames_for_one_sec:
            break

        for box in results.boxes:
            if box.id is None:
                continue

            object_id = int(box.id[0])
            cls = int(box.cls[0])

            if cls not in TRACKED_CLASS_IDS:
                continue

            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2

            region = detect_region(cx, cy, regions)

            speed_ms, _ = speed_calc.update(
                object_id, cx, cy, frame_count * vid_stride, region
            )

            if region is not None and speed_ms < WAITING_SPEED_THRESHOLD:
                waiting_by_dir[region].add(object_id)

    directions = ["north", "south", "east", "west"]
    counts = {d: len(waiting_by_dir[d]) for d in directions}
    total = sum(counts.values())

    logger.info(
        "Camera %s — waiting: N=%d S=%d E=%d W=%d total=%d (processed %d frames)",
        id_camera,
        counts["north"], counts["south"], counts["east"], counts["west"],
        total, frame_count,
    )

    return {
        "id_camera": id_camera,
        "north": counts["north"],
        "south": counts["south"],
        "east": counts["east"],
        "west": counts["west"],
        "total": total,
    }
