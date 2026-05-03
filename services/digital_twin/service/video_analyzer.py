"""YOLO-based video analyser — counts waiting vehicles per direction.

A background thread processes the configured video only while a viewer
is actively watching (demand-driven).  Call ``start_stream()`` to begin
and ``stop_stream()`` (or let the idle timeout fire) to halt processing.

Public API functions return stale / zero data when the stream is off —
the frontend must call start/stop explicitly.
"""

from __future__ import annotations

import base64
import logging
import math
import threading
import time
from collections import defaultdict

import cv2

from service.config import (
    MODEL_PATH,
    METERS_PER_PIXEL,
    TRACKED_CLASS_IDS,
    VIDEO_PATH,
    WAITING_SPEED_THRESHOLD,
    YOLO_IMGSZ,
    YOLO_CONF,
    YOLO_VID_STRIDE,
    REGIONS_PATH,
)
from service.region_helpers import detect_region, load_regions_from_json

logger = logging.getLogger(__name__)

# ── Shared state (single atomic snapshot) ─────────────────────────────

_snapshot_lock = threading.Lock()
_snapshot: dict = {
    "frame_b64": None,
    "frame_annotated_b64": None,
    "timestamp": 0.0,
    "north": 0, "south": 0, "east": 0, "west": 0, "total": 0,
}

# Per-frame tracked vehicle list for sync pipeline
_vehicle_snapshot: list[dict] = []

# Video completion flag (set when one full loop ends)
_video_complete = False

# ── Stream lifecycle ───────────────────────────────────────────────────

# How long (seconds) the stream keeps running after the last keep-alive
STREAM_IDLE_TIMEOUT = 60.0

_stream_lock = threading.Lock()
_stream_active = False          # True while the background thread is looping
_stream_thread: threading.Thread | None = None
_stream_last_keepalive: float = 0.0   # monotonic time of last start/keepalive

# Colours for bounding boxes (BGR for OpenCV)
_COLOR_MOVING = (144, 238, 144)   # light green
_COLOR_WAITING = (128, 128, 255)  # light purple/red (BGR)


# ── Speed calculator ──────────────────────────────────────────────────

class SpeedCalculator:
    """Track per-vehicle positions and compute smoothed speed (m/s)."""

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


# ── Background processing loop ───────────────────────────────────────

