# Map extraction and SUMO conversion service.
# Uses Overpass API QL (highway-only query) for raw OSM data and
# traffic_light_clustered.json for TL detection — no OSMnx dependency.

import hashlib
import logging
import math
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
import json
import requests

from app.utils.traffic_light_clustered import cluster_traffic_light_file

logger = logging.getLogger(__name__)

# In-memory cache: network_id → {osm_path, intersections, road_count, bbox}
_network_cache: dict[str, dict] = {}

from app.config import settings

SIMULATION_NETWORKS_DIR = settings.simulation_networks_dir

CACHE_DIR = Path(__file__).parent.parent.parent.parent / "cache"
TRAFFIC_LIGHT_PATH = CACHE_DIR / "all_traffic_light.json"
TRAFFIC_LIGHT_CLUSTERED_PATH = CACHE_DIR / "traffic_light_clustered.json"

# Distance threshold for OSM-to-SUMO coordinate matching (~100m at equator)
COORD_MATCH_THRESHOLD_DEG = 0.001
# Nearest OSM intersection enrichment for SUMO-first junctions (~220m at equator)
ENRICH_MATCH_THRESHOLD_DEG = 0.002
# Merge SUMO TL markers within this distance (m) into one map pin per physical junction
TL_CLUSTER_RADIUS_M = 50.0

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Highway types that vehicles can drive on (used for intersection detection)
DRIVEABLE_HIGHWAY_TYPES = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "service", "road", "track",
    "living_street", "busway",
    "motorway_link", "trunk_link", "primary_link",
    "secondary_link", "tertiary_link", "motorway_junction",
}


def _generate_network_id(bbox: tuple[float, float, float, float]) -> str:
    """Generate a unique network ID based on bounding box coordinates."""
    bbox_str = f"{bbox[0]:.6f},{bbox[1]:.6f},{bbox[2]:.6f},{bbox[3]:.6f}"
    return hashlib.sha256(bbox_str.encode()).hexdigest()[:16]


def _expand_bbox(
    south: float, west: float, north: float, east: float, buffer_meters: float = 300
) -> tuple[float, float, float, float]:
    """Expand bounding box by buffer in all directions (meters → degrees)."""
    lat_buffer = buffer_meters / 111320
    avg_lat = (south + north) / 2
    lon_buffer = buffer_meters / (111320 * math.cos(math.radians(avg_lat)))
    return (south - lat_buffer, west - lon_buffer, north + lat_buffer, east + lon_buffer)


def _load_clustered_tl_ids(bbox: tuple[float, float, float, float]) -> set[int]:
    """Return OSM node IDs of traffic lights inside bbox from the clustered cache."""
    south, west, north, east = bbox
    if not TRAFFIC_LIGHT_CLUSTERED_PATH.exists():
        logger.warning("traffic_light_clustered.json not found — TL tagging will rely on OSM tags only")
        return set()
    try:
        with open(TRAFFIC_LIGHT_CLUSTERED_PATH, "r", encoding="utf-8") as f:
            nodes = json.load(f)
        ids = {
            int(n["osm_id"])
            for n in nodes
            if south <= n["lat"] <= north and west <= n["lon"] <= east
        }
        logger.debug(f"Loaded {len(ids)} clustered TL IDs for bbox {bbox}")
        return ids
    except Exception as e:
        logger.warning(f"Could not load clustered TL cache: {e}")
        return set()


def _download_osm_highway(
    south: float, west: float, north: float, east: float,
    output_path: Path,
    timeout: int = 60,
) -> None:
    """Download highway-only OSM data for bbox via Overpass QL.

    Uses the Overpass interpreter QL endpoint instead of /api/map so that only
    road geometry is fetched (no buildings, amenities, water, …).  The result
    is a valid .osm XML file that netconvert can consume directly.
    """
    query = (
        f"[out:xml][timeout:{timeout}];"
        f"(way[\"highway\"]({south},{west},{north},{east});>;);"
        f"out body;"
    )
    logger.info(f"Overpass QL query for bbox ({south:.5f},{west:.5f},{north:.5f},{east:.5f})")
    resp = requests.post(
        OVERPASS_URL,
        data={"data": query},
        timeout=timeout + 15,
        stream=True,
    )
    resp.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=65536):
            fh.write(chunk)
    size_kb = output_path.stat().st_size >> 10
    logger.info(f"Overpass download complete: {size_kb} KB → {output_path}")


