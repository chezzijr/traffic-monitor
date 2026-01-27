"""SUMO simulation service using TraCI.

This service controls the SUMO traffic simulation via TraCI (Traffic Control Interface).
It provides functions to start, stop, pause, resume simulations and control traffic lights.

Note: SUMO's traci module is accessed via SUMO_HOME/tools, not pip installed.
The service gracefully handles cases where SUMO is not installed.
"""

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# SUMO availability flag
SUMO_AVAILABLE = False
traci = None
TraCIException = Exception  # Default fallback

# Try to add SUMO tools to path and import traci
SUMO_HOME = os.environ.get("SUMO_HOME", "/usr/share/sumo")
_sumo_tools_path = os.path.join(SUMO_HOME, "tools")

if os.path.isdir(_sumo_tools_path):
    if _sumo_tools_path not in sys.path:
        sys.path.append(_sumo_tools_path)
    try:
        import traci as _traci
        from traci.exceptions import TraCIException as _TraCIException

        traci = _traci
        TraCIException = _TraCIException
        SUMO_AVAILABLE = True
        logger.info(f"SUMO tools loaded from {_sumo_tools_path}")
    except ImportError as e:
        logger.warning(f"Failed to import traci from {_sumo_tools_path}: {e}")
else:
    logger.warning(f"SUMO tools path not found: {_sumo_tools_path}")


def _check_sumo_available() -> None:
    """Check if SUMO is available and raise an error if not."""
    if not SUMO_AVAILABLE:
        raise RuntimeError(
            "SUMO is not available. Please ensure SUMO is installed and "
            "SUMO_HOME environment variable is set correctly."
        )


class SimulationState:
    """Holds the current simulation state with thread-safe access."""

    def __init__(self) -> None:
        self.is_running: bool = False
        self.is_paused: bool = False
        self.current_step: int = 0
        self.network_id: Optional[str] = None
        self.network_path: Optional[str] = None
        self._lock = threading.Lock()

    def reset(self) -> None:
        """Reset state to initial values (must be called with lock held)."""
        self.is_running = False
        self.is_paused = False
        self.current_step = 0
        self.network_id = None
        self.network_path = None


# Global simulation state
_state = SimulationState()


def start_simulation(network_path: str, network_id: str, gui: bool = False) -> dict:
    """Start a SUMO simulation.

    Args:
        network_path: Path to the SUMO .net.xml file
        network_id: ID of the network being simulated
        gui: Whether to use SUMO-GUI (False for headless)

    Returns:
        dict with simulation status containing:
            - status: "started"
            - network_id: ID of the network
            - step: current simulation step (0)

    Raises:
        RuntimeError: If simulation already running, SUMO not available,
                     or SUMO fails to start
    """
    _check_sumo_available()

    with _state._lock:
        if _state.is_running:
            raise RuntimeError("Simulation already running")

        # Validate network file exists
        network_file = Path(network_path)
        if not network_file.exists():
            raise RuntimeError(f"Network file not found: {network_path}")

        sumo_binary = "sumo-gui" if gui else "sumo"
        sumo_cmd = [
            os.path.join(SUMO_HOME, "bin", sumo_binary),
            "-n",
            str(network_path),
            "--start",  # Start simulation immediately
            "--quit-on-end",
            "--no-warnings",
            "--step-length",
            "1",  # 1 second per step
        ]

        try:
            logger.info(f"Starting SUMO simulation with command: {' '.join(sumo_cmd)}")
            traci.start(sumo_cmd)
            _state.is_running = True
            _state.is_paused = False
            _state.current_step = 0
            _state.network_id = network_id
            _state.network_path = network_path
            logger.info(f"SUMO simulation started for network: {network_id}")
            return {"status": "started", "network_id": network_id, "step": 0}
        except TraCIException as e:
            logger.error(f"Failed to start SUMO: {e}")
            raise RuntimeError(f"Failed to start SUMO: {e}")


