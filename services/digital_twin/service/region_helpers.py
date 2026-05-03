"""Region detection helpers.

Tries to import ``detect_region`` and ``load_regions_from_json`` from
a ``script_stream.py`` file sitting next to ``regions.json`` in the
service root.  Falls back to quadrant-based detection if unavailable.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import cv2
import numpy as np

from service.config import BASE_DIR

logger = logging.getLogger(__name__)

_helpers_loaded = False

# Try to import from script_stream.py in the service root
_script_stream_path = BASE_DIR
try:
    if str(_script_stream_path) not in sys.path:
        sys.path.insert(0, str(_script_stream_path))
    from script_stream import detect_region as _detect_region  # type: ignore
    from script_stream import load_regions_from_json as _load_regions  # type: ignore
    _helpers_loaded = True
    logger.info("Loaded region helpers from script_stream.py")
except ImportError:
    logger.warning("script_stream.py not found — using built-in region helpers")


def load_regions_from_json(json_path: str | Path) -> dict | None:
    """Load region polygons from a JSON file."""
    if _helpers_loaded:
        return _load_regions(str(json_path))

    path = Path(json_path)
    if not path.exists():
        logger.warning("Regions file not found: %s", path)
        return None

    try:
        with open(path) as f:
            raw = json.load(f)

        regions: dict = {}
        for name, data in raw.items():
            regions[name] = {
                "points": [tuple(p) for p in data["points"]],
                "color": tuple(data["color"]),
            }
        logger.info("Loaded %d regions from %s", len(regions), path)
        return regions
    except Exception as exc:
        logger.error("Error loading regions: %s", exc)
        return None


def detect_region(cx: float, cy: float, regions) -> str | None:
    """Detect which named region a point falls in.

    If *regions* is a dict of polygons (from ``regions.json``), uses
    OpenCV ``pointPolygonTest``.  If *regions* is a ``(width, height)``
    tuple (fallback), uses quadrant logic.
    """
    if _helpers_loaded:
        return _detect_region(cx, cy, regions)

    if regions is None:
        return None

    # Fallback: (width, height) tuple → quadrant
    if isinstance(regions, tuple):
        w, h = regions
        if cy < h / 2:
            return "north" if cx >= w / 2 else "west"
        else:
            return "east" if cx >= w / 2 else "south"

    # Dict of polygon regions
    for name, data in regions.items():
        pts = np.array(data["points"], dtype=np.int32)
        if cv2.pointPolygonTest(pts, (cx, cy), False) >= 0:
            return name

    return None
