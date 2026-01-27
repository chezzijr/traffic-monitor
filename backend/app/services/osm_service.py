# OpenStreetMap service for fetching and processing map data

import hashlib
import logging
import math
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import osmnx as ox

logger = logging.getLogger(__name__)

# In-memory cache for extracted networks
# Keys: network_id, Values: dict with graph, intersections, metadata
_network_cache: dict[str, dict] = {}

# Base directory for SUMO network files
# Path: osm_service.py -> services -> app -> backend -> traffic-monitor
SIMULATION_NETWORKS_DIR = Path(__file__).parent.parent.parent.parent / "simulation" / "networks"

# Distance threshold for OSM-to-SUMO coordinate matching (~100m at equator)
COORD_MATCH_THRESHOLD_DEG = 0.001


def _generate_network_id(bbox: tuple[float, float, float, float]) -> str:
    """Generate a unique network ID based on bounding box coordinates."""
    bbox_str = f"{bbox[0]:.6f},{bbox[1]:.6f},{bbox[2]:.6f},{bbox[3]:.6f}"
    return hashlib.sha256(bbox_str.encode()).hexdigest()[:16]


def _extract_intersection_name(graph, node_id: int) -> str | None:
    """Try to extract a street name for an intersection from connected edges."""
    try:
        edges = list(graph.edges(node_id, data=True))
        for _, _, data in edges:
            if "name" in data and data["name"]:
                name = data["name"]
                if isinstance(name, list):
                    return name[0]
                return name
    except Exception:
        pass
    return None


def _extract_traffic_signals(bbox: tuple[float, float, float, float]) -> set[int]:
    """
    Extract OSM node IDs with highway=traffic_signals tag.

    Args:
        bbox: Tuple of (south, west, north, east) coordinates

    Returns:
        Set of OSM node IDs that have traffic signals
    """
    south, west, north, east = bbox

    try:
        # OSMnx features_from_bbox expects bbox as (west, south, east, north) named parameter
        gdf = ox.features_from_bbox(
            bbox=(west, south, east, north),
            tags={"highway": "traffic_signals"}
        )
        # Extract node IDs from the GeoDataFrame index
        # Index is MultiIndex with (element_type, osm_id)
        return {osm_id for (elem_type, osm_id) in gdf.index if elem_type == "node"}
    except Exception as e:
        # features_from_bbox can fail if no traffic signals exist in the area
        logger.warning(f"Could not extract traffic signals for bbox {bbox}: {e}")
        return set()


def extract_network(bbox: tuple[float, float, float, float]) -> dict:
    """
    Extract road network from OpenStreetMap for the given bounding box.

    Args:
        bbox: Tuple of (south, west, north, east) coordinates

    Returns:
        Dict with network_id, intersections list, road_count, bbox

    Raises:
        ValueError: If bbox coordinates are invalid
        RuntimeError: If network extraction fails
    """
    south, west, north, east = bbox

    # Validate bbox
    if south >= north:
        raise ValueError(f"South ({south}) must be less than north ({north})")
    if west >= east:
        raise ValueError(f"West ({west}) must be less than east ({east})")

    network_id = _generate_network_id(bbox)

    # Check cache first
    if network_id in _network_cache:
        logger.info(f"Returning cached network: {network_id}")
        cached = _network_cache[network_id]
        return {
            "network_id": network_id,
            "intersections": cached["intersections"],
            "road_count": cached["road_count"],
            "bbox": {"south": south, "west": west, "north": north, "east": east},
        }

    logger.info(f"Extracting network for bbox: {bbox}")

    try:
        # Download road network from OSM
        # OSMnx 2.x expects bbox as (left, bottom, right, top) = (west, south, east, north)
        graph = ox.graph_from_bbox(
            bbox=(west, south, east, north),
            network_type="drive",
            simplify=False,  # Must be False for save_graph_xml() to work
        )
    except Exception as e:
        logger.error(f"Failed to download OSM network: {e}")
        raise RuntimeError(f"Failed to download OSM network for bbox {bbox}: {e}") from e

    # Extract traffic signal node IDs
    traffic_signal_nodes = _extract_traffic_signals(bbox)
    logger.info(f"Found {len(traffic_signal_nodes)} traffic signals in bbox")

    # Identify intersections (nodes with degree > 2)
    intersections = []
    for node_id, data in graph.nodes(data=True):
        degree = graph.degree(node_id)
        if degree > 2:
            intersection = {
                "id": str(node_id),
                "lat": data.get("y", 0.0),
                "lon": data.get("x", 0.0),
                "name": _extract_intersection_name(graph, node_id),
                "num_roads": degree,
                "has_traffic_light": node_id in traffic_signal_nodes,
            }
            intersections.append(intersection)

    # Count road segments (edges)
    road_count = graph.number_of_edges()

    # Cache the network data
    _network_cache[network_id] = {
        "graph": graph,
        "intersections": intersections,
        "road_count": road_count,
        "bbox": bbox,
        "traffic_signal_nodes": traffic_signal_nodes,
    }

    logger.info(f"Extracted network {network_id}: {len(intersections)} intersections, {road_count} roads")

    return {
        "network_id": network_id,
        "intersections": intersections,
        "road_count": road_count,
        "bbox": {"south": south, "west": west, "north": north, "east": east},
    }