def step() -> dict:
    """Advance simulation by one step.

    Returns:
        dict with current metrics containing:
            - step: current simulation step
            - total_vehicles: number of vehicles in simulation
            - total_wait_time: sum of all vehicle waiting times
            - average_wait_time: average waiting time per vehicle
            - average_speed: average speed of all vehicles (m/s)

    Raises:
        RuntimeError: If no simulation running, simulation is paused,
                     or step execution fails
    """
    _check_sumo_available()

    with _state._lock:
        if not _state.is_running:
            raise RuntimeError("No simulation running")
        if _state.is_paused:
            raise RuntimeError("Simulation is paused")

        try:
            traci.simulationStep()
            _state.current_step += 1

            # Collect metrics
            vehicle_ids = traci.vehicle.getIDList()
            num_vehicles = len(vehicle_ids)

            total_wait_time = 0.0
            total_speed = 0.0

            for vid in vehicle_ids:
                total_wait_time += traci.vehicle.getWaitingTime(vid)
                total_speed += traci.vehicle.getSpeed(vid)

            average_wait_time = total_wait_time / num_vehicles if num_vehicles > 0 else 0.0
            average_speed = total_speed / num_vehicles if num_vehicles > 0 else 0.0

            return {
                "step": _state.current_step,
                "total_vehicles": num_vehicles,
                "total_wait_time": total_wait_time,
                "average_wait_time": average_wait_time,
                "average_speed": average_speed,
            }
        except TraCIException as e:
            logger.error(f"Simulation step failed: {e}")
            raise RuntimeError(f"Simulation step failed: {e}")


def step_multiple(num_steps: int = 10) -> list[dict]:
    """Advance simulation by multiple steps.

    Args:
        num_steps: Number of steps to advance (default 10)

    Returns:
        List of dicts with metrics for each step

    Raises:
        RuntimeError: If no simulation running, simulation is paused,
                     or step execution fails
        ValueError: If num_steps is less than 1
    """
    if num_steps < 1:
        raise ValueError("num_steps must be at least 1")

    results = []
    for _ in range(num_steps):
        result = step()
        results.append(result)

    return results


def pause_simulation() -> dict:
    """Pause the simulation.

    Returns:
        dict with status containing:
            - status: "paused"
            - step: current simulation step

    Raises:
        RuntimeError: If no simulation running
    """
    with _state._lock:
        if not _state.is_running:
            raise RuntimeError("No simulation running")
        _state.is_paused = True
        logger.info(f"Simulation paused at step {_state.current_step}")
        return {"status": "paused", "step": _state.current_step}


def resume_simulation() -> dict:
    """Resume a paused simulation.

    Returns:
        dict with status containing:
            - status: "running"
            - step: current simulation step

    Raises:
        RuntimeError: If no simulation running
    """
    with _state._lock:
        if not _state.is_running:
            raise RuntimeError("No simulation running")
        _state.is_paused = False
        logger.info(f"Simulation resumed at step {_state.current_step}")
        return {"status": "running", "step": _state.current_step}


def stop_simulation() -> dict:
    """Stop and cleanup the simulation.

    Returns:
        dict with status containing:
            - status: "stopped"
            - final_step: the step count when stopped
    """
    with _state._lock:
        final_step = _state.current_step

        if _state.is_running:
            try:
                if SUMO_AVAILABLE and traci is not None:
                    traci.close()
                logger.info(f"SUMO simulation stopped at step {final_step}")
            except Exception as e:
                # Ignore errors during cleanup
                logger.warning(f"Error during SUMO cleanup (ignored): {e}")

        _state.reset()
        return {"status": "stopped", "final_step": final_step}


def get_status() -> dict:
    """Get current simulation status.

    Returns:
        dict with status containing:
            - status: "idle", "running", or "paused"
            - step: current simulation step
            - network_id: ID of the current network (or None)
            - sumo_available: whether SUMO is available
    """
    with _state._lock:
        status = "idle"
        if _state.is_running:
            status = "paused" if _state.is_paused else "running"

        return {
            "status": status,
            "step": _state.current_step,
            "network_id": _state.network_id,
            "sumo_available": SUMO_AVAILABLE,
        }


