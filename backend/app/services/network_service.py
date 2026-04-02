"""Service for network metadata persistence."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from app.config import settings

NETWORKS_DIR = settings.simulation_networks_dir


def save_metadata(
    network_id: str,
    bbox: dict,
    intersection_count: int = 0,
    traffic_light_count: int = 0,
    junctions: list[dict] | None = None,
    road_count: int = 0,
) -> Path:
    """Save network metadata to .meta.json file."""
    NETWORKS_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = NETWORKS_DIR / f"{network_id}.meta.json"

    metadata = {
        "network_id": network_id,
        "bbox": bbox,
        "intersection_count": intersection_count,
        "traffic_light_count": traffic_light_count,
        "junctions": junctions or [],
        "road_count": road_count,
        "created_at": datetime.now().isoformat(),
    }

    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info(f"Saved network metadata: {meta_path}")
    return meta_path


def load_metadata(network_id: str) -> dict[str, Any] | None:
    """Load network metadata from .meta.json file."""
    meta_path = NETWORKS_DIR / f"{network_id}.meta.json"
    if not meta_path.exists():
        return None

    with open(meta_path) as f:
        return json.load(f)


def list_networks() -> list[dict[str, Any]]:
    """List all networks with metadata."""
    networks = []

    if not NETWORKS_DIR.exists():
        return networks

    for meta_file in NETWORKS_DIR.glob("*.meta.json"):
        try:
            with open(meta_file) as f:
                metadata = json.load(f)
            networks.append(metadata)
        except Exception:
            continue

    networks.sort(key=lambda n: n.get("created_at", ""), reverse=True)
    return networks


def delete_network(network_id: str) -> dict[str, Any]:
    """Delete a network and its associated files."""
    deleted_files = []

    # Delete meta.json
    meta_path = NETWORKS_DIR / f"{network_id}.meta.json"
    if meta_path.exists():
        meta_path.unlink()
        deleted_files.append(str(meta_path))

    # Delete .net.xml
    net_path = NETWORKS_DIR / f"{network_id}.net.xml"
    if net_path.exists():
        net_path.unlink()
        deleted_files.append(str(net_path))

    # Delete route files
    for route_file in NETWORKS_DIR.glob(f"{network_id}_*.rou.xml"):
        route_file.unlink()
        deleted_files.append(str(route_file))

    # Delete .rou.alt.xml files
    for alt_file in NETWORKS_DIR.glob(f"{network_id}_*.rou.alt.xml"):
        alt_file.unlink()
        deleted_files.append(str(alt_file))

    if not deleted_files:
        raise FileNotFoundError(f"Network not found: {network_id}")

    logger.info(f"Deleted network {network_id}: {len(deleted_files)} files")
    return {"network_id": network_id, "deleted_files": deleted_files}