def get_intersections(network_id: str) -> list[dict]:
    """
    Get cached intersections for a given network ID.

    Args:
        network_id: The unique identifier for the network

    Returns:
        List of intersection dicts, each with id, lat, lon, name, num_roads

    Raises:
        KeyError: If network_id is not found in cache
    """
    if network_id not in _network_cache:
        raise KeyError(f"Network '{network_id}' not found in cache. Extract the network first.")

    return _network_cache[network_id]["intersections"]


def parse_sumo_traffic_lights(net_xml_path: Path) -> dict:
    """
    Parse SUMO network XML for traffic light IDs, coordinates, and phases.

    Args:
        net_xml_path: Path to the SUMO .net.xml file

    Returns:
        Dict with traffic light data:
        {
            "traffic_lights": [
                {
                    "id": str,           # SUMO traffic light ID
                    "x": float,          # X coordinate in SUMO network
                    "y": float,          # Y coordinate in SUMO network
                    "type": str,         # Traffic light type (e.g., "actuated")
                    "phases": [
                        {
                            "duration": int,   # Phase duration in seconds
                            "state": str,      # Phase state string (e.g., "GGrrGGrr")
                        }
                    ]
                }
            ]
        }
    """
    try:
        tree = ET.parse(net_xml_path)
        root = tree.getroot()
    except ET.ParseError as e:
        logger.error(f"Failed to parse SUMO network XML: {e}")
        return {"traffic_lights": []}

    # Build junction coordinate lookup (junction id -> (x, y))
    junction_coords: dict[str, tuple[float, float]] = {}
    for junction in root.findall(".//junction"):
        jid = junction.get("id")
        jtype = junction.get("type")
        # Only include traffic_light junctions
        if jid and jtype == "traffic_light":
            x = float(junction.get("x", 0))
            y = float(junction.get("y", 0))
            junction_coords[jid] = (x, y)

    # Parse traffic light logic
    traffic_lights = []
    for tl_logic in root.findall(".//tlLogic"):
        tl_id = tl_logic.get("id")
        if tl_id is None:
            continue
        tl_type = tl_logic.get("type", "static")

        # Get coordinates from junction with same ID
        x, y = junction_coords.get(tl_id, (0.0, 0.0))

        # Parse phases
        phases = []
        for phase in tl_logic.findall("phase"):
            duration = int(phase.get("duration", 0))
            state = phase.get("state", "")
            phases.append({
                "duration": duration,
                "state": state,
            })

        traffic_lights.append({
            "id": tl_id,
            "x": x,
            "y": y,
            "type": tl_type,
            "phases": phases,
        })

    logger.info(f"Parsed {len(traffic_lights)} traffic lights from SUMO network")
    return {"traffic_lights": traffic_lights}