def set_traffic_light_phase(tl_id: str, phase_index: int) -> dict:
    """Set traffic light to a specific phase.

    Args:
        tl_id: Traffic light ID
        phase_index: Index of the phase to set (0-indexed)

    Returns:
        dict with traffic light status containing:
            - tl_id: traffic light ID
            - phase: current phase index after setting

    Raises:
        RuntimeError: If no simulation running or setting phase fails
    """
    _check_sumo_available()

    with _state._lock:
        if not _state.is_running:
            raise RuntimeError("No simulation running")

        try:
            traci.trafficlight.setPhase(tl_id, phase_index)
            current_phase = traci.trafficlight.getPhase(tl_id)
            logger.debug(f"Set traffic light {tl_id} to phase {current_phase}")
            return {"tl_id": tl_id, "phase": current_phase}
        except TraCIException as e:
            logger.error(f"Failed to set traffic light {tl_id}: {e}")
            raise RuntimeError(f"Failed to set traffic light: {e}")


def set_traffic_light_program(tl_id: str, program_id: str) -> dict:
    """Set traffic light to use a specific program.

    Args:
        tl_id: Traffic light ID
        program_id: ID of the program to use

    Returns:
        dict with traffic light status containing:
            - tl_id: traffic light ID
            - program: current program ID after setting

    Raises:
        RuntimeError: If no simulation running or setting program fails
    """
    _check_sumo_available()

    with _state._lock:
        if not _state.is_running:
            raise RuntimeError("No simulation running")

        try:
            traci.trafficlight.setProgram(tl_id, program_id)
            current_program = traci.trafficlight.getProgram(tl_id)
            logger.debug(f"Set traffic light {tl_id} to program {current_program}")
            return {"tl_id": tl_id, "program": current_program}
        except TraCIException as e:
            logger.error(f"Failed to set traffic light program {tl_id}: {e}")
            raise RuntimeError(f"Failed to set traffic light program: {e}")


def get_traffic_lights() -> list[dict]:
    """Get all traffic lights and their current states.

    Returns:
        List of dicts, each containing:
            - id: traffic light ID
            - phase: current phase index
            - program: current program ID
            - state: current signal state string (e.g., "GGrr")
            - phase_duration: remaining duration of current phase

    Returns empty list if no simulation running or SUMO not available.
    """
    if not SUMO_AVAILABLE:
        return []

    with _state._lock:
        if not _state.is_running:
            return []

        try:
            tl_ids = traci.trafficlight.getIDList()
            result = []
            for tl_id in tl_ids:
                tl_info = {
                    "id": tl_id,
                    "phase": traci.trafficlight.getPhase(tl_id),
                    "program": traci.trafficlight.getProgram(tl_id),
                    "state": traci.trafficlight.getRedYellowGreenState(tl_id),
                    "phase_duration": traci.trafficlight.getPhaseDuration(tl_id),
                }
                result.append(tl_info)
            return result
        except TraCIException as e:
            logger.warning(f"Failed to get traffic lights: {e}")
            return []


def get_traffic_light(tl_id: str) -> Optional[dict]:
    """Get a specific traffic light's current state.

    Args:
        tl_id: Traffic light ID

    Returns:
        dict with traffic light info or None if not found, containing:
            - id: traffic light ID
            - phase: current phase index
            - program: current program ID
            - state: current signal state string
            - phase_duration: remaining duration of current phase
            - controlled_lanes: list of lane IDs controlled by this light

    Raises:
        RuntimeError: If no simulation running
    """
    _check_sumo_available()

    with _state._lock:
        if not _state.is_running:
            raise RuntimeError("No simulation running")

        try:
            # Check if traffic light exists
            tl_ids = traci.trafficlight.getIDList()
            if tl_id not in tl_ids:
                return None

            return {
                "id": tl_id,
                "phase": traci.trafficlight.getPhase(tl_id),
                "program": traci.trafficlight.getProgram(tl_id),
                "state": traci.trafficlight.getRedYellowGreenState(tl_id),
                "phase_duration": traci.trafficlight.getPhaseDuration(tl_id),
                "controlled_lanes": list(traci.trafficlight.getControlledLanes(tl_id)),
            }
        except TraCIException as e:
            logger.warning(f"Failed to get traffic light {tl_id}: {e}")
            return None


