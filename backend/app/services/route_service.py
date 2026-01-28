"""Route generation service for SUMO simulations.

This service generates vehicle routes for SUMO simulations using randomTrips.py
and duarouter tools. It supports Vietnamese traffic patterns with configurable
traffic scenarios.
"""

import logging
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from app.models.schemas import TrafficScenario

logger = logging.getLogger(__name__)

# SUMO environment
SUMO_HOME = os.environ.get("SUMO_HOME", "/usr/share/sumo")

# Vietnamese vehicle types file path
VTYPES_FILE = Path(__file__).parent.parent.parent.parent / "simulation" / "vtypes" / "vietnamese_vtypes.add.xml"


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

    # SUMO tool paths
    random_trips_path = Path(SUMO_HOME) / "tools" / "randomTrips.py"
    duarouter_path = Path(SUMO_HOME) / "bin" / "duarouter"

    # Track temp files for cleanup
    temp_trip_files: list[Path] = []

    try:
        # Step 1: Generate trips for each vehicle type with proportional rates
        for vtype, proportion in VEHICLE_DISTRIBUTION.items():
            if proportion <= 0:
                continue

            # Adjust period for this vehicle type's proportion
            # E.g., for MODERATE (period=1.25s) and motorbike (80%):
            # type_period = 1.25 / 0.80 = 1.5625s between motorbikes
            type_period = period / proportion
            type_trips_file = output_path / f"{network_name}_{scenario.value}_{vtype}.trips.xml"
            temp_trip_files.append(type_trips_file)

            trips_cmd = [
                "python3",
                str(random_trips_path),
                "-n", str(network_path),
                "-o", str(type_trips_file),
                "-e", str(duration),
                "-p", str(type_period),
                "--additional-file", str(VTYPES_FILE),
                "--trip-attributes", f'type="{vtype}"',
                "--validate",
                "--fringe-factor", "5",
            ]

            if seed is not None:
                # Use different seed for each type but deterministic
                type_seed = seed + hash(vtype) % 1000
                trips_cmd.extend(["--seed", str(type_seed)])

            logger.info(f"Generating {vtype} trips (period={type_period:.2f}s): {' '.join(trips_cmd)}")

            try:
                result = subprocess.run(
                    trips_cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    cwd=str(output_path),
                )

                if result.returncode != 0:
                    logger.error(f"randomTrips failed for {vtype}: {result.stderr}")
                    raise RuntimeError(f"randomTrips failed for {vtype}: {result.stderr}")

                logger.info(f"Generated trips for {vtype}")

            except subprocess.TimeoutExpired:
                logger.error(f"randomTrips timed out for {vtype}")
                raise RuntimeError(f"randomTrips timed out for {vtype} after 5 minutes")

            except FileNotFoundError as e:
                logger.error(f"Failed to run randomTrips: {e}")
                raise RuntimeError(f"Failed to run randomTrips: {e}")

        # Step 2: Merge all trip files into a single combined file
        logger.info("Merging trip files from all vehicle types")

        all_trips: list[ET.Element] = []
        for trip_file in temp_trip_files:
            if trip_file.exists():
                tree = ET.parse(trip_file)
                root = tree.getroot()
                for trip in root.findall("trip"):
                    all_trips.append(trip)

        # Sort trips by departure time
        all_trips.sort(key=lambda t: float(t.get("depart", "0")))

        # Create combined trips file with renumbered IDs to avoid duplicates
        combined_root = ET.Element("routes")
        for idx, trip in enumerate(all_trips):
            trip.set("id", str(idx))  # Renumber to ensure unique IDs
            combined_root.append(trip)

        combined_tree = ET.ElementTree(combined_root)
        ET.indent(combined_tree, space="    ")
        combined_tree.write(trips_file, encoding="unicode", xml_declaration=True)

        logger.info(f"Combined {len(all_trips)} trips into {trips_file}")

        # Step 3: Convert trips to routes using duarouter
        dua_cmd = [
            str(duarouter_path),
            "-n", str(network_path),
            "--route-files", str(trips_file),
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

    finally:
        # Clean up all temporary trip files
        for temp_file in temp_trip_files:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                    logger.debug(f"Cleaned up temp trip file: {temp_file}")
                except OSError as e:
                    logger.warning(f"Failed to clean up temp trip file {temp_file}: {e}")

        # Clean up combined trips file
        if trips_file.exists():
            try:
                trips_file.unlink()
                logger.debug(f"Cleaned up combined trips file: {trips_file}")
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