def _parse_osm_intersections(
    osm_path: Path,
    orig_bbox: tuple[float, float, float, float],
    tl_node_ids: set[int],
) -> tuple[list[dict], int]:
    """Parse raw .osm XML to find intersections and road count.

    An intersection is a node referenced by ≥ 2 driveable highway ways.
    Results are filtered to orig_bbox (not the expanded download area).
    Returns (intersections, road_count).
    """
    tree = ET.parse(str(osm_path))
    root = tree.getroot()

    # node_id → {lat, lon, tags}
    nodes: dict[int, dict] = {}
    for node_el in root.findall("node"):
        nid = int(node_el.get("id"))
        lat = float(node_el.get("lat", 0))
        lon = float(node_el.get("lon", 0))
        tags = {tag.get("k"): tag.get("v") for tag in node_el.findall("tag")}
        nodes[nid] = {"lat": lat, "lon": lon, "tags": tags}

    # Count driveable-way references per node; collect first street name
    node_way_count: dict[int, int] = {}
    node_way_names: dict[int, str] = {}
    road_count = 0

    for way_el in root.findall("way"):
        tags = {tag.get("k"): tag.get("v") for tag in way_el.findall("tag")}
        hw = tags.get("highway", "")
        if hw not in DRIVEABLE_HIGHWAY_TYPES:
            continue
        road_count += 1
        name = tags.get("name")
        for nd in way_el.findall("nd"):
            ref = int(nd.get("ref"))
            node_way_count[ref] = node_way_count.get(ref, 0) + 1
            if name and ref not in node_way_names:
                node_way_names[ref] = name

    south, west, north, east = orig_bbox
    intersections: list[dict] = []

    for nid, count in node_way_count.items():
        if count < 2:
            continue
        nd = nodes.get(nid)
        if nd is None:
            continue
        lat, lon = nd["lat"], nd["lon"]
        # Restrict to original (non-expanded) bbox
        if not (south <= lat <= north and west <= lon <= east):
            continue

        has_tl = (
            nid in tl_node_ids
            or nd["tags"].get("highway") == "traffic_signals"
        )

        intersections.append({
            "id": str(nid),
            "osm_id": nid,
            "lat": lat,
            "lon": lon,
            "name": node_way_names.get(nid),
            "num_roads": count,
            "has_traffic_light": has_tl,
        })

    return intersections, road_count


