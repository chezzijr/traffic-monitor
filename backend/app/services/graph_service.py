"""TL graph analysis — connected components of the TL-to-TL adjacency graph."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict, deque


def build_tl_clusters(network_path: str) -> list[list[str]]:
    """Return connected components of the TL-to-TL graph for a SUMO network.

    Edge = non-internal SUMO edge whose `from` and `to` junctions both have a
    `<tlLogic>` entry. Components returned sorted by size descending. Isolated
    TLs (no TL neighbors) are returned as size-1 components.
    """
    tree = ET.parse(network_path)
    root = tree.getroot()

    tls: set[str] = {tl.get("id", "") for tl in root.findall("tlLogic")}
    tls.discard("")

    neighbors: dict[str, set[str]] = defaultdict(set)
    for edge in root.findall("edge"):
        if edge.get("function") == "internal":
            continue
        frm = edge.get("from")
        to = edge.get("to")
        if frm in tls and to in tls and frm != to:
            neighbors[frm].add(to)
            neighbors[to].add(frm)

    visited: set[str] = set()
    components: list[list[str]] = []
    for tl_id in tls:
        if tl_id in visited:
            continue
        component: list[str] = []
        queue: deque[str] = deque([tl_id])
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            component.append(node)
            for nb in neighbors.get(node, ()):
                if nb not in visited:
                    queue.append(nb)
        components.append(sorted(component))

    components.sort(key=len, reverse=True)
    return components
