"""Shared helpers for SUMO road-network graph analysis.

Consolidates GS_ alias stripping, TL canonicalization, and multi-hop
adjacency traversal used by both cluster detection (graph_service) and
CoLight training graph construction (colight_env).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict, deque


def strip_gs(node_id: str) -> str:
    """Strip the 'GS_' (joined signal group) prefix if present."""
    return node_id[3:] if node_id.startswith("GS_") else node_id


def parse_network(network_path: str) -> tuple[set[str], dict[str, set[str]], dict[str, tuple[float, float]]]:
    """Parse a SUMO .net.xml and return (canonical_tl_ids, junction_adj, junction_coords).

    canonical_tl_ids: set of canonical TL identifiers (as they appear in <tlLogic>,
        e.g. both '411925335' and 'GS_411925919'). Consumers match against this set.
    junction_adj: undirected adjacency map keyed by SUMO junction id (NOT canonical —
        edges reference the geometric junction, which is the stripped form).
    junction_coords: (x, y) in SUMO meters per non-internal junction.
    """
    tree = ET.parse(network_path)
    root = tree.getroot()

    tl_ids: set[str] = {tl.get("id", "") for tl in root.findall("tlLogic")}
    tl_ids.discard("")

    junction_coords: dict[str, tuple[float, float]] = {}
    for j in root.findall("junction"):
        if j.get("type") == "internal":
            continue
        jid = j.get("id")
        if not jid:
            continue
        try:
            junction_coords[jid] = (float(j.get("x", "0")), float(j.get("y", "0")))
        except (TypeError, ValueError):
            pass

    junction_adj: dict[str, set[str]] = defaultdict(set)
    for edge in root.findall("edge"):
        if edge.get("function") == "internal":
            continue
        frm = edge.get("from")
        to = edge.get("to")
        if not frm or not to or frm == to:
            continue
        junction_adj[frm].add(to)
        junction_adj[to].add(frm)

    return tl_ids, dict(junction_adj), junction_coords


def is_tl_junction(junction_id: str, tl_ids: set[str]) -> bool:
    """Check whether a SUMO junction id corresponds to a traffic light.

    Since <edge> references reference the stripped (geometric) id, a junction
    'X' is a TL iff either 'X' or 'GS_X' appears in tlLogic.
    """
    return junction_id in tl_ids or f"GS_{junction_id}" in tl_ids


def canonical_tl(junction_id: str, tl_ids: set[str]) -> str:
    """Map a geometric junction id back to its canonical TL id (prefers GS_ form)."""
    if f"GS_{junction_id}" in tl_ids:
        return f"GS_{junction_id}"
    return junction_id


def tl_neighbors_by_hop(
    start_tl: str,
    tl_ids: set[str],
    junction_adj: dict[str, set[str]],
    max_hops: int = 5,
) -> set[str]:
    """BFS from a TL through NON-TL junctions; return all TLs reached within max_hops.

    Hop count increments per non-TL junction traversed. Traversal stops at the
    first TL hit — we don't recurse past other TLs because their neighborhoods
    are computed from their own BFS runs.

    Args:
        start_tl: canonical TL id (as in <tlLogic>, e.g. '411925335' or 'GS_411925919')
        tl_ids: canonical TL id set from parse_network
        junction_adj: junction adjacency from parse_network (keyed by geometric id)
        max_hops: maximum number of non-TL intermediate junctions between TLs

    Returns:
        Set of canonical TL ids reachable from start_tl. Excludes start_tl itself.
    """
    start_geom = strip_gs(start_tl)
    if start_geom not in junction_adj:
        return set()

    seen: set[str] = {start_geom}
    # (geometric_id, hops_so_far) — hops counts non-TL intermediates
    frontier: deque[tuple[str, int]] = deque([(start_geom, 0)])
    neighbors: set[str] = set()

    while frontier:
        node, hops = frontier.popleft()
        for nb in junction_adj.get(node, ()):
            if nb in seen:
                continue
            seen.add(nb)
            if is_tl_junction(nb, tl_ids) and nb != start_geom:
                canonical_nb = canonical_tl(nb, tl_ids)
                if canonical_nb != start_tl:
                    neighbors.add(canonical_nb)
                continue
            if hops + 1 <= max_hops:
                frontier.append((nb, hops + 1))
    return neighbors
