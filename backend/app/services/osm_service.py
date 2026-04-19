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

# Distance threshold for OSM-to-SUMO coordinate matching (~200m at equator).
# Joined junction centroids can sit 40-80m from any component OSM node; bump to
# tolerate that drift when coord fallback is needed.
COORD_MATCH_THRESHOLD_DEG = 0.002

# Bump this whenever netconvert flags change to invalidate cached .net.xml.
# Written as sentinel file {network_id}.netconvert_v alongside .net.xml.
NETCONVERT_CONFIG_VERSION = 3

# Netconvert flag set shared by the primary convert and the disconnected-
# component cleanup re-run. Keeping it in one place prevents drift (seen
# historically: cleanup re-run rediscovered TLs with default threshold and
# dropped 25+ TLs that only the tuned threshold detected).
NETCONVERT_COMMON_FLAGS = [
    "--geometry.remove", "true",
    "--roundabouts.guess", "true",
    "--ramps.guess", "true",
    "--junctions.join", "true",
    "--tls.guess", "true",
    # Default threshold (69.44 m/s combined arm speed) skips HCMC urban
    # signalized junctions where per-arm speeds are 40-50 km/h. 45 m/s
    # catches them without phantom-tagging residential intersections.
    "--tls.guess.threshold", "45",
    # Honor OSM `highway=traffic_signals` placed on approach edges (common
    # Vietnamese convention; --tls.guess alone only looks at junction nodes).
    "--tls.guess-signals", "true",
    "--tls.guess-signals.dist", "40",
    "--tls.guess-signals.slack", "1",
    # Drop pass-through "TLs" that control a single straight flow.
    "--tls.discard-simple", "true",
    "--tls.join", "true",
    # Merge cross-median dual-carriageway TLs (common on HCMC boulevards like
    # CMT8). Default 20m leaves 25-32m pairs unmerged, causing asymmetric RL
    # control of the same physical intersection.
    "--tls.join-dist", "40",
    "--edges.join", "true",
    "--no-turnarounds.tls", "true",
    "--remove-edges.by-type",
    "highway.footway,highway.pedestrian,highway.steps,highway.cycleway,highway.path",
    "--offset.disable-normalization", "true",
    "--proj.utm", "true",
    "--tls.default-type", "actuated",
]

# Regex for extracting OSM node IDs embedded in SUMO joined/cluster junction IDs.
# SUMO patterns: cluster_<id>_<id>_..._#Nmore, joinedS_<id>_<id>, joinedG_<id>_<id>,
# GS_<id> (guessed signal). Bare numeric ids are also valid.
import re as _re
import fcntl as _fcntl
from contextlib import contextmanager as _contextmanager
_SUMO_ID_DIGITS_RE = _re.compile(r"\d+")


@_contextmanager
def _convert_network_lock(network_id: str):
    """Cross-process exclusive lock on a per-network sidecar file.

    FastAPI uvicorn workers and the Celery worker process share
    simulation/networks/ via a Docker volume. threading.Lock only protects one
    process; fcntl.flock on a sentinel file serializes across them.
    """
    SIMULATION_NETWORKS_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = SIMULATION_NETWORKS_DIR / f"{network_id}.convert.lock"
    fh = open(lock_path, "w")
    try:
        _fcntl.flock(fh.fileno(), _fcntl.LOCK_EX)
        yield
    finally:
        try:
            _fcntl.flock(fh.fileno(), _fcntl.LOCK_UN)
        finally:
            fh.close()