def _background_loop():
    """Process the video while the stream is active, skipping frames to stay in real-time.

    Exits cleanly when:
    - ``_stream_active`` is set to False, OR
    - No keepalive has been received for ``STREAM_IDLE_TIMEOUT`` seconds.
    """
    global _stream_active, _video_complete, _vehicle_snapshot
    from ultralytics import YOLO

    logger.info("Stream: loading YOLO model from %s …", MODEL_PATH)
    model = YOLO(str(MODEL_PATH))
    model.verbose = False
    logger.info("Stream: YOLO model loaded.")

    video_path = str(VIDEO_PATH)

    # Load regions once
    if REGIONS_PATH.exists():
        regions = load_regions_from_json(str(REGIONS_PATH))
    else:
        regions = None

    MAX_SKIP_FRAMES = 10  # Never skip more than this many frames at once

    while True:
        # ── Check if we should keep running ───────────────────────────
        with _stream_lock:
            if not _stream_active:
                logger.info("Stream: stop requested — exiting loop.")
                return
            idle_secs = time.monotonic() - _stream_last_keepalive
            if idle_secs > STREAM_IDLE_TIMEOUT:
                logger.info(
                    "Stream: idle for %.0fs (timeout=%.0fs) — auto-stopping.",
                    idle_secs, STREAM_IDLE_TIMEOUT,
                )
                _stream_active = False
                return

        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                logger.error("Stream: cannot open video %s — retrying in 5s", video_path)
                time.sleep(5)
                continue

            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

            fallback_regions = regions if regions is not None else (width, height)

            logger.info(
                "Stream: starting video %s (fps=%.1f, frames=%d)",
                video_path, fps, total_frames,
            )

            speed_calc = SpeedCalculator(fps)
            frame_idx = 0
            start_wall = time.monotonic()

            while cap.isOpened():
                # ── Check stop/idle inside inner loop too ─────────────
                with _stream_lock:
                    if not _stream_active:
                        logger.info("Stream: stop requested mid-video.")
                        cap.release()
                        return
                    idle_secs = time.monotonic() - _stream_last_keepalive
                    if idle_secs > STREAM_IDLE_TIMEOUT:
                        logger.info(
                            "Stream: idle %.0fs — auto-stopping mid-video.", idle_secs
                        )
                        _stream_active = False
                        cap.release()
                        return

                ret, frame = cap.read()
                if not ret:
                    break
                frame_idx += 1

                # ── Real-time sync: compare video time vs wall time ───
                video_time = frame_idx / fps
                wall_elapsed = time.monotonic() - start_wall

                if video_time < wall_elapsed - 0.5:
                    lag_seconds = wall_elapsed - video_time
                    frames_behind = int(lag_seconds * fps)

                    if frames_behind > MAX_SKIP_FRAMES:
                        logger.warning(
                            "Stream: %.1fs behind real-time (%d frames), "
                            "capping skip at %d",
                            lag_seconds, frames_behind, MAX_SKIP_FRAMES,
                        )
                        # Skip up to MAX_SKIP_FRAMES by reading & discarding
                        for _ in range(MAX_SKIP_FRAMES - 1):
                            ret, frame = cap.read()
                            if not ret:
                                break
                            frame_idx += 1
                    else:
                        continue  # Skip this single frame

                # ── Only process every YOLO_VID_STRIDE-th frame ───────
                if frame_idx % YOLO_VID_STRIDE != 0:
                    continue

                # ── YOLO inference on this single frame ───────────────
                results_list = model.track(
                    frame,
                    imgsz=YOLO_IMGSZ,
                    conf=YOLO_CONF,
                    show=False,
                    verbose=False,
                    persist=True,
                    tracker="botsort.yaml",
                )

                if not results_list:
                    continue
                results = results_list[0]
                frame_img = results.orig_img

                box_annotations: list[tuple[int,int,int,int,bool,int]] = []
                frame_waiting: dict[str, int] = defaultdict(int)
                frame_vehicles: list[dict] = []

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

                    region = detect_region(cx, cy, fallback_regions)
                    speed_ms, _ = speed_calc.update(
                        object_id, cx, cy, frame_idx, region,
                    )

                    is_waiting = region is not None and speed_ms < WAITING_SPEED_THRESHOLD
                    if is_waiting:
                        frame_waiting[region] += 1

                    box_annotations.append((x1, y1, x2, y2, is_waiting, object_id))
                    frame_vehicles.append({
                        "id": object_id,
                        "cx": cx,
                        "cy": cy,
                        "speed": speed_ms,
                        "region": region,
                        "is_waiting": is_waiting,
                        "video_width": width,
                        "video_height": height,
                    })

                directions = ["north", "south", "east", "west"]
                counts = {d: frame_waiting.get(d, 0) for d in directions}
                counts["total"] = sum(counts.values())

                try:
                    if frame_img is not None:
                        _, buf_orig = cv2.imencode(
                            ".jpg", frame_img, [cv2.IMWRITE_JPEG_QUALITY, 70],
                        )
                        orig_b64 = base64.b64encode(buf_orig.tobytes()).decode()

                        annotated = frame_img.copy()
                        for (bx1, by1, bx2, by2, bwait, bid) in box_annotations:
                            color = _COLOR_WAITING if bwait else _COLOR_MOVING
                            cv2.rectangle(annotated, (bx1, by1), (bx2, by2), color, 2)
                            label = f"#{bid} {'WAIT' if bwait else 'GO'}"
                            cv2.putText(
                                annotated, label,
                                (bx1, by1 - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
                                cv2.LINE_AA,
                            )
                        _, buf_ann = cv2.imencode(
                            ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 70],
                        )
                        ann_b64 = base64.b64encode(buf_ann.tobytes()).decode()

                        with _snapshot_lock:
                            _snapshot["frame_b64"] = orig_b64
                            _snapshot["frame_annotated_b64"] = ann_b64
                            _snapshot["timestamp"] = video_time
                            _snapshot["north"] = counts["north"]
                            _snapshot["south"] = counts["south"]
                            _snapshot["east"] = counts["east"]
                            _snapshot["west"] = counts["west"]
                            _snapshot["total"] = counts["total"]
                            _vehicle_snapshot = frame_vehicles
                except Exception:
                    pass  # non-critical

            cap.release()

            # Mark video as complete (one full loop)
            with _snapshot_lock:
                global _video_complete
                _video_complete = True

            logger.info("Stream: video ended at frame %d — looping.", frame_idx)

        except Exception:
            logger.exception("Stream: loop error — restarting in 3s")
            time.sleep(3)


