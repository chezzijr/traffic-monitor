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

import numpy as np
import torch
import cv2

from service.config import (
    MODEL_PATH,
    METERS_PER_PIXEL,
    TRACKED_CLASS_IDS,
    VIDEO_PATH,
    WAITING_SPEED_THRESHOLD,
    WAITING_MIN_FRAMES,
    WAITING_SPEED_THRESHOLD_NORTH,
    YOLO_IMGSZ,
    YOLO_CONF,
    YOLO_VID_STRIDE,
    REGIONS_PATH,
    TRACKER_CONFIG,
)
from service.region_helpers import detect_region, load_regions_from_json

logger = logging.getLogger(__name__)


def _format_hms_label(total_seconds: float) -> str:
    seconds = max(0, int(total_seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}h{minutes:02d}m{secs:02d}s"


def _build_time_label(video_time: float) -> str:
    return f"12h00m00s + {_format_hms_label(video_time)}"


def _draw_time_label(frame, text: str) -> None:
    cv2.putText(
        frame,
        text,
        (12, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 0, 0),
        3,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        text,
        (12, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )


def _run_track(model, frame, device: str):
    return model.track(
        frame,
        imgsz=YOLO_IMGSZ,
        conf=YOLO_CONF,
        show=False,
        verbose=False,
        persist=True,
        tracker=str(TRACKER_CONFIG),
        half=(device == "cuda"),
        device=device,
    )



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

# Waiting-count time-series: list of (video_time_sec, north, south, east, west)
_waiting_history: list[tuple[float, int, int, int, int]] = []

# ── Stream lifecycle ───────────────────────────────────────────────────

# How long (seconds) the stream keeps running after the last keep-alive
STREAM_IDLE_TIMEOUT = 60.0

_stream_lock = threading.Lock()
_stream_active = False          # True while the background thread is looping
_stream_thread: threading.Thread | None = None
_stream_last_keepalive: float = 0.0   # monotonic time of last start/keepalive
_stream_error_msg: str | None = None  # Last fatal error surfaced from background loop

# Colours for bounding boxes (BGR for OpenCV)
_COLOR_MOVING = (144, 238, 144)   # light green
_COLOR_WAITING = (128, 128, 255)  # light purple/red (BGR)

# ── Debug mode ────────────────────────────────────────────────────────
_debug_mode = False


def set_debug_mode(enabled: bool) -> None:
    global _debug_mode
    _debug_mode = enabled


def get_debug_mode() -> bool:
    return _debug_mode


def _draw_region_overlays(frame, regions) -> None:
    """Draw semi-transparent filled polygons + outlines for each direction region."""
    if not isinstance(regions, dict):
        return

    overlay = frame.copy()
    for name, data in regions.items():
        pts = np.array(data["points"], dtype=np.int32).reshape((-1, 1, 2))
        color_rgb = data.get("color", [255, 255, 255])
        # regions.json stores RGB; OpenCV needs BGR
        color_bgr = (int(color_rgb[2]), int(color_rgb[1]), int(color_rgb[0]))

        cv2.fillPoly(overlay, [pts], color_bgr)

    cv2.addWeighted(overlay, 0.25, frame, 0.75, 0, frame)

    for name, data in regions.items():
        pts = np.array(data["points"], dtype=np.int32).reshape((-1, 1, 2))
        color_rgb = data.get("color", [255, 255, 255])
        color_bgr = (int(color_rgb[2]), int(color_rgb[1]), int(color_rgb[0]))

        cv2.polylines(frame, [pts], isClosed=True, color=color_bgr, thickness=2)

        # Label at centroid
        cx = int(np.mean([p[0] for p in data["points"]]))
        cy = int(np.mean([p[1] for p in data["points"]]))
        cv2.putText(frame, name.upper(), (cx - 20, cy),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(frame, name.upper(), (cx - 20, cy),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, color_bgr, 2, cv2.LINE_AA)


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
                "low_speed_frames": 0,
                "seen_frames": 1,
            }
            return 0.0, region, 0

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

        track["seen_frames"] += 1
        if track["speed_ms"] < WAITING_SPEED_THRESHOLD:
            track["low_speed_frames"] += 1
        else:
            track["low_speed_frames"] = 0

        track["last_frame"] = frame_count
        track["last_cx"] = cx
        track["last_cy"] = cy
        return track["speed_ms"], track["entry_region"], track["low_speed_frames"]


class LatestFrameBuffer:
    """Read video frames in a background thread and keep only the latest.

    The reader paces itself to the video FPS, so it doesn't run ahead of
    real-time. The main loop always consumes the newest frame available.
    """

    def __init__(self, video_path: str):
        global _stream_error_msg
        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
            from pathlib import Path as _P
            exists = _P(video_path).exists()
            if not exists:
                msg = f"video_missing: file not found at {video_path}. Run `git lfs pull`."
            else:
                msg = f"video_unreadable: cv2.VideoCapture failed for {video_path}. Check codec/permissions or LFS pointer."
            with _stream_lock:
                _stream_error_msg = msg
            raise RuntimeError(msg)

        # Disable WMF auto-rotation on Windows so we can apply it ourselves
        # consistently across platforms (FFmpeg/Linux never auto-rotates).
        self.cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 0)
        self._rotation = int(self.cap.get(cv2.CAP_PROP_ORIENTATION_META))

        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

        self._lock = threading.Lock()
        self._latest: tuple[int, any] | None = None
        self._frame_idx = 0
        self._seek_to: int | None = None
        self._eof = False
        self._start_wall: float | None = None
        self._stop_event = threading.Event()

        self._thread = threading.Thread(
            target=self._reader_loop,
            daemon=True,
            name="video-reader",
        )
        self._thread.start()

    def _reader_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                seek_to = self._seek_to
                if seek_to is not None:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, seek_to)
                    self._frame_idx = seek_to
                    self._seek_to = None
                    self._start_wall = time.monotonic()

            ret, frame = self.cap.read()
            if not ret:
                with self._lock:
                    self._eof = True
                break

            if self._rotation == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            elif self._rotation == 90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            elif self._rotation == 270:
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

            with self._lock:
                self._frame_idx += 1
                self._latest = (self._frame_idx, frame)
                if self._start_wall is None:
                    self._start_wall = time.monotonic()
                start_wall = self._start_wall
                frame_idx = self._frame_idx

            if start_wall is not None:
                target_delay = (frame_idx / self.fps) - (time.monotonic() - start_wall)
                if target_delay > 0:
                    time.sleep(min(target_delay, 0.5))

    def get_latest(self) -> tuple[tuple[int, any] | None, bool]:
        with self._lock:
            return self._latest, self._eof

    def seek(self, target_frame: int) -> None:
        with self._lock:
            self._seek_to = max(0, target_frame)

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=3.0)
        self.cap.release()


