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

from app.config import settings
from app.models.schemas import TrafficScenario

logger = logging.getLogger(__name__)

# SUMO environment
SUMO_HOME = os.environ.get("SUMO_HOME", "/usr/share/sumo")

# Vietnamese vehicle types file path
VTYPES_FILE = settings.simulation_vtypes_dir / "vietnamese_vtypes.add.xml"


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

# Junction-concentrated flow rates (vehicles/second total through junction)
# Much lower than network-wide because ALL traffic goes through one junction
JUNCTION_SCENARIO_RATES = {
    TrafficScenario.LIGHT: 0.08,  # ~288 veh/hr
    TrafficScenario.MODERATE: 0.15,  # ~540 veh/hr
    TrafficScenario.HEAVY: 0.25,  # ~900 veh/hr
    TrafficScenario.RUSH_HOUR: 0.35,  # ~1260 veh/hr
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
            # Quarter period to compensate for ~65% route validation drop on OSM networks
            type_period = (period / proportion) * 0.25
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

            # Count actual vehicles in output to detect silent drops
            try:
                tree = ET.parse(str(routes_file))
                actual_vehicles = len(tree.findall('.//vehicle'))
                yield_pct = actual_vehicles / max(estimated_trips, 1) * 100
                logger.info(
                    f"Routes generated: {routes_file} — "
                    f"{actual_vehicles}/{estimated_trips} vehicles ({yield_pct:.0f}% yield)"
                )
                if yield_pct < 50:
                    logger.warning(
                        f"Low route yield ({yield_pct:.0f}%): duarouter dropped "
                        f"{estimated_trips - actual_vehicles} vehicles due to invalid routes"
                    )
            except Exception as count_err:
                logger.warning(f"Could not count vehicles in route file: {count_err}")
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


def _resolve_tl_nodes(net, tl_id: str) -> list:
    """Resolve a traffic light ID to its junction node(s) in sumolib.

    Handles various SUMO TL naming conventions:
    - Simple: '411918637' -> node '411918637'
    - Cluster: 'cluster_X_Y_Z' -> node 'cluster_X_Y_Z'
    - Guessed signal: 'GS_411926667' -> try node '411926667'
    - Joined signal: 'joinedS_X_Y' -> try nodes X, Y individually
    """
    try:
        return [net.getNode(tl_id)]
    except KeyError:
        pass

    if tl_id.startswith("GS_"):
        try:
            return [net.getNode(tl_id[3:])]
        except KeyError:
            pass

    if tl_id.startswith("joinedS_"):
        parts = tl_id[8:].split("_")
        nodes = []
        for part in parts:
            try:
                nodes.append(net.getNode(part))
            except KeyError:
                pass
        if nodes:
            return nodes

    for node in net.getNodes():
        nid = node.getID()
        if tl_id in nid or nid in tl_id:
            return [node]

    return []


def generate_junction_routes(
    network_path: str,
    tl_id: str,
    output_dir: str,
    scenario: TrafficScenario,
    duration: int = 3600,
    seed: int | None = None,
) -> dict:
    """Generate routes concentrated at a specific junction for training.

    Creates SUMO <flow> definitions that direct traffic through the target
    junction's incoming->outgoing edge pairs with asymmetric rates weighted
    by lane count (main roads get more traffic than side roads).

    Args:
        network_path: Path to the SUMO .net.xml file
        tl_id: Traffic light ID to concentrate traffic at
        output_dir: Directory to store generated route files
        scenario: Traffic scenario determining vehicle generation rate
        duration: Simulation duration in seconds
        seed: Random seed (unused, kept for API compatibility)

    Returns:
        dict with routes_path, trip_count, vehicle_distribution
    """
    import sys

    sumo_tools = os.path.join(SUMO_HOME, "tools")
    if sumo_tools not in sys.path:
        sys.path.append(sumo_tools)
    import sumolib

    network_file = Path(network_path)
    if not network_file.exists():
        raise FileNotFoundError(f"Network file not found: {network_path}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if not VTYPES_FILE.exists():
        raise RuntimeError(f"Vehicle types file not found: {VTYPES_FILE}")

    # Check disk cache first
    network_name = network_file.stem.replace(".net", "")
    routes_file = output_path / f"{network_name}_{tl_id}_{scenario.value}_jn.rou.xml"
    total_rate = JUNCTION_SCENARIO_RATES[scenario]
    estimated_vehicles = int(total_rate * duration)

    if routes_file.exists():
        logger.info(f"Using cached junction routes: {routes_file}")
        return {
            "routes_path": str(routes_file),
            "trip_count": estimated_vehicles,
            "vehicle_distribution": VEHICLE_DISTRIBUTION.copy(),
        }

    net = sumolib.net.readNet(str(network_path))

    # Resolve TL ID to node(s)
    nodes = _resolve_tl_nodes(net, tl_id)
    if not nodes:
        raise ValueError(f"Could not resolve junction node(s) for TL '{tl_id}'")

    # Collect incoming/outgoing edges from all resolved nodes
    incoming_edges = []
    outgoing_edges = []
    seen_in, seen_out = set(), set()
    for node in nodes:
        for e in node.getIncoming():
            eid = e.getID()
            if not eid.startswith(":") and eid not in seen_in:
                incoming_edges.append(e)
                seen_in.add(eid)
        for e in node.getOutgoing():
            eid = e.getID()
            if not eid.startswith(":") and eid not in seen_out:
                outgoing_edges.append(e)
                seen_out.add(eid)

    if not incoming_edges or not outgoing_edges:
        raise ValueError(
            f"Junction '{tl_id}' has {len(incoming_edges)} incoming, "
            f"{len(outgoing_edges)} outgoing edges — cannot generate routes"
        )

    logger.info(
        f"Junction {tl_id}: {len(incoming_edges)} incoming, "
        f"{len(outgoing_edges)} outgoing edges"
    )

    # Build valid (in_edge, out_edge) pairs — skip U-turns, prefer connected
    valid_pairs = []
    for in_edge in incoming_edges:
        for out_edge in outgoing_edges:
            in_base = in_edge.getID().lstrip("-")
            out_base = out_edge.getID().lstrip("-")
            if in_base == out_base:
                continue
            for node in nodes:
                if node.getConnections(in_edge, out_edge):
                    valid_pairs.append((in_edge, out_edge))
                    break

    if not valid_pairs:
        logger.warning(f"No connected pairs for TL {tl_id}, using all non-U-turn combos")
        for in_edge in incoming_edges:
            for out_edge in outgoing_edges:
                in_base = in_edge.getID().lstrip("-")
                out_base = out_edge.getID().lstrip("-")
                if in_base != out_base:
                    valid_pairs.append((in_edge, out_edge))

    if not valid_pairs:
        raise ValueError(f"No valid edge pairs for junction '{tl_id}'")

    # Asymmetric weighting by incoming edge lane count
    in_edge_weights: dict[str, float] = {}
    for in_edge, _ in valid_pairs:
        eid = in_edge.getID()
        if eid not in in_edge_weights:
            in_edge_weights[eid] = float(in_edge.getLaneNumber())
    total_weight = sum(in_edge_weights.values())

    # Count outgoing options per incoming edge
    out_count_per_in: dict[str, int] = {}
    for in_edge, _ in valid_pairs:
        eid = in_edge.getID()
        out_count_per_in[eid] = out_count_per_in.get(eid, 0) + 1

    logger.info(
        f"Junction {tl_id}: {len(valid_pairs)} valid pairs, "
        f"lane weights: {in_edge_weights}"
    )

    # Build route XML
    vtypes_tree = ET.parse(str(VTYPES_FILE))
    vtypes_root = vtypes_tree.getroot()

    routes_root = ET.Element("routes")
    for vtype_elem in vtypes_root.findall("vType"):
        routes_root.append(vtype_elem)

    flow_id = 0
    for in_edge, out_edge in valid_pairs:
        in_id = in_edge.getID()
        in_fraction = in_edge_weights[in_id] / total_weight
        pair_fraction = in_fraction / out_count_per_in[in_id]

        for vtype, proportion in VEHICLE_DISTRIBUTION.items():
            prob = total_rate * proportion * pair_fraction
            if prob < 0.0001:
                continue

            flow_elem = ET.SubElement(routes_root, "flow")
            flow_elem.set("id", f"{vtype}_{flow_id}")
            flow_elem.set("type", vtype)
            flow_elem.set("begin", "0")
            flow_elem.set("end", str(duration))
            flow_elem.set("probability", f"{prob:.4f}")
            flow_elem.set("from", in_id)
            flow_elem.set("to", out_edge.getID())
            flow_elem.set("departLane", "best")
            flow_elem.set("departSpeed", "max")
            flow_id += 1

    logger.info(
        f"Generated {flow_id} flow definitions for junction {tl_id}, "
        f"~{estimated_vehicles} vehicles over {duration}s ({scenario.value})"
    )

    tree = ET.ElementTree(routes_root)
    ET.indent(tree, space="    ")
    tree.write(str(routes_file), encoding="unicode", xml_declaration=True)

    return {
        "routes_path": str(routes_file),
        "trip_count": estimated_vehicles,
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