def _match_osm_to_sumo_traffic_lights(
    intersections: list[dict],
    sumo_traffic_lights: list[dict],
    net_xml_path: Path,
) -> dict[str, str]:
    """
    Create mapping from OSM intersection IDs to SUMO traffic light IDs.

    Uses coordinate matching by converting SUMO coordinates to lat/lon
    and finding the closest OSM intersection with a traffic light.

    Args:
        intersections: List of intersection dicts from extract_network()
        sumo_traffic_lights: List of traffic light dicts from parse_sumo_traffic_lights()
        net_xml_path: Path to SUMO .net.xml file (for projection info)

    Returns:
        Dict mapping OSM intersection ID (str) to SUMO traffic light ID (str)
    """
    # Parse location info from SUMO network for coordinate projection
    try:
        tree = ET.parse(net_xml_path)
        root = tree.getroot()
        location = root.find(".//location")
        if location is None:
            logger.warning("No location element found in SUMO network")
            return {}

        # Get original boundary (lat/lon)
        orig_boundary_str = location.get("origBoundary", "")
        if orig_boundary_str:
            orig_parts = orig_boundary_str.split(",")
            if len(orig_parts) != 4:
                logger.warning("Invalid origBoundary format in SUMO network")
                return {}
            orig_west = float(orig_parts[0])
            orig_south = float(orig_parts[1])
            orig_east = float(orig_parts[2])
            orig_north = float(orig_parts[3])
        else:
            logger.warning("No origBoundary in SUMO network, cannot match coordinates")
            return {}

        # Get converted boundary
        conv_boundary_str = location.get("convBoundary", "")
        if conv_boundary_str:
            conv_parts = conv_boundary_str.split(",")
            if len(conv_parts) != 4:
                logger.warning("Invalid convBoundary format in SUMO network")
                return {}
            conv_west = float(conv_parts[0])
            conv_south = float(conv_parts[1])
            conv_east = float(conv_parts[2])
            conv_north = float(conv_parts[3])
        else:
            logger.warning("No convBoundary in SUMO network, cannot match coordinates")
            return {}

    except (ET.ParseError, ValueError) as e:
        logger.error(f"Failed to parse SUMO network location: {e}")
        return {}

    # Filter intersections with traffic lights
    tl_intersections = [i for i in intersections if i.get("has_traffic_light", False)]

    # Calculate scale factors for coordinate conversion
    lon_scale = (orig_east - orig_west) / (conv_east - conv_west) if conv_east != conv_west else 1.0
    lat_scale = (orig_north - orig_south) / (conv_north - conv_south) if conv_north != conv_south else 1.0

    osm_to_sumo_map: dict[str, str] = {}

    # For each SUMO traffic light, find closest OSM intersection
    for sumo_tl in sumo_traffic_lights:
        sumo_x = sumo_tl["x"]
        sumo_y = sumo_tl["y"]

        # Convert SUMO coordinates to approximate lat/lon
        # SUMO uses Cartesian coords, need to reverse the projection
        approx_lon = orig_west + (sumo_x - conv_west) * lon_scale
        approx_lat = orig_south + (sumo_y - conv_south) * lat_scale

        # Find closest OSM intersection with traffic light
        best_match = None
        best_distance = float("inf")

        for intersection in tl_intersections:
            # Skip if already matched
            if intersection["id"] in osm_to_sumo_map:
                continue

            int_lat = intersection["lat"]
            int_lon = intersection["lon"]

            # Calculate approximate distance (Euclidean on lat/lon, good enough for matching)
            distance = math.sqrt((int_lat - approx_lat) ** 2 + (int_lon - approx_lon) ** 2)

            if distance < best_distance:
                best_distance = distance
                best_match = intersection

        # Threshold for matching (approximately 100m in degrees)
        if best_match and best_distance < COORD_MATCH_THRESHOLD_DEG:
            osm_to_sumo_map[best_match["id"]] = sumo_tl["id"]
            logger.debug(f"Matched OSM {best_match['id']} to SUMO {sumo_tl['id']} (dist: {best_distance:.6f})")

    logger.info(f"Matched {len(osm_to_sumo_map)} OSM intersections to SUMO traffic lights")
    return osm_to_sumo_map


