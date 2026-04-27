"""TraCI manager for the Digital Twin SUMO sync pipeline.

Manages an independent SUMO instance (separate from the backend's
``sumo_service``) with vehicle lifecycle control: add, update, reroute,
remove.  Vehicles are injected dynamically — no route file needed.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from service.config import SUMO_HOME, SUMO_GUI
from service.network_gen import CENTER_JUNCTION

logger = logging.getLogger(__name__)

# ── TraCI import ──────────────────────────────────────────────────────

_sumo_tools = os.path.join(SUMO_HOME, "tools")
if os.path.isdir(_sumo_tools) and _sumo_tools not in sys.path:
    sys.path.insert(0, _sumo_tools)

try:
    import traci  # type: ignore
    from traci.exceptions import TraCIException  # type: ignore
    TRACI_AVAILABLE = True
except ImportError:
    traci = None  # type: ignore
    TraCIException = Exception
    TRACI_AVAILABLE = False
    logger.warning("traci not available — SUMO sync disabled")

class SumoManager:
    """Manages a single headless SUMO instance for the sync pipeline.

    Each instance uses a unique TraCI connection label so multiple
    SUMO processes can run in parallel (e.g. RL + baseline).
    """

    def __init__(self, label: str = "digital_twin_sync") -> None:
        self._label = label
        self._running = False
        self._step_count = 0
        self._defined_routes: set[str] = set()

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self, network_path: str | Path) -> None:
        """Start SUMO with the given network (no route file)."""
        if not TRACI_AVAILABLE:
            raise RuntimeError("traci is not available")
        if self._running:
            self.stop()

        binary = "sumo-gui" if SUMO_GUI else "sumo"
        sumo_bin = os.path.join(SUMO_HOME, "bin", binary)

        cmd = [
            sumo_bin,
            "-n", str(network_path),
            "--no-step-log", "true",
            "--no-warnings", "true",
            "--step-length", "1",
            "--time-to-teleport", "-1",  # disable teleporting
        ]

        logger.info("Starting SUMO [%s]: %s", self._label, " ".join(cmd))
        traci.start(cmd, label=self._label)
        self._running = True
        self._step_count = 0
        self._defined_routes.clear()
        logger.info("SUMO [%s] started", self._label)

    def stop(self) -> None:
        """Close the SUMO connection."""
        if self._running:
            try:
                conn = traci.getConnection(self._label)
                conn.close()
            except Exception:
                pass
            self._running = False
            self._defined_routes.clear()
            logger.info("SUMO [%s] stopped (step %d)", self._label, self._step_count)

    def step(self) -> dict:
        """Advance simulation by one step. Returns basic metrics."""
        conn = self._conn()
        conn.simulationStep()
        self._step_count += 1

        veh_ids = conn.vehicle.getIDList()
        total_wait = sum(conn.vehicle.getWaitingTime(v) for v in veh_ids)
        total_speed = sum(conn.vehicle.getSpeed(v) for v in veh_ids)
        n = len(veh_ids)

        return {
            "step": self._step_count,
            "num_vehicles": n,
            "total_waiting_time": total_wait,
            "avg_waiting_time": total_wait / n if n else 0.0,
            "avg_speed": total_speed / n if n else 0.0,
            "arrived": conn.simulation.getArrivedNumber(),
        }

    @property
    def running(self) -> bool:
        return self._running

    @property
    def step_count(self) -> int:
        return self._step_count

    # ── Vehicle management ────────────────────────────────────────────

    def add_vehicle(
        self,
        veh_id: str,
        route_edges: list[str],
        lane_index: int = 0,
        pos: float = 0.1,
        speed: float = 0.0,
    ) -> bool:
        """Add a vehicle to the simulation. Returns True on success."""
        conn = self._conn()

        # Ensure a route exists for this edge sequence
        route_id = "_".join(route_edges)
        if route_id not in self._defined_routes:
            try:
                conn.route.add(route_id, route_edges)
                self._defined_routes.add(route_id)
            except TraCIException:
                # Route may already exist from a previous run
                self._defined_routes.add(route_id)

        try:
            conn.vehicle.add(
                veh_id,
                routeID=route_id,
                departLane=str(lane_index),
                departPos=str(pos),
                departSpeed=str(speed),
            )
            return True
        except TraCIException as exc:
            logger.debug("Failed to add vehicle %s: %s", veh_id, exc)
            return False

    def update_vehicle_speed(self, veh_id: str, speed: float) -> None:
        """Set a vehicle's speed (-1 to release to SUMO control)."""
        conn = self._conn()
        try:
            conn.vehicle.setSpeed(veh_id, speed)
        except TraCIException:
            pass  # vehicle may have left

    def reroute_vehicle(self, veh_id: str, new_route_edges: list[str]) -> bool:
        """Change a vehicle's route. Returns True on success."""
        conn = self._conn()

        # Ensure route is defined
        route_id = "_".join(new_route_edges)
        if route_id not in self._defined_routes:
            try:
                conn.route.add(route_id, new_route_edges)
                self._defined_routes.add(route_id)
            except TraCIException:
                self._defined_routes.add(route_id)

        try:
            conn.vehicle.setRoute(veh_id, new_route_edges)
            return True
        except TraCIException as exc:
            logger.debug("Failed to reroute %s: %s", veh_id, exc)
            return False

    def remove_vehicle(self, veh_id: str) -> None:
        """Remove a vehicle from the simulation."""
        conn = self._conn()
        try:
            conn.vehicle.remove(veh_id)
        except TraCIException:
            pass

    def get_vehicle_ids(self) -> list[str]:
        """Return IDs of all vehicles currently in the simulation."""
        conn = self._conn()
        return list(conn.vehicle.getIDList())

    def get_vehicles(self) -> list[dict]:
        """Return detailed state of all vehicles."""
        conn = self._conn()
        result = []
        for vid in conn.vehicle.getIDList():
            pos = conn.vehicle.getPosition(vid)
            result.append({
                "id": vid,
                "x": pos[0],
                "y": pos[1],
                "speed": conn.vehicle.getSpeed(vid),
                "waiting_time": conn.vehicle.getWaitingTime(vid),
                "lane": conn.vehicle.getLaneID(vid),
                "route": list(conn.vehicle.getRoute(vid)),
            })
        return result

    # ── Traffic light control ─────────────────────────────────────────

    def get_tl_id(self) -> str:
        """Return the traffic light ID (assumes single junction)."""
        conn = self._conn()
        tls = conn.trafficlight.getIDList()
        if not tls:
            raise RuntimeError("No traffic lights in the network")
        return tls[0]

    def get_traffic_light_state(self) -> dict:
        """Query current TL state."""
        conn = self._conn()
        tl_id = self.get_tl_id()
        return {
            "tl_id": tl_id,
            "phase": conn.trafficlight.getPhase(tl_id),
            "state": conn.trafficlight.getRedYellowGreenState(tl_id),
            "program": conn.trafficlight.getProgram(tl_id),
        }

    def set_traffic_light_phase(self, phase_index: int) -> None:
        """Set the traffic light to a specific phase."""
        conn = self._conn()
        tl_id = self.get_tl_id()
        conn.trafficlight.setPhase(tl_id, phase_index)

    def get_controlled_lanes(self) -> list[str]:
        """Return the list of lanes controlled by the traffic light."""
        conn = self._conn()
        tl_id = self.get_tl_id()
        return list(conn.trafficlight.getControlledLanes(tl_id))

    def get_num_phases(self) -> int:
        """Return the number of phases in the TL program."""
        conn = self._conn()
        tl_id = self.get_tl_id()
        logic = conn.trafficlight.getAllProgramLogics(tl_id)
        if logic:
            return len(logic[0].phases)
        return 0

    def install_fixed_time_program(
        self,
        green_duration: int = 35,
        yellow_duration: int = 3,
    ) -> None:
        """Install a fixed-time TLS program for baseline comparison.

        Creates a 4-phase program:
          Phase 0: NS green, EW red  (green_duration s)
          Phase 1: NS yellow, EW red (yellow_duration s)
          Phase 2: NS red, EW green  (green_duration s)
          Phase 3: NS red, EW yellow (yellow_duration s)
        """
        conn = self._conn()
        tl_id = self.get_tl_id()

        # Get current program to understand the link count
        current = conn.trafficlight.getAllProgramLogics(tl_id)
        if not current:
            raise RuntimeError("No TLS program found")

        num_links = len(current[0].phases[0].state)

        # Build simple 2-axis fixed program
        # For a 4-arm intersection with 2 lanes each:
        #   The state string encodes each controlled link.
        #   We use the existing state length and create a simple
        #   NS-green / EW-green alternation.

        # Get the green phases from the existing program
        # We'll create our own simple program
        half = num_links // 2

        # Phase 0: first half green, second half red
        ns_green = "G" * half + "r" * (num_links - half)
        ns_yellow = "y" * half + "r" * (num_links - half)
        # Phase 2: first half red, second half green
        ew_green = "r" * half + "G" * (num_links - half)
        ew_yellow = "r" * half + "y" * (num_links - half)

        phases = [
            traci.trafficlight.Phase(green_duration, ns_green),
            traci.trafficlight.Phase(yellow_duration, ns_yellow),
            traci.trafficlight.Phase(green_duration, ew_green),
            traci.trafficlight.Phase(yellow_duration, ew_yellow),
        ]

        logic = traci.trafficlight.Logic(
            "fixed_baseline", 0, 0, phases=phases,
        )

        conn.trafficlight.setProgramLogic(tl_id, logic)
        conn.trafficlight.setProgram(tl_id, "fixed_baseline")
        logger.info(
            "Installed fixed-time program: %ds green / %ds yellow",
            green_duration,
            yellow_duration,
        )

    # ── Internal ──────────────────────────────────────────────────────

    def _conn(self):
        """Get the TraCI connection, raising if not running."""
        if not self._running:
            raise RuntimeError(f"SUMO [{self._label}] is not running")
        return traci.getConnection(self._label)
