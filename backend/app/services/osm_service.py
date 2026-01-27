# OpenStreetMap service for fetching and processing map data

import hashlib
import logging
import os
import subprocess
import tempfile
from pathlib import Path

import osmnx as ox

logger = logging.getLogger(__name__)

# In-memory cache for extracted networks
# Keys: network_id, Values: dict with graph, intersections, metadata
_network_cache: dict[str, dict] = {}

# Base directory for SUMO network files
# Path: osm_service.py -> services -> app -> backend -> traffic-monitor
SIMULATION_NETWORKS_DIR = Path(__file__).parent.parent.parent.parent / "simulation" / "networks"


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
        # OSMnx expects bbox as (north, south, east, west) for graph_from_bbox
        graph = ox.graph_from_bbox(
            bbox=(north, south, east, west),
            network_type="drive",
            simplify=True,
        )
    except Exception as e:
        logger.error(f"Failed to download OSM network: {e}")
        raise RuntimeError(f"Failed to download OSM network for bbox {bbox}: {e}") from e

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


def convert_to_sumo(network_id: str) -> Path:
    """
    Convert cached OSM network to SUMO format using netconvert.

    Args:
        network_id: The unique identifier for the network

    Returns:
        Path to the generated SUMO .net.xml file

    Raises:
        KeyError: If network_id is not found in cache
        RuntimeError: If netconvert fails
    """
    if network_id not in _network_cache:
        raise KeyError(f"Network '{network_id}' not found in cache. Extract the network first.")

    # Ensure output directory exists
    SIMULATION_NETWORKS_DIR.mkdir(parents=True, exist_ok=True)

    output_path = SIMULATION_NETWORKS_DIR / f"{network_id}.net.xml"

    # If already converted, return existing file
    if output_path.exists():
        logger.info(f"SUMO network already exists: {output_path}")
        return output_path

    cached = _network_cache[network_id]
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
        return output_path

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
