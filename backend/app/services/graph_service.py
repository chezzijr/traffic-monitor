"""TL graph analysis — connected components of the TL-to-TL adjacency graph.

The TL adjacency used here is tolerant of SUMO's real-world quirks:

* GS_ (joined signal group) alias: <tlLogic> uses 'GS_X' while <edge> references
  the geometric junction 'X'. We canonicalize both to the same TL.
* Non-TL gap junctions: real-world OSM networks frequently interpose unsignaled
  priority junctions between adjacent traffic lights. We traverse through them
  up to max_hops to recover the logical adjacency a human would draw.
"""

from __future__ import annotations

from app.services.sumo_graph_utils import (
    parse_network,
    strip_gs,
    tl_neighbors_by_hop,
)


def build_tl_clusters(
    network_path: str,
    max_hops: int = 2,
    max_distance_m: float = 500.0,
) -> list[list[str]]:
    """Return connected components of the TL-to-TL graph for a SUMO network.

    Two TLs are considered adjacent iff they are reachable from each other by
    a path of at most `max_hops` non-TL junctions AND their geometric junctions
    are within `max_distance_m` straight-line meters. The distance cap prevents
    transit highways from chaining through many gap junctions and merging
    otherwise-unrelated neighborhoods.

    Returns components sorted by size descending. Isolated TLs appear as
    size-1 components.
    """
    tl_ids, junction_adj, junction_coords = parse_network(network_path)

    neighbors: dict[str, set[str]] = {tl: set() for tl in tl_ids}
    for tl in tl_ids:
        reachable = tl_neighbors_by_hop(tl, tl_ids, junction_adj, max_hops=max_hops)
        src_geom = strip_gs(tl)
        sc = junction_coords.get(src_geom)
        for nb in reachable:
            if sc is not None:
                nb_geom = strip_gs(nb)
                nc = junction_coords.get(nb_geom)
                if nc is not None:
                    dx = sc[0] - nc[0]
                    dy = sc[1] - nc[1]
                    if (dx * dx + dy * dy) > (max_distance_m * max_distance_m):
                        continue
            neighbors.setdefault(tl, set()).add(nb)
            neighbors.setdefault(nb, set()).add(tl)

    visited: set[str] = set()
    components: list[list[str]] = []
    for tl in tl_ids:
        if tl in visited:
            continue
        stack = [tl]
        component: list[str] = []
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            component.append(node)
            for nb in neighbors.get(node, ()):
                if nb not in visited:
                    stack.append(nb)
        components.append(sorted(component))

    components.sort(key=len, reverse=True)
    return components