def convert_to_sumo(network_id: str) -> dict:
    """
    Convert cached OSM network to SUMO format using netconvert.

    Args:
        network_id: The unique identifier for the network

    Returns:
        Dict with:
        - network_path: Path to the generated SUMO .net.xml file (as string)
        - traffic_lights: List of traffic light dicts with id, type, phases
        - osm_to_sumo_tl_map: Dict mapping OSM intersection ID to SUMO traffic light ID

    Raises:
        KeyError: If network_id is not found in cache
        RuntimeError: If netconvert fails
    """
    if network_id not in _network_cache:
        raise KeyError(f"Network '{network_id}' not found in cache. Extract the network first.")

    # Ensure output directory exists
    SIMULATION_NETWORKS_DIR.mkdir(parents=True, exist_ok=True)

    output_path = SIMULATION_NETWORKS_DIR / f"{network_id}.net.xml"
    cached = _network_cache[network_id]

    # If already converted, parse existing file and return enriched data
    if output_path.exists():
        logger.info(f"SUMO network already exists: {output_path}")
        tl_data = parse_sumo_traffic_lights(output_path)
        osm_to_sumo_map = _match_osm_to_sumo_traffic_lights(
            cached["intersections"],
            tl_data["traffic_lights"],
            output_path,
        )
        return {
            "network_path": str(output_path),
            "traffic_lights": tl_data["traffic_lights"],
            "osm_to_sumo_tl_map": osm_to_sumo_map,
        }

    graph = cached["graph"]

    # Save graph as OSM XML to temporary file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".osm", delete=False) as osm_file:
        osm_temp_path = osm_file.name

    try:
        # Export graph to OSM XML format
        ox.save_graph_xml(graph, filepath=osm_temp_path)

        # Get SUMO_HOME for netconvert location
        sumo_home = os.environ.get("SUMO_HOME", "/usr/share/sumo")
        netconvert_path = os.path.join(sumo_home, "bin", "netconvert")

        # Build netconvert command
        cmd = [
            netconvert_path,
            "--osm-files",
            osm_temp_path,
            "--output-file",
            str(output_path),
            "--geometry.remove",
            "--roundabouts.guess",
            "--ramps.guess",
            "--junctions.join",
            "--tls.guess-signals",
            "--tls.discard-simple",
            "--tls.join",
            "--tls.default-type",
            "actuated",
        ]

        logger.info(f"Running netconvert: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        if result.returncode != 0:
            logger.error(f"netconvert failed: {result.stderr}")
            raise RuntimeError(f"netconvert failed with code {result.returncode}: {result.stderr}")

        logger.info(f"SUMO network created: {output_path}")

        # Parse traffic lights from generated network
        tl_data = parse_sumo_traffic_lights(output_path)

        # Create OSM to SUMO traffic light mapping
        osm_to_sumo_map = _match_osm_to_sumo_traffic_lights(
            cached["intersections"],
            tl_data["traffic_lights"],
            output_path,
        )

        return {
            "network_path": str(output_path),
            "traffic_lights": tl_data["traffic_lights"],
            "osm_to_sumo_tl_map": osm_to_sumo_map,
        }

    except subprocess.TimeoutExpired:
        logger.error("netconvert timed out after 5 minutes")
        raise RuntimeError("netconvert timed out after 5 minutes")

    except FileNotFoundError:
        logger.error("netconvert not found. Ensure SUMO is installed and in PATH")
        raise RuntimeError("netconvert not found. Ensure SUMO is installed and SUMO_HOME is set")

    finally:
        # Clean up temporary OSM file
        if os.path.exists(osm_temp_path):
            os.unlink(osm_temp_path)


def clear_cache() -> None:
    """Clear the in-memory network cache."""
    _network_cache.clear()
    logger.info("Network cache cleared")


def get_cached_network_ids() -> list[str]:
    """Get list of all cached network IDs."""
    return list(_network_cache.keys())
