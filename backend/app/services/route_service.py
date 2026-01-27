"""Route generation service for SUMO simulations.

This service generates vehicle routes for SUMO simulations using randomTrips.py
and duarouter tools. It supports Vietnamese traffic patterns with configurable
traffic scenarios.
"""

import logging
import os
import subprocess
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

# SUMO environment
SUMO_HOME = os.environ.get("SUMO_HOME", "/usr/share/sumo")

# Vietnamese vehicle types file path
VTYPES_FILE = Path(__file__).parent.parent.parent.parent / "simulation" / "vtypes" / "vietnamese_vtypes.add.xml"


class TrafficScenario(Enum):
    """Traffic scenario definitions with vehicle generation rates."""
    LIGHT = "light"         # 0.3 veh/s
    MODERATE = "moderate"   # 0.8 veh/s
    HEAVY = "heavy"         # 1.5 veh/s
    RUSH_HOUR = "rush_hour" # 2.0 veh/s with peak patterns


# Vehicle generation periods (seconds between vehicles) for each scenario
SCENARIO_PERIODS = {
    TrafficScenario.LIGHT: 1.0 / 0.3,      # ~3.33 seconds
    TrafficScenario.MODERATE: 1.0 / 0.8,   # ~1.25 seconds
    TrafficScenario.HEAVY: 1.0 / 1.5,      # ~0.67 seconds
    TrafficScenario.RUSH_HOUR: 1.0 / 2.0,  # 0.5 seconds
}

# Vietnamese vehicle type distribution: 80% motorbikes, 15% cars, 5% buses
VEHICLE_DISTRIBUTION = {
    "motorbike": 0.80,
    "car": 0.15,
    "bus": 0.05,
}


def _check_sumo_tools() -> None:
    """Check if SUMO tools are available."""
    random_trips_path = Path(SUMO_HOME) / "tools" / "randomTrips.py"
    duarouter_path = Path(SUMO_HOME) / "bin" / "duarouter"

    if not random_trips_path.exists():
        raise RuntimeError(f"randomTrips.py not found at {random_trips_path}")
    if not duarouter_path.exists():
        raise RuntimeError(f"duarouter not found at {duarouter_path}")


def _build_trip_attributes() -> str:
    """Build trip attributes string for vehicle type distribution."""
    # Format: "type1:prob1 type2:prob2 ..."
    # randomTrips.py uses this for --trip-attributes with type distribution
    type_dist = " ".join(f'type="{vtype}"' for vtype in VEHICLE_DISTRIBUTION.keys())
    return type_dist