def _atomic_write_text(path: Path, content: str) -> None:
    """Write `content` to `path` via temp-file + os.replace so readers never see
    a partial write. Cleans the temp file on any failure so `.tmp` does not leak."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_text(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

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


def parse_sumo_traffic_lights(net_xml_path: Path) -> dict:
    """Parse SUMO network XML for traffic light IDs, coordinates, and phases."""
    try:
        tree = ET.parse(net_xml_path)
        root = tree.getroot()
    except ET.ParseError as e:
        logger.error(f"Failed to parse SUMO network XML: {e}")
        return {"traffic_lights": []}

    # Index every junction's coords so tlLogic → junction lookup always
    # succeeds. With --tls.join, joined TL controllers may reference junctions
    # whose type isn't literally "traffic_light"; filtering to that type left
    # such tlLogics at (0,0) and collapsed them onto the SW bbox corner.
    junction_coords: dict[str, tuple[float, float]] = {}
    for junction in root.findall(".//junction"):
        jid = junction.get("id")
        if jid:
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

        # Resolve tlLogic → (x, y). Four tiers:
        # 1. Direct junction match (plain numeric ids).
        # 2. `GS_<id>` → strip prefix → match underlying junction.
        # 3. `joinedS_A_B_..._#Nmore` / `cluster_A_B_...` — synthetic controller
        #    id with no junction counterpart. Centroid member OSM node coords.
        # 4. Nested case `joinedS_cluster_A_B_cluster_C_D` — tier 3 extracts
        #    raw numeric ids that don't match; scan junctions whose id is a
        #    substring of the tlLogic id (picks up inner `cluster_A_B`).
        xy = junction_coords.get(tl_id)
        if xy is None and tl_id.startswith("GS_"):
            xy = junction_coords.get(tl_id[3:])
        if xy is None:
            member_ids = _extract_member_osm_ids(tl_id)
            member_xys = [junction_coords[m] for m in member_ids if m in junction_coords]
            if member_xys:
                xy = (
                    sum(p[0] for p in member_xys) / len(member_xys),
                    sum(p[1] for p in member_xys) / len(member_xys),
                )
        if xy is None:
            # Only look at structured compound ids (cluster_X_Y, joinedS_X_Y).
            # Restricting the scan avoids plain numeric junction ids matching
            # as incidental substrings of longer numeric sequences (e.g.
            # junction "1234567" matching tlLogic "joinedS_12345678_...").
            substring_xys = [
                junction_coords[jid]
                for jid in junction_coords
                if (jid.startswith("cluster_") or jid.startswith("joinedS_"))
                and jid in tl_id
                and jid != tl_id
            ]
            if substring_xys:
                xy = (
                    sum(p[0] for p in substring_xys) / len(substring_xys),
                    sum(p[1] for p in substring_xys) / len(substring_xys),
                )
        if xy is None:
            logger.warning(f"No junction coord found for tlLogic {tl_id}; coord (0,0)")
            xy = (0.0, 0.0)

        phases = [
            {"duration": int(p.get("duration", 0)), "state": p.get("state", "")}
            for p in tl_logic.findall("phase")
        ]
        traffic_lights.append({"id": tl_id, "x": xy[0], "y": xy[1], "type": tl_type, "phases": phases})

    logger.info(f"Parsed {len(traffic_lights)} traffic lights from SUMO network")
    return {"traffic_lights": traffic_lights}


def _parse_sumo_boundary(net_xml_path: Path) -> tuple[float, float, float, float, float, float] | None:
    """Return (orig_west, orig_south, conv_west, conv_south, lon_scale, lat_scale) or None.

    Tuple layout is used by `sumo_xy_to_lonlat` and `_match_osm_to_sumo_traffic_lights`
    — do not reorder without updating both callers.
    """
    try:
        tree = ET.parse(net_xml_path)
        root = tree.getroot()
        location = root.find(".//location")
        if location is None:
            logger.warning("No location element in SUMO network")
            return None

        orig_parts = location.get("origBoundary", "").split(",")
        conv_parts = location.get("convBoundary", "").split(",")
        if len(orig_parts) != 4 or len(conv_parts) != 4:
            logger.warning("Invalid boundary format in SUMO network")
            return None

        orig_west, orig_south, orig_east, orig_north = map(float, orig_parts)
        conv_west, conv_south, conv_east, conv_north = map(float, conv_parts)
    except (ET.ParseError, ValueError) as e:
        logger.error(f"Failed to parse SUMO network location: {e}")
        return None

    lon_scale = (orig_east - orig_west) / (conv_east - conv_west) if conv_east != conv_west else 1.0
    lat_scale = (orig_north - orig_south) / (conv_north - conv_south) if conv_north != conv_south else 1.0
    # Stash conv origin in orig-tuple via closure: callers need both.
    return (orig_west, orig_south, conv_west, conv_south, lon_scale, lat_scale)


def sumo_xy_to_lonlat(x: float, y: float, boundary: tuple) -> tuple[float, float]:
    """Reverse-project SUMO UTM-ish x/y back to (lon, lat) via boundary scaling."""
    orig_west, orig_south, conv_west, conv_south, lon_scale, lat_scale = boundary
    lon = orig_west + (x - conv_west) * lon_scale
    lat = orig_south + (y - conv_south) * lat_scale
    return lon, lat


def _extract_member_osm_ids(sumo_id: str) -> list[str]:
    """Extract member OSM node IDs embedded in a SUMO junction/tlLogic ID.

    Filters tokens shorter than 5 digits (e.g. the `7` in `_#7more` cluster
    suffix) since real OSM node IDs are always ≥ 5 digits.

    Examples:
      '411918637'                                → ['411918637']
      'cluster_11804018784_2393618251_#7more'    → ['11804018784', '2393618251']
      'joinedS_12923547870_411926052'            → ['12923547870', '411926052']
      'GS_411918637'                             → ['411918637']
    """
    return [d for d in _SUMO_ID_DIGITS_RE.findall(sumo_id) if len(d) >= 5]


def _match_osm_to_sumo_traffic_lights(
    intersections: list[dict],
    sumo_traffic_lights: list[dict],
    net_xml_path: Path,
) -> dict[str, str]:
    """Map OSM intersection IDs → SUMO traffic light IDs.

    Strategy (in order of preference):
    1. **ID-based parse**: SUMO preserves OSM node IDs inside joined/cluster names.
       Extract every numeric token from the SUMO ID; any token present in
       `intersections` → many-to-one mapping (multiple OSM nodes back one SUMO TL).
    2. **Coord-based fallback** (only for SUMO TLs with zero ID matches, e.g.
       pure guessed signals): nearest OSM intersection within COORD_MATCH_THRESHOLD_DEG.
       No first-come-first-serve gate — each OSM intersection can back multiple
       SUMO TLs (valid for complex junctions).

    The returned map is osm_id → sumo_tl_id. Flips `has_traffic_light=True` on
    every matched intersection in place.
    """
    osm_id_set = {inter["id"] for inter in intersections}

    osm_to_sumo_map: dict[str, str] = {}
    id_matched_sumo_tls: set[str] = set()

    # Phase 1: ID-based parsing
    for sumo_tl in sumo_traffic_lights:
        tl_id = sumo_tl["id"]
        members = _extract_member_osm_ids(tl_id)
        hits = [m for m in members if m in osm_id_set]
        if hits:
            id_matched_sumo_tls.add(tl_id)
            for osm_id in hits:
                # First SUMO TL wins; later TLs overwrite only if this osm_id
                # not yet claimed. Avoids silent drops — still logs all hits.
                osm_to_sumo_map.setdefault(osm_id, tl_id)
            logger.debug(f"ID-match SUMO {tl_id} ← OSM {hits}")

    # Phase 2: Coord fallback for SUMO TLs that failed ID parse (guessed, etc.)
    unmatched = [tl for tl in sumo_traffic_lights if tl["id"] not in id_matched_sumo_tls]
    if unmatched:
        boundary = _parse_sumo_boundary(net_xml_path)
        if boundary is not None:
            orig_west, orig_south, conv_west, conv_south, lon_scale, lat_scale = boundary
            for sumo_tl in unmatched:
                approx_lon = orig_west + (sumo_tl["x"] - conv_west) * lon_scale
                approx_lat = orig_south + (sumo_tl["y"] - conv_south) * lat_scale

                best_match = None
                best_dist = float("inf")
                for inter in intersections:
                    dist = math.sqrt(
                        (inter["lat"] - approx_lat) ** 2
                        + (inter["lon"] - approx_lon) ** 2
                    )
                    if dist < best_dist:
                        best_dist = dist
                        best_match = inter

                if best_match and best_dist < COORD_MATCH_THRESHOLD_DEG:
                    osm_to_sumo_map.setdefault(best_match["id"], sumo_tl["id"])
                    logger.debug(
                        f"Coord-match SUMO {sumo_tl['id']} ← OSM {best_match['id']} "
                        f"(dist {best_dist:.6f})"
                    )

    # Flip has_traffic_light on matched intersections
    for inter in intersections:
        if inter["id"] in osm_to_sumo_map:
            inter["has_traffic_light"] = True

    matched_sumo_ids = set(osm_to_sumo_map.values())
    matched_sumo_count = len(matched_sumo_ids)
    total_sumo = len(sumo_traffic_lights)
    logger.info(
        f"Matched {len(osm_to_sumo_map)} OSM intersections to "
        f"{matched_sumo_count}/{total_sumo} SUMO traffic lights "
        f"(id-phase {len(id_matched_sumo_tls)}, coord-phase {matched_sumo_count - len(id_matched_sumo_tls)})"
    )
    if matched_sumo_count < total_sumo:
        dropped = [tl["id"] for tl in sumo_traffic_lights if tl["id"] not in matched_sumo_ids]
        logger.warning(
            f"{len(dropped)} SUMO TL(s) unmapped to OSM nodes "
            f"(will still appear in junction list via coord reverse-projection): "
            f"{dropped[:10]}{'…' if len(dropped) > 10 else ''}"
        )
    return osm_to_sumo_map


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
        *NETCONVERT_COMMON_FLAGS,
        "--remove-edges.explicit", ",".join(edges_to_remove),
    ]
    # Netconvert overwrites net_path in-place. If it crashes mid-write, the
    # multi-component original is gone and we're left with a truncated file.
    # Back it up so we can restore the already-valid multi-component network.
    backup_path = net_path.with_suffix(net_path.suffix + ".bak")
    try:
        import shutil
        shutil.copy2(net_path, backup_path)
    except OSError as err:
        logger.warning(f"Could not back up {net_path} before cleanup: {err}")
        backup_path = None  # type: ignore[assignment]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (subprocess.TimeoutExpired, OSError) as err:
        logger.error(f"netconvert disconnected-cleanup crashed: {err}")
        if backup_path and backup_path.exists():
            os.replace(backup_path, net_path)
            logger.info(f"Restored {net_path} from backup")
        return -1

    if result.returncode != 0:
        logger.error(f"netconvert disconnected-cleanup failed: {result.stderr}")
        if backup_path and backup_path.exists():
            os.replace(backup_path, net_path)
            logger.info(f"Restored {net_path} from backup")
        return -1

    # Success: drop backup.
    if backup_path and backup_path.exists():
        try:
            backup_path.unlink()
        except OSError:
            pass
    logger.info(f"Network cleaned: removed {len(edges_to_remove)} disconnected edges")
    return len(edges_to_remove)


def convert_to_sumo(network_id: str) -> dict:
    """Convert cached OSM network to SUMO format using netconvert.

    Serializes concurrent callers per network_id so netconvert never writes the
    same .net.xml twice in parallel. The raw .osm file saved during
    extract_network() is fed directly to netconvert — no OSMnx graph
    re-serialization step.

    Returns:
        Dict with network_path, traffic_lights, osm_to_sumo_tl_map
    """
    if network_id not in _network_cache:
        raise KeyError(f"Network '{network_id}' not found in cache. Extract the network first.")

    with _convert_network_lock(network_id):
        return _convert_to_sumo_locked(network_id)


def _convert_to_sumo_locked(network_id: str) -> dict:
    SIMULATION_NETWORKS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = SIMULATION_NETWORKS_DIR / f"{network_id}.net.xml"
    version_path = SIMULATION_NETWORKS_DIR / f"{network_id}.netconvert_v"
    cached = _network_cache[network_id]

    def _cached_version_matches() -> bool:
        if not version_path.exists():
            return False
        try:
            return version_path.read_text().strip() == str(NETCONVERT_CONFIG_VERSION)
        except OSError as err:
            logger.warning(f"Unreadable netconvert version sentinel {version_path}: {err}")
            return False

    if output_path.exists() and _cached_version_matches():
        logger.info(f"SUMO network already exists (v{NETCONVERT_CONFIG_VERSION}): {output_path}")
        try:
            tl_data = parse_sumo_traffic_lights(output_path)
        except (ET.ParseError, OSError) as err:
            logger.warning(f"Cached .net.xml unreadable ({err}); falling through to rebuild")
        else:
            osm_to_sumo_map = _match_osm_to_sumo_traffic_lights(
                cached["intersections"], tl_data["traffic_lights"], output_path
            )
            return {
                "network_path": str(output_path),
                "traffic_lights": tl_data["traffic_lights"],
                "osm_to_sumo_tl_map": osm_to_sumo_map,
            }

    if output_path.exists():
        logger.info(
            f"Rebuilding .net.xml for {network_id}: netconvert config version "
            f"changed (on-disk → {NETCONVERT_CONFIG_VERSION})"
        )
        # Route files reference edges from the previous .net.xml; edge IDs can
        # change when netconvert flags change, which makes cached routes stale
        # (SUMO errors "edge 'X' is not known"). Drop them so route_service
        # regenerates on next training run.
        # Glob is anchored with an explicit separator to avoid matching a
        # different network whose id happens to share the 16-hex prefix.
        stale_routes = (
            list(SIMULATION_NETWORKS_DIR.glob(f"{network_id}_*.rou.xml"))
            + list(SIMULATION_NETWORKS_DIR.glob(f"{network_id}.rou.xml"))
            + list(SIMULATION_NETWORKS_DIR.glob(f"{network_id}_*.rou.alt.xml"))
            + list(SIMULATION_NETWORKS_DIR.glob(f"{network_id}.rou.alt.xml"))
            + list(SIMULATION_NETWORKS_DIR.glob(f"{network_id}_*.trips.xml"))
            + list(SIMULATION_NETWORKS_DIR.glob(f"{network_id}.trips.xml"))
        )
        for p in stale_routes:
            try:
                p.unlink()
            except OSError as err:
                logger.warning(f"Failed to remove stale route file {p}: {err}")
        if stale_routes:
            logger.info(f"Dropped {len(stale_routes)} stale route/trips files for {network_id}")

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
        *NETCONVERT_COMMON_FLAGS,
    ]

    logger.info(f"Running netconvert: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.stdout:
            logger.info(f"netconvert output:\n{result.stdout}")
        if result.stderr:
            logger.warning(f"netconvert warnings:\n{result.stderr}")

        if result.returncode != 0:
            # Drop any partial output so the next call rebuilds fresh.
            output_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"netconvert failed with code {result.returncode}: {result.stderr}"
            )

        logger.info(f"SUMO network created: {output_path}")

        cleanup_result = _remove_disconnected_components(output_path, netconvert_path, osm_path)

        # Parse + match first; only stamp the sentinel once we've confirmed the
        # new network is actually usable. A crash between netconvert success
        # and sentinel write would otherwise leave a stale .net.xml that the
        # next call treats as fresh.
        tl_data = parse_sumo_traffic_lights(output_path)
        osm_to_sumo_map = _match_osm_to_sumo_traffic_lights(
            cached["intersections"], tl_data["traffic_lights"], output_path
        )

        if cleanup_result >= 0:
            try:
                _atomic_write_text(version_path, str(NETCONVERT_CONFIG_VERSION))
            except OSError as err:
                logger.warning(f"Failed to write netconvert version sentinel: {err}")
        else:
            logger.warning(
                "Skipping netconvert version sentinel; disconnected-cleanup failed — "
                "next call will rebuild."
            )

        return {
            "network_path": str(output_path),
            "traffic_lights": tl_data["traffic_lights"],
            "osm_to_sumo_tl_map": osm_to_sumo_map,
        }

    except subprocess.TimeoutExpired:
        logger.error("netconvert timed out")
        # Netconvert may have left a truncated .net.xml. Remove it so the next
        # call rebuilds from scratch instead of serving corrupted output.
        output_path.unlink(missing_ok=True)
        raise RuntimeError("netconvert timed out after 5 minutes")

    except FileNotFoundError:
        logger.error("netconvert not found")
        output_path.unlink(missing_ok=True)
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
