"""Network persistence service for managing network metadata on disk."""

import json
import logging
from datetime import datetime, timezone

from app.services.osm_service import SIMULATION_NETWORKS_DIR, _network_cache

logger = logging.getLogger(__name__)


def save_network_metadata(
    network_id: str,
    bbox: dict,
    junctions: list[dict],
    road_count: int,
    name: str | None = None,
) -> dict:
    """
    Save network metadata to a .meta.json file alongside the .net.xml.

    Args:
        network_id: Unique network identifier (hash-based).
        bbox: Dict with south, west, north, east keys.
        junctions: List of junction dicts with id, lat, lon, tl_id keys.
        road_count: Total number of road segments.
        name: Optional human-readable name for the network.

    Returns:
        The saved metadata dict.
    """
    SIMULATION_NETWORKS_DIR.mkdir(parents=True, exist_ok=True)

    metadata = {
        "network_id": network_id,
        "bbox": bbox,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "junctions": junctions,
        "road_count": road_count,
        "name": name,
    }

    meta_path = SIMULATION_NETWORKS_DIR / f"{network_id}.meta.json"
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    logger.info(f"Saved network metadata: {meta_path}")

    return metadata


def load_network_metadata(network_id: str) -> dict | None:
    """
    Load network metadata from a .meta.json file.

    Args:
        network_id: Unique network identifier.

    Returns:
        Metadata dict if found, None otherwise.
    """
    meta_path = SIMULATION_NETWORKS_DIR / f"{network_id}.meta.json"
    if not meta_path.exists():
        return None

    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        # Compute signalized_junction_count (not stored, derived)
        data["signalized_junction_count"] = sum(
            1 for j in data.get("junctions", []) if j.get("tl_id") is not None
        )
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load metadata for {network_id}: {e}")
        return None


def list_networks() -> list[dict]:
    """
    Scan simulation/networks/ for .meta.json files and return metadata list.

    Returns:
        List of metadata dicts sorted by created_at descending.
    """
    if not SIMULATION_NETWORKS_DIR.exists():
        return []

    networks = []
    for meta_path in SIMULATION_NETWORKS_DIR.glob("*.meta.json"):
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            data["signalized_junction_count"] = sum(
                1 for j in data.get("junctions", []) if j.get("tl_id") is not None
            )
            networks.append(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Skipping invalid metadata file {meta_path}: {e}")

    # Sort by created_at descending
    networks.sort(key=lambda n: n.get("created_at", ""), reverse=True)
    return networks


def delete_network(network_id: str) -> int:
    """
    Delete all files associated with a network: .net.xml, .meta.json, and route files.

    Args:
        network_id: Unique network identifier.

    Returns:
        Number of files removed.
    """
    if not SIMULATION_NETWORKS_DIR.exists():
        return 0

    files_removed = 0

    # .net.xml
    net_path = SIMULATION_NETWORKS_DIR / f"{network_id}.net.xml"
    if net_path.exists():
        net_path.unlink()
        files_removed += 1
        logger.info(f"Deleted network file: {net_path}")

    # .meta.json
    meta_path = SIMULATION_NETWORKS_DIR / f"{network_id}.meta.json"
    if meta_path.exists():
        meta_path.unlink()
        files_removed += 1
        logger.info(f"Deleted metadata file: {meta_path}")

    # Route files: {network_id}_*.rou.xml and {network_id}_*.rou.alt.xml
    for route_file in SIMULATION_NETWORKS_DIR.glob(f"{network_id}_*.rou*"):
        route_file.unlink()
        files_removed += 1
        logger.info(f"Deleted route file: {route_file}")

    # Remove from in-memory cache if present
    if network_id in _network_cache:
        del _network_cache[network_id]
        logger.info(f"Removed {network_id} from in-memory cache")

    return files_removed


def restore_network_to_cache(network_id: str) -> dict | None:
    """
    Read .meta.json and populate osm_service._network_cache with a lightweight entry.

    This allows API operations that check the cache (e.g., convert_to_sumo) to find
    the network without re-extracting from OSM. The cache entry contains bbox and
    junctions but no full OSM graph.

    Args:
        network_id: Unique network identifier.

    Returns:
        Metadata dict if successfully restored, None if metadata not found.
    """
    metadata = load_network_metadata(network_id)
    if metadata is None:
        return None

    bbox = metadata["bbox"]
    bbox_tuple = (bbox["south"], bbox["west"], bbox["north"], bbox["east"])

    # Build lightweight intersection list from junctions
    intersections = []
    for j in metadata.get("junctions", []):
        intersections.append({
            "id": j["id"],
            "lat": j["lat"],
            "lon": j["lon"],
            "name": None,
            "num_roads": 0,
            "has_traffic_light": j.get("tl_id") is not None,
            "sumo_tl_id": j.get("tl_id"),
        })

    _network_cache[network_id] = {
        "graph": None,  # No full graph available from metadata
        "intersections": intersections,
        "road_count": metadata.get("road_count", 0),
        "bbox": bbox_tuple,
        "traffic_signal_nodes": set(),
    }

    logger.info(f"Restored network {network_id} to in-memory cache from metadata")
    return metadata