def extract_network(bbox: tuple[float, float, float, float]) -> dict:
    """Extract road network for the given bounding box.

    Downloads raw highway OSM data via Overpass QL (no OSMnx), saves it as
    {network_id}.osm on disk, parses intersections and tags TL nodes using the
    pre-built traffic_light_clustered.json cache.

    Args:
        bbox: (south, west, north, east) in WGS-84 degrees

    Returns:
        Dict with network_id, intersections, road_count, bbox
    """
    south, west, north, east = bbox

    if south >= north:
        raise ValueError(f"South ({south}) must be less than north ({north})")
    if west >= east:
        raise ValueError(f"West ({west}) must be less than east ({east})")

    network_id = _generate_network_id(bbox)

    if network_id in _network_cache:
        logger.info(f"Returning in-memory cached network: {network_id}")
        cached = _network_cache[network_id]
        return {
            "network_id": network_id,
            "intersections": cached["intersections"],
            "road_count": cached["road_count"],
            "bbox": {"south": south, "west": west, "north": north, "east": east},
        }

    logger.info(f"Extracting network for bbox: {bbox}")

    # Expand bbox by 300 m so boundary roads are fully included
    exp_south, exp_west, exp_north, exp_east = _expand_bbox(south, west, north, east)
    logger.info(
        f"Expanded bbox: ({exp_south:.6f}, {exp_west:.6f}, {exp_north:.6f}, {exp_east:.6f})"
    )

    SIMULATION_NETWORKS_DIR.mkdir(parents=True, exist_ok=True)
    osm_path = SIMULATION_NETWORKS_DIR / f"{network_id}.osm"

    if not osm_path.exists():
        try:
            _download_osm_highway(exp_south, exp_west, exp_north, exp_east, osm_path)
        except requests.exceptions.Timeout:
            raise RuntimeError(
                "Overpass API timed out. Try a smaller region or retry in a few minutes."
            )
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Overpass API download failed: {e}") from e
    else:
        logger.info(f"Reusing existing OSM file: {osm_path}")

    tl_node_ids = _load_clustered_tl_ids(bbox)

    try:
        intersections, road_count = _parse_osm_intersections(osm_path, bbox, tl_node_ids)
    except ET.ParseError as e:
        osm_path.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to parse downloaded OSM data: {e}") from e

    if road_count == 0:
        osm_path.unlink(missing_ok=True)
        raise ValueError(
            "Selected region contains no driveable road segments. "
            "Please select a larger area (at least 300–500 m across)."
        )

    _network_cache[network_id] = {
        "osm_path": str(osm_path),
        "intersections": intersections,
        "road_count": road_count,
        "bbox": bbox,
    }

    logger.info(
        f"Network {network_id}: {len(intersections)} intersections, {road_count} road ways"
    )
    return {
        "network_id": network_id,
        "intersections": intersections,
        "road_count": road_count,
        "bbox": {"south": south, "west": west, "north": north, "east": east},
    }


def get_intersections(network_id: str) -> list[dict]:
    """Get cached intersections for a network ID."""
    if network_id not in _network_cache:
        raise KeyError(f"Network '{network_id}' not found in cache. Extract the network first.")
    return _network_cache[network_id]["intersections"]


def get_network_bbox(network_id: str) -> tuple | None:
    """Get the bounding box for a cached network."""
    if network_id in _network_cache:
        return _network_cache[network_id]["bbox"]
    return None


def get_road_count(network_id: str) -> int | None:
    """Road-way count from the original OSM extract (unchanged after SUMO conversion)."""
    if network_id not in _network_cache:
        return None
    return _network_cache[network_id].get("road_count", 0)


def parse_sumo_traffic_lights(net_xml_path: Path) -> dict:
    """Parse SUMO network XML for traffic light IDs, coordinates, and phases."""
    try:
        tree = ET.parse(net_xml_path)
        root = tree.getroot()
    except ET.ParseError as e:
        logger.error(f"Failed to parse SUMO network XML: {e}")
        return {"traffic_lights": []}

    junction_coords: dict[str, tuple[float, float]] = {}
    for junction in root.findall(".//junction"):
        jid = junction.get("id")
        if jid and junction.get("type") == "traffic_light":
            junction_coords[jid] = (
                float(junction.get("x", 0)),
                float(junction.get("y", 0)),
            )

    traffic_lights = []
    for tl_logic in root.findall(".//tlLogic"):
        tl_id = tl_logic.get("id")
        if tl_id is None:
            continue
        tl_type = tl_logic.get("type", "static")
        canonical_id = tl_id[3:] if tl_id.startswith("GS_") else tl_id
        x, y = junction_coords.get(tl_id) or junction_coords.get(canonical_id, (0.0, 0.0))

        phases = [
            {"duration": int(p.get("duration", 0)), "state": p.get("state", "")}
            for p in tl_logic.findall("phase")
        ]
        traffic_lights.append({"id": tl_id, "x": x, "y": y, "type": tl_type, "phases": phases})

    logger.info(f"Parsed {len(traffic_lights)} traffic lights from SUMO network")
    return {"traffic_lights": traffic_lights}