def get_vehicles() -> list[dict]:
    """Get all vehicles and their current states.

    Returns:
        List of dicts, each containing:
            - id: vehicle ID
            - position: (x, y) coordinates
            - speed: current speed in m/s
            - waiting_time: accumulated waiting time
            - route_id: current route ID
            - lane_id: current lane ID

    Returns empty list if no simulation running or SUMO not available.
    """
    if not SUMO_AVAILABLE:
        return []

    with _state._lock:
        if not _state.is_running:
            return []

        try:
            vehicle_ids = traci.vehicle.getIDList()
            result = []
            for vid in vehicle_ids:
                position = traci.vehicle.getPosition(vid)
                vehicle_info = {
                    "id": vid,
                    "position": {"x": position[0], "y": position[1]},
                    "speed": traci.vehicle.getSpeed(vid),
                    "waiting_time": traci.vehicle.getWaitingTime(vid),
                    "route_id": traci.vehicle.getRouteID(vid),
                    "lane_id": traci.vehicle.getLaneID(vid),
                }
                result.append(vehicle_info)
            return result
        except TraCIException as e:
            logger.warning(f"Failed to get vehicles: {e}")
            return []


def get_simulation_time() -> float:
    """Get current simulation time in seconds.

    Returns:
        Current simulation time in seconds, or 0.0 if no simulation running

    Raises:
        RuntimeError: If no simulation running
    """
    _check_sumo_available()

    with _state._lock:
        if not _state.is_running:
            raise RuntimeError("No simulation running")

        try:
            return traci.simulation.getTime()
        except TraCIException as e:
            logger.warning(f"Failed to get simulation time: {e}")
            return 0.0


def get_departed_vehicles_count() -> int:
    """Get count of vehicles that departed in the last step.

    Returns:
        Number of vehicles that entered the simulation in the last step

    Raises:
        RuntimeError: If no simulation running
    """
    _check_sumo_available()

    with _state._lock:
        if not _state.is_running:
            raise RuntimeError("No simulation running")

        try:
            return traci.simulation.getDepartedNumber()
        except TraCIException as e:
            logger.warning(f"Failed to get departed vehicles count: {e}")
            return 0


def get_arrived_vehicles_count() -> int:
    """Get count of vehicles that arrived at their destination in the last step.

    Returns:
        Number of vehicles that completed their route in the last step

    Raises:
        RuntimeError: If no simulation running
    """
    _check_sumo_available()

    with _state._lock:
        if not _state.is_running:
            raise RuntimeError("No simulation running")

        try:
            return traci.simulation.getArrivedNumber()
        except TraCIException as e:
            logger.warning(f"Failed to get arrived vehicles count: {e}")
            return 0


def is_simulation_running() -> bool:
    """Check if a simulation is currently running.

    Returns:
        True if simulation is running (even if paused), False otherwise
    """
    with _state._lock:
        return _state.is_running


def is_sumo_available() -> bool:
    """Check if SUMO is available on this system.

    Returns:
        True if SUMO traci module is available, False otherwise
    """
    return SUMO_AVAILABLE


async def step_async() -> dict:
    """Run step() in thread pool to not block event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, step)


def get_is_paused() -> bool:
    """Check if simulation is currently paused."""
    with _state._lock:
        return _state.is_paused


def get_is_running() -> bool:
    """Check if simulation is currently running."""
    with _state._lock:
        return _state.is_running