# ── Background processing loop ───────────────────────────────────────

def _background_loop():
    """Process the video while the stream is active, skipping frames to stay in real-time.

    Exits cleanly when:
    - ``_stream_active`` is set to False, OR
    - No keepalive has been received for ``STREAM_IDLE_TIMEOUT`` seconds.
    """
    global _stream_active, _video_complete, _vehicle_snapshot
    from ultralytics import YOLO

    logger.info("Stream: loading YOLO model from %s (imgsz=%s) …", MODEL_PATH, YOLO_IMGSZ)
    model = YOLO(str(MODEL_PATH))
    model.verbose = False
    
    # Use GPU if available
    device = "cuda" if torch.cuda.is_available() else "cpu"
    # Note: .to(device) is only for .pt models. For .engine, we pass device to track()
    if str(MODEL_PATH).endswith(".pt"):
        model.to(device)
    
    logger.info("Stream: YOLO model loaded on %s.", device)
    logger.info(
        "Stream: config model=%s tracker=%s imgsz=%s conf=%s stride=%s",
        MODEL_PATH,
        TRACKER_CONFIG,
        YOLO_IMGSZ,
        YOLO_CONF,
        YOLO_VID_STRIDE,
    )
    logger.info("Stream: detection mode=track (forced)")

    video_path = str(VIDEO_PATH)

    # Load regions once
    if REGIONS_PATH.exists():
        regions = load_regions_from_json(str(REGIONS_PATH))
    else:
        regions = None

    MAX_SKIP_FRAMES = 300  # Skip up to 10 seconds (at 30fps) to catch up
    LAG_JUMP_THRESHOLD_FRAMES = 5  # If lag exceeds this, jump to wall time

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

        buffer = None
        try:
            buffer = LatestFrameBuffer(video_path)

            width = buffer.width
            height = buffer.height
            fps = buffer.fps
            total_frames = buffer.total_frames

            fallback_regions = regions if regions is not None else (width, height)

            logger.info(
                "Stream: starting video %s (fps=%.1f, frames=%d)",
                video_path, fps, total_frames,
            )

            speed_calc = SpeedCalculator(fps)
            frame_idx = 0
            last_seen_frame = 0
            start_wall = None
            warmup_remaining = 5
            seek_target: int | None = None

            while True:
                # ── Check stop/idle inside inner loop too ─────────────
                with _stream_lock:
                    if not _stream_active:
                        logger.info("Stream: stop requested mid-video.")
                        if buffer is not None:
                            buffer.stop()
                        return
                    idle_secs = time.monotonic() - _stream_last_keepalive
                    if idle_secs > STREAM_IDLE_TIMEOUT:
                        logger.info(
                            "Stream: idle %.0fs — auto-stopping mid-video.", idle_secs
                        )
                        _stream_active = False
                        if buffer is not None:
                            buffer.stop()
                        return

                latest, eof = buffer.get_latest()
                if latest is None:
                    if eof:
                        break
                    time.sleep(0.01)
                    continue

                frame_idx, frame = latest
                if frame_idx == last_seen_frame:
                    time.sleep(0.005)
                    continue

                last_seen_frame = frame_idx

                if seek_target is not None:
                    if frame_idx < seek_target:
                        time.sleep(0.005)
                        continue
                    seek_target = None

                if start_wall is None:
                    start_wall = time.monotonic()

                # ── Real-time sync: compare video time vs wall time ───
                video_time = frame_idx / fps
                wall_elapsed = time.monotonic() - start_wall

                if warmup_remaining > 0:
                    warmup_remaining -= 1
                    do_force_inference = True
                elif video_time < wall_elapsed - 0.2:
                    lag_seconds = wall_elapsed - video_time
                    frames_behind = int(lag_seconds * fps)

                    if frames_behind >= LAG_JUMP_THRESHOLD_FRAMES:
                        target_frame = int(wall_elapsed * fps)
                        if target_frame > frame_idx:
                            logger.warning(
                                "Stream: %.1fs behind (%d frames) — jumping to frame %d.",
                                lag_seconds, frames_behind, target_frame,
                            )
                            buffer.seek(target_frame)
                            seek_target = target_frame
                            continue
                        do_force_inference = True
                    elif frames_behind > 0:
                        # Skip up to MAX_SKIP_FRAMES using grab() (faster than read())
                        to_skip = min(frames_behind, MAX_SKIP_FRAMES)
                        logger.warning(
                            "Stream: %.1fs behind real-time (%d frames) — skipping %d to catch up.",
                            lag_seconds, frames_behind, to_skip
                        )
                        target_frame = frame_idx + to_skip
                        buffer.seek(target_frame)
                        seek_target = target_frame
                        continue
                    else:
                        do_force_inference = False
                else:
                    do_force_inference = False

                # ── Only process every YOLO_VID_STRIDE-th frame ───────
                if frame_idx % YOLO_VID_STRIDE != 0 and not do_force_inference:
                    continue
                
                # ── YOLO inference on this single frame ───────────────
                results_list = _run_track(model, frame, device)

                if not results_list:
                    logger.warning("Stream: YOLO returned no results for frame %d", frame_idx)
                    continue
                results = results_list[0]
                
                num_detected = len(results.boxes) if results.boxes is not None else 0
                num_tracked = 0
                logger.info(
                    "Stream: frame %d processed (lag=%.2fs, mode=track, detections=%d)",
                    frame_idx,
                    time.monotonic() - start_wall - video_time,
                    num_detected,
                )
                frame_img = results.orig_img

                box_annotations: list[tuple[int,int,int,int,bool,int,str]] = []
                frame_waiting: dict[str, int] = defaultdict(int)
                frame_vehicles: list[dict] = []

                for box in results.boxes:
                    if box.cls is None or len(box.cls) == 0:
                        continue
                    cls = int(box.cls[0])
                    cls_name = model.names.get(cls, f"cls{cls}")

                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                    region = detect_region(cx, cy, fallback_regions)

                    # Tracking ID is needed for speed / waiting state
                    object_id = None
                    if box.id is not None:
                        try:
                            object_id = int(box.id[0])
                        except (IndexError, TypeError):
                            pass

                    is_waiting = False
                    speed_ms = 0.0

                    if object_id is not None and cls in TRACKED_CLASS_IDS:
                        speed_ms, _, low_speed_frames = speed_calc.update(
                            object_id, cx, cy, frame_idx, region
                        )
                        speed_threshold = WAITING_SPEED_THRESHOLD
                        if region == "north":
                            speed_threshold = WAITING_SPEED_THRESHOLD_NORTH
                        is_waiting = (
                            region is not None
                            and speed_ms < speed_threshold
                            and low_speed_frames >= WAITING_MIN_FRAMES
                        )
                        if is_waiting:
                            frame_waiting[region] += 1
                        num_tracked += 1
                    
                    # Only annotate vehicle classes to avoid rider/person duplicates.
                    if cls in TRACKED_CLASS_IDS:
                        box_annotations.append(
                            (x1, y1, x2, y2, is_waiting, object_id if object_id is not None else -1, cls_name)
                        )
                    
                    if object_id is not None and cls in TRACKED_CLASS_IDS:
                        frame_vehicles.append({
                            "id": object_id, "cx": cx, "cy": cy, "speed": speed_ms,
                            "region": region, "is_waiting": is_waiting,
                            "video_width": width, "video_height": height,
                        })

                if num_detected > 0:
                    logger.info(
                        "Stream: frame %d tracked=%d total=%d",
                        frame_idx,
                        num_tracked,
                        num_detected,
                    )

                directions = ["north", "south", "east", "west"]
                counts = {d: frame_waiting.get(d, 0) for d in directions}
                counts["total"] = sum(counts.values())

                try:
                    if frame_img is not None:
                        time_label = _build_time_label(video_time)
                        frame_with_time = frame_img.copy()
                        _draw_time_label(frame_with_time, time_label)
                        _, buf_orig = cv2.imencode(
                            ".jpg", frame_with_time, [cv2.IMWRITE_JPEG_QUALITY, 70],
                        )
                        orig_b64 = base64.b64encode(buf_orig.tobytes()).decode()

                        annotated = frame_img.copy()
                        if _debug_mode:
                            _draw_region_overlays(annotated, fallback_regions)
                        for (bx1, by1, bx2, by2, bwait, bid, cls_name) in box_annotations:
                            color = _COLOR_WAITING if bwait else _COLOR_MOVING
                            cv2.rectangle(annotated, (bx1, by1), (bx2, by2), color, 2)
                            label = f"{cls_name} #{bid} {'WAIT' if bwait else 'GO'}"
                            cv2.putText(
                                annotated, label,
                                (bx1, by1 - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
                                cv2.LINE_AA,
                            )
                        _draw_time_label(annotated, time_label)
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
                            _waiting_history.append((
                                video_time,
                                counts["north"],
                                counts["south"],
                                counts["east"],
                                counts["west"],
                            ))
                except Exception:
                    pass  # non-critical

            if buffer is not None:
                buffer.stop()

            # Mark video as complete (one full loop)
            with _snapshot_lock:
                global _video_complete
                _video_complete = True

            logger.info("Stream: video ended at frame %d — looping.", frame_idx)

        except Exception as exc:
            global _stream_error_msg
            with _stream_lock:
                _stream_error_msg = f"stream_loop_error: {exc}"
            logger.exception("Stream: loop error — restarting in 3s")
            time.sleep(3)
        finally:
            if buffer is not None:
                buffer.stop()


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
        error_msg = _stream_error_msg
    return {
        "active": active,
        "idle_seconds": round(idle_secs, 1) if idle_secs is not None else None,
        "idle_timeout": STREAM_IDLE_TIMEOUT,
        "error_msg": error_msg,
    }


def get_stream_error() -> str | None:
    """Return the last fatal error from the background video loop, if any."""
    with _stream_lock:
        return _stream_error_msg


def clear_stream_error() -> None:
    """Clear the surfaced error. Called when a fresh stream is restarted."""
    global _stream_error_msg
    with _stream_lock:
        _stream_error_msg = None


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


def get_waiting_history() -> list[tuple[float, int, int, int, int]]:
    """Return a copy of the accumulated waiting-count time-series.

    Each entry is ``(video_time_sec, north, south, east, west)``.
    """
    with _snapshot_lock:
        return list(_waiting_history)


def reset_waiting_history() -> None:
    """Clear the accumulated waiting-count history."""
    global _waiting_history
    with _snapshot_lock:
        _waiting_history = []


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