def _match_osm_to_sumo_traffic_lights(
    intersections: list[dict],
    sumo_traffic_lights: list[dict],
    net_xml_path: Path,
) -> dict[str, str]:
    """Map OSM intersection IDs to SUMO traffic light IDs via coordinate matching."""
    try:
        tree = ET.parse(net_xml_path)
        root = tree.getroot()
        location = root.find(".//location")
        if location is None:
            logger.warning("No location element in SUMO network")
            return {}

        orig_parts = location.get("origBoundary", "").split(",")
        conv_parts = location.get("convBoundary", "").split(",")
        if len(orig_parts) != 4 or len(conv_parts) != 4:
            logger.warning("Invalid boundary format in SUMO network")
            return {}

        orig_west, orig_south, orig_east, orig_north = map(float, orig_parts)
        conv_west, conv_south, conv_east, conv_north = map(float, conv_parts)
    except (ET.ParseError, ValueError) as e:
        logger.error(f"Failed to parse SUMO network location: {e}")
        return {}

    lon_scale = (orig_east - orig_west) / (conv_east - conv_west) if conv_east != conv_west else 1.0
    lat_scale = (orig_north - orig_south) / (conv_north - conv_south) if conv_north != conv_south else 1.0

    osm_to_sumo_map: dict[str, str] = {}

    for sumo_tl in sumo_traffic_lights:
        approx_lon = orig_west + (sumo_tl["x"] - conv_west) * lon_scale
        approx_lat = orig_south + (sumo_tl["y"] - conv_south) * lat_scale

        best_match = None
        best_dist = float("inf")

        for inter in intersections:
            if inter["id"] in osm_to_sumo_map:
                continue
            dist = math.sqrt(
                (inter["lat"] - approx_lat) ** 2 + (inter["lon"] - approx_lon) ** 2
            )
            if dist < best_dist:
                best_dist = dist
                best_match = inter

        if best_match and best_dist < COORD_MATCH_THRESHOLD_DEG:
            osm_to_sumo_map[best_match["id"]] = sumo_tl["id"]
            logger.debug(
                f"Matched OSM {best_match['id']} → SUMO {sumo_tl['id']} (dist {best_dist:.6f})"
            )

    matched_ids = set(osm_to_sumo_map.keys())
    for inter in intersections:
        if inter["id"] in matched_ids:
            inter["has_traffic_light"] = True

    logger.info(f"Matched {len(osm_to_sumo_map)} OSM intersections to SUMO traffic lights")
    return osm_to_sumo_map


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS-84 points in meters."""
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(min(1.0, math.sqrt(a)))
    return 6371000.0 * c


class _UnionFind:
    def __init__(self, n: int) -> None:
        self._p = list(range(n))

    def find(self, x: int) -> int:
        while self._p[x] != x:
            self._p[x] = self._p[self._p[x]]
            x = self._p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._p[rb] = ra


def _cluster_sumo_junctions_spatial(
    junctions: list[dict],
    radius_m: float = TL_CLUSTER_RADIUS_M,
) -> tuple[list[dict], dict[str, str]]:
    """Merge nearby SUMO TL junctions so the map shows one pin per physical intersection.

    Returns merged junction dicts and a map from every original sumo_tl_id to the canonical
    (representative) tl_id used for that cluster.
    """
    if not junctions:
        return [], {}

    n = len(junctions)
    if n == 1:
        tid = junctions[0]["sumo_tl_id"]
        out = [{**junctions[0], "clustered_tl_ids": None}]
        return out, {tid: tid}

    uf = _UnionFind(n)

    for i in range(n):
        for j in range(i + 1, n):
            a, b = junctions[i], junctions[j]
            d = _haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
            if d <= radius_m:
                uf.union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        r = uf.find(i)
        groups.setdefault(r, []).append(i)

    merged: list[dict] = []
    tl_redirect: dict[str, str] = {}

    for _root, idxs in groups.items():
        members = [junctions[i] for i in idxs]
        clat = sum(m["lat"] for m in members) / len(members)
        clon = sum(m["lon"] for m in members) / len(members)

        canonical_m = min(
            members,
            key=lambda m: _haversine_m(m["lat"], m["lon"], clat, clon),
        )
        canonical_tl = canonical_m["sumo_tl_id"]
        for m in members:
            tl_redirect[m["sumo_tl_id"]] = canonical_tl

        all_tl_ids = sorted({m["sumo_tl_id"] for m in members})
        num_roads = max(m["num_roads"] for m in members)

        cluster_id = (
            f"sumo_cluster_{hashlib.sha256('|'.join(all_tl_ids).encode()).hexdigest()[:14]}"
        )

        merged.append({
            "id": cluster_id,
            "osm_id": canonical_m.get("osm_id"),
            "lat": clat,
            "lon": clon,
            "name": canonical_m.get("name"),
            "num_roads": num_roads,
            "has_traffic_light": True,
            "sumo_tl_id": canonical_tl,
            "clustered_tl_ids": all_tl_ids if len(all_tl_ids) > 1 else None,
        })

    return merged, tl_redirect


def _build_sumo_tl_junctions(
    net_xml_path: Path,
    sumo_traffic_lights: list[dict],
    osm_intersections: list[dict],
) -> tuple[list[dict], dict[str, str]]:
    """Build junction list from SUMO traffic lights (source of truth) with accurate lon/lat.

    Uses sumolib.convertXY2LonLat for projection-correct coordinates. Optionally enriches
    with nearest OSM intersection name/osm_id when within ENRICH_MATCH_THRESHOLD_DEG
    (one OSM node matched at most once).
    """
    import sumolib

    try:
        net = sumolib.net.readNet(str(net_xml_path))
    except Exception as e:
        logger.error(f"Failed to read SUMO network with sumolib: {e}")
        return [], {}

    sumo_junctions: list[dict] = []
    osm_to_sumo_map: dict[str, str] = {}
    used_osm_intersection_ids: set[str] = set()

    for sumo_tl in sumo_traffic_lights:
        tl_id = sumo_tl["id"]
        x, y = sumo_tl["x"], sumo_tl["y"]
        try:
            lon, lat = net.convertXY2LonLat(x, y)
        except Exception as e:
            logger.warning(f"convertXY2LonLat failed for TL {tl_id}: {e}")
            continue

        node = None
        if net.hasNode(tl_id):
            node = net.getNode(tl_id)
        else:
            cand = tl_id[3:] if tl_id.startswith("GS_") else tl_id
            if net.hasNode(cand):
                node = net.getNode(cand)

        if node is not None:
            num_roads = max(len(node.getIncoming()) + len(node.getOutgoing()), 1)
        else:
            num_roads = 2

        best_inter = None
        best_dist = float("inf")
        for inter in osm_intersections:
            if inter["id"] in used_osm_intersection_ids:
                continue
            dist = math.sqrt((inter["lat"] - lat) ** 2 + (inter["lon"] - lon) ** 2)
            if dist < best_dist:
                best_dist = dist
                best_inter = inter

        osm_id: int | None = None
        name: str | None = None
        if best_inter is not None and best_dist < ENRICH_MATCH_THRESHOLD_DEG:
            used_osm_intersection_ids.add(best_inter["id"])
            osm_id = best_inter.get("osm_id")
            name = best_inter.get("name")
            osm_to_sumo_map[best_inter["id"]] = tl_id

        junction_id = f"sumo_{tl_id}"
        sumo_junctions.append({
            "id": junction_id,
            "osm_id": osm_id,
            "lat": lat,
            "lon": lon,
            "name": name,
            "num_roads": num_roads,
            "has_traffic_light": True,
            "sumo_tl_id": tl_id,
        })

    clustered, tl_redirect = _cluster_sumo_junctions_spatial(sumo_junctions, TL_CLUSTER_RADIUS_M)
    osm_to_sumo_map = {k: tl_redirect.get(v, v) for k, v in osm_to_sumo_map.items()}

    logger.info(
        f"Built {len(sumo_junctions)} SUMO TL junctions -> {len(clustered)} after "
        f"clustering (radius {TL_CLUSTER_RADIUS_M}m); "
        f"{len(osm_to_sumo_map)} OSM intersections enriched"
    )
    return clustered, osm_to_sumo_map


def _remove_disconnected_components(net_path: Path, netconvert_path: str, osm_path: str) -> int:
    """Remove disconnected network fragments, keeping only the largest component."""
    import sumolib
    from collections import deque

    net = sumolib.net.readNet(str(net_path))
    edges = net.getEdges(withInternal=False)
    if not edges:
        return 0

    node_to_edges: dict[str, set] = {}
    for edge in edges:
        for node in (edge.getFromNode(), edge.getToNode()):
            node_to_edges.setdefault(node.getID(), set()).add(edge)

    visited_edges: set[str] = set()
    components: list[set[str]] = []
    for edge in edges:
        eid = edge.getID()
        if eid in visited_edges:
            continue
        component: set[str] = set()
        queue = deque([edge])
        while queue:
            current = queue.popleft()
            cid = current.getID()
            if cid in component:
                continue
            component.add(cid)
            visited_edges.add(cid)
            for node in (current.getFromNode(), current.getToNode()):
                for neighbor in node_to_edges.get(node.getID(), set()):
                    if neighbor.getID() not in component:
                        queue.append(neighbor)
        components.append(component)

    if len(components) <= 1:
        logger.info("Network is fully connected — no fragments to remove")
        return 0

    largest = max(components, key=len)
    edges_to_remove = set()
    for comp in components:
        if comp is not largest:
            edges_to_remove.update(comp)

    logger.info(
        f"Removing {len(edges_to_remove)} edges from {len(components) - 1} fragments "
        f"(keeping largest: {len(largest)} edges)"
    )

    cmd = [
        netconvert_path,
        "--osm-files", osm_path,
        "--output-file", str(net_path),
        "--geometry.remove", "true",
        "--roundabouts.guess", "true",
        "--ramps.guess", "true",
        "--junctions.join", "true",
        "--tls.guess", "true",
        "--tls.join", "true",
        "--edges.join", "true",
        "--no-turnarounds.tls", "true",
        "--remove-edges.by-type",
        "highway.footway,highway.pedestrian,highway.steps,highway.cycleway,highway.path",
        "--offset.disable-normalization", "true",
        "--proj.utm", "true",
        "--tls.default-type", "actuated",
        "--remove-edges.explicit", ",".join(edges_to_remove),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        logger.warning(f"netconvert re-run failed: {result.stderr}")
    else:
        logger.info(f"Network cleaned: removed {len(edges_to_remove)} disconnected edges")

    return len(edges_to_remove)


def convert_to_sumo(network_id: str) -> dict:
    """Convert cached OSM network to SUMO format using netconvert.

    The raw .osm file saved during extract_network() is fed directly to
    netconvert — no OSMnx graph re-serialization step.

    Returns:
        Dict with network_path, traffic_lights, osm_to_sumo_tl_map, sumo_junctions
    """
    if network_id not in _network_cache:
        raise KeyError(f"Network '{network_id}' not found in cache. Extract the network first.")

    SIMULATION_NETWORKS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = SIMULATION_NETWORKS_DIR / f"{network_id}.net.xml"
    cached = _network_cache[network_id]
    osm_intersections = list(cached["intersections"])

    if output_path.exists():
        logger.info(f"SUMO network already exists: {output_path}")
        tl_data = parse_sumo_traffic_lights(output_path)
        sumo_junctions, osm_to_sumo_map = _build_sumo_tl_junctions(
            output_path, tl_data["traffic_lights"], osm_intersections
        )
        _network_cache[network_id]["intersections"] = sumo_junctions
        return {
            "network_path": str(output_path),
            "traffic_lights": tl_data["traffic_lights"],
            "osm_to_sumo_tl_map": osm_to_sumo_map,
            "sumo_junctions": sumo_junctions,
        }

    osm_path = cached["osm_path"]
    if not os.path.exists(osm_path):
        raise RuntimeError(
            f"OSM source file missing: {osm_path}. Re-run extract-region to regenerate."
        )

    sumo_home = os.environ.get("SUMO_HOME", "/usr/share/sumo")
    netconvert_path = os.path.join(sumo_home, "bin", "netconvert")

    # Feed raw .osm directly to netconvert (same pipeline as geofabrik)
    cmd = [
        netconvert_path,
        "--osm-files", osm_path,
        "--output-file", str(output_path),
        "--geometry.remove", "true",
        "--roundabouts.guess", "true",
        "--ramps.guess", "true",
        "--junctions.join", "true",
        "--tls.guess", "true",
        "--tls.join", "true",
        "--edges.join", "true",
        "--no-turnarounds.tls", "true",
        "--remove-edges.by-type",
        "highway.footway,highway.pedestrian,highway.steps,highway.cycleway,highway.path",
        "--offset.disable-normalization", "true",
        "--proj.utm", "true",
        "--tls.default-type", "actuated",
    ]

    logger.info(f"Running netconvert: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.stdout:
            logger.info(f"netconvert output:\n{result.stdout}")
        if result.stderr:
            logger.warning(f"netconvert warnings:\n{result.stderr}")

        if result.returncode != 0:
            raise RuntimeError(
                f"netconvert failed with code {result.returncode}: {result.stderr}"
            )

        logger.info(f"SUMO network created: {output_path}")

        _remove_disconnected_components(output_path, netconvert_path, osm_path)

        tl_data = parse_sumo_traffic_lights(output_path)
        sumo_junctions, osm_to_sumo_map = _build_sumo_tl_junctions(
            output_path, tl_data["traffic_lights"], osm_intersections
        )
        _network_cache[network_id]["intersections"] = sumo_junctions

        return {
            "network_path": str(output_path),
            "traffic_lights": tl_data["traffic_lights"],
            "osm_to_sumo_tl_map": osm_to_sumo_map,
            "sumo_junctions": sumo_junctions,
        }

    except subprocess.TimeoutExpired:
        logger.error("netconvert timed out")
        raise RuntimeError("netconvert timed out after 5 minutes")

    except FileNotFoundError:
        logger.error("netconvert not found")
        raise RuntimeError("netconvert not found. Ensure SUMO is installed and SUMO_HOME is set")


def clear_cache() -> None:
    """Clear the in-memory network cache."""
    _network_cache.clear()
    logger.info("Network cache cleared")


def get_cached_network_ids() -> list[str]:
    """Get list of all cached network IDs."""
    return list(_network_cache.keys())


def get_all_traffic_lights() -> list[dict]:
    """Return the clustered traffic light list from disk cache."""
    if TRAFFIC_LIGHT_CLUSTERED_PATH.exists():
        with open(TRAFFIC_LIGHT_CLUSTERED_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    if TRAFFIC_LIGHT_PATH.exists():
        logger.info("Building clustered TL cache from raw TL data…")
        os.makedirs(str(CACHE_DIR), exist_ok=True)
        cluster_traffic_light_file(str(TRAFFIC_LIGHT_PATH), str(TRAFFIC_LIGHT_CLUSTERED_PATH))
        with open(TRAFFIC_LIGHT_CLUSTERED_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    logger.warning("No traffic light cache found — returning empty list")
    return []
