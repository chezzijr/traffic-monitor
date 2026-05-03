"""Map video pixel coordinates to SUMO network edges and positions.

Uses the region polygons (from regions.json) to determine which
direction a vehicle is coming from, then maps to the corresponding
SUMO incoming edge and estimates position along that edge.

Direction detection is based on region transitions over time:
  - same region throughout → straight
  - region change → turning (left/right depends on the pair)
"""

from __future__ import annotations

import logging
from collections import defaultdict

from service.network_gen import (
    EDGE_NORTH_IN,
    EDGE_SOUTH_IN,
    EDGE_EAST_IN,
    EDGE_WEST_IN,
    EDGE_NORTH_OUT,
    EDGE_SOUTH_OUT,
    EDGE_EAST_OUT,
    EDGE_WEST_OUT,
)

logger = logging.getLogger(__name__)

# ── Direction → incoming SUMO edge ───────────────────────────────────

DIRECTION_TO_INCOMING_EDGE: dict[str, str] = {
    "north": EDGE_NORTH_IN,
    "south": EDGE_SOUTH_IN,
    "east":  EDGE_EAST_IN,
    "west":  EDGE_WEST_IN,
}

# ── Straight-through routes (entry → exit) ───────────────────────────
# "Straight" means the opposite side.

STRAIGHT_ROUTES: dict[str, list[str]] = {
    "north": [EDGE_NORTH_IN, EDGE_SOUTH_OUT],
    "south": [EDGE_SOUTH_IN, EDGE_NORTH_OUT],
    "east":  [EDGE_EAST_IN, EDGE_WEST_OUT],
    "west":  [EDGE_WEST_IN, EDGE_EAST_OUT],
}

# ── Turn routes: (entry_direction, exit_direction) → edge list ───────
# From perspective of a vehicle entering from `entry_direction`,
# turning to exit via `exit_direction`.

_TURN_ROUTES: dict[tuple[str, str], list[str]] = {
    # From north
    ("north", "east"):  [EDGE_NORTH_IN, EDGE_EAST_OUT],   # right turn
    ("north", "west"):  [EDGE_NORTH_IN, EDGE_WEST_OUT],   # left turn
    ("north", "south"): [EDGE_NORTH_IN, EDGE_SOUTH_OUT],  # straight
    # From south
    ("south", "west"):  [EDGE_SOUTH_IN, EDGE_WEST_OUT],   # right turn
    ("south", "east"):  [EDGE_SOUTH_IN, EDGE_EAST_OUT],   # left turn
    ("south", "north"): [EDGE_SOUTH_IN, EDGE_NORTH_OUT],  # straight
    # From east
    ("east", "south"):  [EDGE_EAST_IN, EDGE_SOUTH_OUT],   # right turn
    ("east", "north"):  [EDGE_EAST_IN, EDGE_NORTH_OUT],   # left turn
    ("east", "west"):   [EDGE_EAST_IN, EDGE_WEST_OUT],    # straight
    # From west
    ("west", "north"):  [EDGE_WEST_IN, EDGE_NORTH_OUT],   # right turn
    ("west", "south"):  [EDGE_WEST_IN, EDGE_SOUTH_OUT],   # left turn
    ("west", "east"):   [EDGE_WEST_IN, EDGE_EAST_OUT],    # straight
}


class DirectionTracker:
    """Track region history per vehicle to detect turning direction."""

    def __init__(self, confirm_frames: int = 5):
        self.confirm_frames = confirm_frames
        # vehicle_id → list of recent regions
        self._history: dict[int, list[str]] = defaultdict(list)
        # vehicle_id → confirmed entry direction
        self._entry_direction: dict[int, str] = {}
        # vehicle_id → confirmed exit direction (None = not yet confirmed)
        self._exit_direction: dict[int, str | None] = {}

    def update(self, vehicle_id: int, region: str | None) -> None:
        """Record a region observation for a vehicle."""
        if region is None:
            return

        history = self._history[vehicle_id]
        history.append(region)

        # Set entry direction from first observation
        if vehicle_id not in self._entry_direction:
            self._entry_direction[vehicle_id] = region

        # Check for direction change (entered new region consistently)
        entry = self._entry_direction[vehicle_id]
        if region != entry:
            # Count how many recent frames are in the new region
            recent = history[-self.confirm_frames:]
            if len(recent) >= self.confirm_frames and all(r == region for r in recent):
                self._exit_direction[vehicle_id] = region

    def get_entry_direction(self, vehicle_id: int) -> str | None:
        """Return the confirmed entry direction."""
        return self._entry_direction.get(vehicle_id)

    def get_route(self, vehicle_id: int) -> list[str] | None:
        """Return the route for a vehicle.

        Returns the confirmed turn route if direction change detected,
        otherwise the default straight route.
        """
        entry = self._entry_direction.get(vehicle_id)
        if entry is None:
            return None

        exit_dir = self._exit_direction.get(vehicle_id)
        if exit_dir is not None:
            route = _TURN_ROUTES.get((entry, exit_dir))
            if route:
                return route

        # Default: straight through
        return STRAIGHT_ROUTES.get(entry)

    def is_route_updated(self, vehicle_id: int) -> bool:
        """Return True if the vehicle's route has been corrected from default."""
        return vehicle_id in self._exit_direction

    def remove(self, vehicle_id: int) -> None:
        """Clean up tracking data for a vehicle that left."""
        self._history.pop(vehicle_id, None)
        self._entry_direction.pop(vehicle_id, None)
        self._exit_direction.pop(vehicle_id, None)


def get_incoming_edge(direction: str) -> str | None:
    """Map a direction name to the corresponding incoming SUMO edge ID."""
    return DIRECTION_TO_INCOMING_EDGE.get(direction)


