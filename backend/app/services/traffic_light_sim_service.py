"""Mockup traffic light simulation service.

Simulates real-time traffic light cycles per intersection purely from
wall-clock time — no background threads required. Each intersection
lazily initialises a simulation on first request.

Rules:
  - Two phase groups: NS (North/South) and WE (West/East).
  - One group is green while the other is red (opposite states).
  - Default cycle per group: Green 30s → Yellow 3s → Red 33s.
  - Full cycle length = (green + yellow) * 2 = 66s.
"""

from dataclasses import dataclass, field
import time
from typing import Literal

PhaseColour = Literal["red", "yellow", "green"]


@dataclass
class PhaseConfig:
    green_duration: int = 30
    yellow_duration: int = 3

    @property
    def half_cycle(self) -> int:
        """Duration of one group's green+yellow phase."""
        return self.green_duration + self.yellow_duration

    @property
    def full_cycle(self) -> int:
        """Duration of a complete NS+WE cycle."""
        return self.half_cycle * 2


@dataclass
class SimState:
    intersection_id: str
    started_at: float = field(default_factory=time.time)
    phase_config: PhaseConfig = field(default_factory=PhaseConfig)


def _compute_phase(offset_in_half: int, cfg: PhaseConfig) -> tuple[PhaseColour, int]:
    """Return (colour, remaining_seconds) for the *active* group given
    an offset within its half-cycle."""
    if offset_in_half < cfg.green_duration:
        return "green", cfg.green_duration - offset_in_half
    else:
        return "yellow", cfg.half_cycle - offset_in_half


def _opposite_colour(colour: PhaseColour) -> PhaseColour:
    """The colour the opposing group shows."""
    if colour == "green":
        return "red"
    if colour == "yellow":
        return "red"
    return "green"      # should not happen mid-logic, but safe default


# ---------------------------------------------------------------------------
# In-memory store — lazily populated per intersection
# ---------------------------------------------------------------------------
_simulations: dict[str, SimState] = {}


def get_or_create_sim(intersection_id: str) -> SimState:
    if intersection_id not in _simulations:
        _simulations[intersection_id] = SimState(intersection_id=intersection_id)
    return _simulations[intersection_id]


def get_state(intersection_id: str) -> dict:
    """Return the current traffic-light state for *intersection_id*."""
    sim = get_or_create_sim(intersection_id)
    cfg = sim.phase_config

    elapsed = time.time() - sim.started_at
    cycle_pos = int(elapsed) % cfg.full_cycle          # position in the 66-s cycle

    # First half-cycle: NS is active (green/yellow), WE is red.
    # Second half-cycle: WE is active, NS is red.
    if cycle_pos < cfg.half_cycle:
        # NS active
        ns_colour, ns_remaining = _compute_phase(cycle_pos, cfg)
        we_colour = "red"
        we_remaining = cfg.half_cycle - cycle_pos       # time until WE gets green
    else:
        # WE active
        offset = cycle_pos - cfg.half_cycle
        we_colour, we_remaining = _compute_phase(offset, cfg)
        ns_colour = "red"
        ns_remaining = cfg.full_cycle - cycle_pos       # time until NS gets green again

    return {
        "intersection_id": intersection_id,
        "directions": {
            "north":  {"state": ns_colour, "remaining": ns_remaining},
            "south":  {"state": ns_colour, "remaining": ns_remaining},
            "east":   {"state": we_colour, "remaining": we_remaining},
            "west":   {"state": we_colour, "remaining": we_remaining},
        },
        "cycle_duration": cfg.full_cycle,
    }