# ── Stream lifecycle API ──────────────────────────────────────────────

def start_stream() -> dict:
    """Start (or keep alive) the background video processing thread.

    Safe to call repeatedly — acts as a keepalive heartbeat.
    Returns the current stream status.
    """
    global _stream_active, _stream_thread, _stream_last_keepalive

    with _stream_lock:
        _stream_last_keepalive = time.monotonic()

        if _stream_active and _stream_thread and _stream_thread.is_alive():
            logger.debug("Stream: keepalive received (already running).")
            return {"status": "running"}

        # Start fresh
        _stream_active = True
        _stream_thread = threading.Thread(
            target=_background_loop,
            daemon=True,
            name="video-analyzer",
        )
        _stream_thread.start()
        logger.info("Stream: started on demand.")
        return {"status": "started"}


def stop_stream() -> dict:
    """Signal the background thread to stop after the current frame."""
    global _stream_active

    with _stream_lock:
        if not _stream_active:
            return {"status": "already_stopped"}
        _stream_active = False

    logger.info("Stream: stop requested by caller.")
    return {"status": "stopped"}


def get_stream_status() -> dict:
    """Return whether the video stream is currently active."""
    with _stream_lock:
        active = _stream_active and bool(
            _stream_thread and _stream_thread.is_alive()
        )
        idle_secs = time.monotonic() - _stream_last_keepalive if _stream_last_keepalive else None
    return {
        "active": active,
        "idle_seconds": round(idle_secs, 1) if idle_secs is not None else None,
        "idle_timeout": STREAM_IDLE_TIMEOUT,
    }


# ── Legacy compatibility (used by sync_loop) ──────────────────────────

def start_background_loop() -> None:
    """Start stream — kept for sync_loop.py compatibility."""
    start_stream()


# ── Public API ────────────────────────────────────────────────────────

def get_waiting_count(id_camera: str) -> dict:
    """Return the latest cached waiting vehicle counts (from snapshot).

    Returns zeros if the stream is not running.
    """
    with _snapshot_lock:
        return {
            "id_camera": id_camera,
            "north": _snapshot["north"],
            "south": _snapshot["south"],
            "east": _snapshot["east"],
            "west": _snapshot["west"],
            "total": _snapshot["total"],
        }


def get_latest_frame() -> dict:
    """Return the latest video frames (original + annotated) as base64.

    Returns a dict with 'image' and 'image_annotated' keys.
    Either may be None if the stream is not running or no frame yet.
    """
    with _snapshot_lock:
        return {
            "image": _snapshot["frame_b64"],
            "image_annotated": _snapshot["frame_annotated_b64"],
            "timestamp": _snapshot["timestamp"],
        }