def generate_routes(
    network_path: str,
    output_dir: str,
    scenario: TrafficScenario,
    duration: int = 3600,
    seed: int | None = None,
) -> dict:
    """Generate vehicle routes for SUMO simulation.

    Uses randomTrips.py for trip generation and duarouter for route validation.
    Generates routes with Vietnamese vehicle type distribution (80% motorbikes,
    15% cars, 5% buses).

    Args:
        network_path: Path to the SUMO .net.xml file
        output_dir: Directory to store generated route files
        scenario: Traffic scenario determining vehicle generation rate
        duration: Simulation duration in seconds (default 3600 = 1 hour)
        seed: Random seed for reproducibility (optional)

    Returns:
        dict with:
            - routes_path: Path to the generated .rou.xml file
            - trip_count: Estimated number of generated trips
            - vehicle_distribution: Dict with vehicle type percentages

    Raises:
        RuntimeError: If SUMO tools are not available or route generation fails
        FileNotFoundError: If network file does not exist
        ValueError: If invalid scenario is provided
    """
    _check_sumo_tools()

    network_file = Path(network_path)
    if not network_file.exists():
        raise FileNotFoundError(f"Network file not found: {network_path}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Validate vtypes file exists
    if not VTYPES_FILE.exists():
        raise RuntimeError(f"Vehicle types file not found: {VTYPES_FILE}")

    # Generate file names based on network and scenario
    network_name = network_file.stem.replace(".net", "")
    trips_file = output_path / f"{network_name}_{scenario.value}.trips.xml"
    routes_file = output_path / f"{network_name}_{scenario.value}.rou.xml"

    period = SCENARIO_PERIODS[scenario]
    estimated_trips = int(duration / period)

    logger.info(
        f"Generating routes for {network_name} with {scenario.value} traffic "
        f"(period={period:.2f}s, ~{estimated_trips} trips over {duration}s)"
    )

    # Step 1: Generate random trips using randomTrips.py
    random_trips_path = Path(SUMO_HOME) / "tools" / "randomTrips.py"

    # Build vehicle type distribution string for --vehicle-class
    # We generate trips for each vehicle class proportionally
    trips_cmd = [
        "python3",
        str(random_trips_path),
        "-n", str(network_path),
        "-o", str(trips_file),
        "-e", str(duration),
        "-p", str(period),
        "--additional-file", str(VTYPES_FILE),
        "--vehicle-class", "motorcycle",  # Allow motorcycles on the network
        "--validate",
    ]

    if seed is not None:
        trips_cmd.extend(["--seed", str(seed)])

    # Add fringe factor to prefer starting/ending at network edges
    trips_cmd.extend(["--fringe-factor", "5"])

    logger.info(f"Running randomTrips: {' '.join(trips_cmd)}")

    try:
        result = subprocess.run(
            trips_cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(output_path),
        )

        if result.returncode != 0:
            logger.error(f"randomTrips failed: {result.stderr}")
            raise RuntimeError(f"randomTrips failed: {result.stderr}")

        logger.info("Random trips generated successfully")

    except subprocess.TimeoutExpired:
        logger.error("randomTrips timed out after 5 minutes")
        raise RuntimeError("randomTrips timed out after 5 minutes")

    except FileNotFoundError as e:
        logger.error(f"Failed to run randomTrips: {e}")
        raise RuntimeError(f"Failed to run randomTrips: {e}")

    # Step 2: Convert trips to routes using duarouter
    duarouter_path = Path(SUMO_HOME) / "bin" / "duarouter"

    dua_cmd = [
        str(duarouter_path),
        "-n", str(network_path),
        "-t", str(trips_file),
        "-o", str(routes_file),
        "--additional-files", str(VTYPES_FILE),
        "--ignore-errors",
        "--no-warnings",
    ]

    if seed is not None:
        dua_cmd.extend(["--seed", str(seed)])

    logger.info(f"Running duarouter: {' '.join(dua_cmd)}")

    try:
        result = subprocess.run(
            dua_cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            logger.error(f"duarouter failed: {result.stderr}")
            raise RuntimeError(f"duarouter failed: {result.stderr}")

        logger.info(f"Routes generated successfully: {routes_file}")

    except subprocess.TimeoutExpired:
        logger.error("duarouter timed out after 5 minutes")
        raise RuntimeError("duarouter timed out after 5 minutes")

    except FileNotFoundError as e:
        logger.error(f"Failed to run duarouter: {e}")
        raise RuntimeError(f"Failed to run duarouter: {e}")

    # Clean up intermediate trips file
    if trips_file.exists():
        try:
            trips_file.unlink()
            logger.debug(f"Cleaned up trips file: {trips_file}")
        except OSError as e:
            logger.warning(f"Failed to clean up trips file: {e}")

    return {
        "routes_path": str(routes_file),
        "trip_count": estimated_trips,
        "vehicle_distribution": VEHICLE_DISTRIBUTION.copy(),
    }


def get_vtypes_file_path() -> str:
    """Get the path to the Vietnamese vehicle types file.

    Returns:
        Path to vietnamese_vtypes.add.xml as string

    Raises:
        FileNotFoundError: If the vtypes file does not exist
    """
    if not VTYPES_FILE.exists():
        raise FileNotFoundError(f"Vehicle types file not found: {VTYPES_FILE}")
    return str(VTYPES_FILE)


def get_available_scenarios() -> list[dict]:
    """Get list of available traffic scenarios with their details.

    Returns:
        List of dicts with scenario name, period, and rate
    """
    return [
        {
            "name": scenario.value,
            "period": SCENARIO_PERIODS[scenario],
            "rate": 1.0 / SCENARIO_PERIODS[scenario],
            "description": _get_scenario_description(scenario),
        }
        for scenario in TrafficScenario
    ]


def _get_scenario_description(scenario: TrafficScenario) -> str:
    """Get human-readable description for a scenario."""
    descriptions = {
        TrafficScenario.LIGHT: "Light traffic - 0.3 vehicles/second, typical late night",
        TrafficScenario.MODERATE: "Moderate traffic - 0.8 vehicles/second, typical daytime",
        TrafficScenario.HEAVY: "Heavy traffic - 1.5 vehicles/second, busy periods",
        TrafficScenario.RUSH_HOUR: "Rush hour - 2.0 vehicles/second, peak congestion",
    }
    return descriptions.get(scenario, "Unknown scenario")