def get_tracked_vehicles() -> list[dict]:
    """Return the latest per-frame tracked vehicle list.

    Each entry: {id, cx, cy, speed, region, is_waiting, video_width, video_height}
    """
    with _snapshot_lock:
        return list(_vehicle_snapshot)


def is_video_complete() -> bool:
    """Return True if the video has completed one full loop."""
    with _snapshot_lock:
        return _video_complete


def reset_video_complete_flag() -> None:
    """Reset the video completion flag (call before starting a new sync run)."""
    global _video_complete
    with _snapshot_lock:
        _video_complete = False


# ── Traffic light state machine ───────────────────────────────────────

# Which axis is currently RED: "ns" (North/South red, East/West green)
#                           or "ew" (East/West red, North/South green)
_light_red_axis: str | None = None   # None = not yet initialised
_light_last_switch: float = 0.0      # time.time() of last state change


def get_traffic_light_state() -> dict:
    """Infer traffic light states from waiting vehicle counts.

    Rules:
      1. Exactly one axis is RED, the other is GREEN (mutual exclusion).
         Axes: NS (North + South) vs EW (East + West).
      2. Observed directions are North and East.  If waiting >= threshold
         → that direction's axis looks "red".
      3. Conflict resolution:
         - Both look red  → the axis with MORE waiting vehicles is red.
         - Both look green → keep the previous state (no change).
      4. After a switch, the state is locked for MIN_LIGHT_DURATION_SECS
         seconds.  During the cooldown the current state is returned
         without re-evaluation.

    Returns::

        {
            "north":  {"state": "red"|"green", "duration": -1},
            "south":  {"state": "red"|"green", "duration": -1},
            "east":   {"state": "red"|"green", "duration": -1},
            "west":   {"state": "red"|"green", "duration": -1},
        }
    """
    from service.config import WAITING_VEHICLE_RED_THRESHOLD, MIN_LIGHT_DURATION_SECS

    global _light_red_axis, _light_last_switch

    now = time.time()

    with _snapshot_lock:
        north_waiting = _snapshot["north"]
        east_waiting = _snapshot["east"]

    # ── First call: initialise based on current observations ──────────
    if _light_red_axis is None:
        ns_looks_red = north_waiting >= WAITING_VEHICLE_RED_THRESHOLD
        ew_looks_red = east_waiting >= WAITING_VEHICLE_RED_THRESHOLD

        if ns_looks_red and ew_looks_red:
            _light_red_axis = "ns" if north_waiting >= east_waiting else "ew"
        elif ns_looks_red:
            _light_red_axis = "ns"
        elif ew_looks_red:
            _light_red_axis = "ew"
        else:
            _light_red_axis = "ns"  # default: NS red, EW green

        _light_last_switch = now

    # ── Cooldown: skip re-evaluation if less than MIN_LIGHT_DURATION ──
    elif now - _light_last_switch >= MIN_LIGHT_DURATION_SECS:
        ns_looks_red = north_waiting >= WAITING_VEHICLE_RED_THRESHOLD
        ew_looks_red = east_waiting >= WAITING_VEHICLE_RED_THRESHOLD

        new_axis = _light_red_axis  # default: keep current

        if ns_looks_red and not ew_looks_red:
            new_axis = "ns"
        elif ew_looks_red and not ns_looks_red:
            new_axis = "ew"
        elif ns_looks_red and ew_looks_red:
            new_axis = "ns" if north_waiting >= east_waiting else "ew"
        # else: both green → keep previous state

        if new_axis != _light_red_axis:
            _light_red_axis = new_axis
            _light_last_switch = now

    # ── Build response from current axis state ────────────────────────
    ns_state = "red" if _light_red_axis == "ns" else "green"
    ew_state = "red" if _light_red_axis == "ew" else "green"

    return {
        "north": {"state": ns_state, "duration": -1},
        "south": {"state": ns_state, "duration": -1},
        "east":  {"state": ew_state, "duration": -1},
        "west":  {"state": ew_state, "duration": -1},
    }
