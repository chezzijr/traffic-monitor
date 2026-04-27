"""Regression tests for traffic-light cluster detection."""

from pathlib import Path

import pytest

from app.services.graph_service import build_tl_clusters
from app.services.sumo_graph_utils import (
    canonical_tl,
    is_tl_junction,
    parse_network,
    strip_gs,
    tl_neighbors_by_hop,
)

NET_PATH = Path(__file__).resolve().parents[2] / "simulation" / "networks" / "1dd22cc5fc1a3e39.net.xml"

# The 8-TL grid the user confirmed visually adjacent (Trương Định / Võ Văn Tần, HCMC).
GRID_8 = {
    "411925453",
    "GS_411925919",
    "GS_411925922",
    "411925335",
    "411926451",
    "GS_411926667",
    "GS_411926609",
    "411925869",
}


@pytest.mark.skipif(not NET_PATH.exists(), reason="test network not present")
def test_8_tl_grid_forms_single_cluster():
    components = build_tl_clusters(str(NET_PATH))
    target_cluster = next((set(c) for c in components if GRID_8 & set(c)), None)
    assert target_cluster is not None, "Target TLs not found in any cluster"
    missing = GRID_8 - target_cluster
    assert not missing, f"Missing from cluster: {missing}"
    # With max_hops=2, max_distance=500m the 8 TLs should be exactly the cluster
    assert len(target_cluster) == 8, f"Expected 8, got {len(target_cluster)}: {sorted(target_cluster)}"


@pytest.mark.skipif(not NET_PATH.exists(), reason="test network not present")
def test_strip_gs_and_canonical():
    tl_ids, _, _ = parse_network(str(NET_PATH))
    for t in GRID_8:
        if t.startswith("GS_"):
            assert strip_gs(t) == t[3:]
            # Canonical lookup from geometric form returns prefixed form
            assert canonical_tl(t[3:], tl_ids) == t
        else:
            assert strip_gs(t) == t


@pytest.mark.skipif(not NET_PATH.exists(), reason="test network not present")
def test_is_tl_junction_recognizes_gs_alias():
    tl_ids, _, _ = parse_network(str(NET_PATH))
    # Geometric form without prefix
    assert is_tl_junction("411925919", tl_ids), "GS_411925919 geometric form not recognized"
    # Prefixed form
    assert is_tl_junction("GS_411925919", tl_ids)
    # Non-TL junction
    assert not is_tl_junction("nonexistent_junction", tl_ids)


@pytest.mark.skipif(not NET_PATH.exists(), reason="test network not present")
def test_hop_traversal_finds_neighbors_through_non_tl_junctions():
    tl_ids, junction_adj, _ = parse_network(str(NET_PATH))
    # 411925335 should reach at least 2 other target TLs through non-TL hops
    nbrs = tl_neighbors_by_hop("411925335", tl_ids, junction_adj, max_hops=2)
    in_target = nbrs & GRID_8
    assert len(in_target) >= 2, f"Expected ≥2 target neighbors, got {in_target}"


@pytest.mark.skipif(not NET_PATH.exists(), reason="test network not present")
def test_hop2_recovers_strictly_more_than_hop1():
    """Regression: hop-2 traversal finds edges that hop-1 (direct) misses on
    real OSM networks with non-TL priority junctions between signaled intersections.
    """
    hop1 = build_tl_clusters(str(NET_PATH), max_hops=0)
    hop2 = build_tl_clusters(str(NET_PATH), max_hops=2)
    # Find the component containing GRID_8 in each
    h1_cluster = next((set(c) for c in hop1 if GRID_8 & set(c)), set())
    h2_cluster = next((set(c) for c in hop2 if GRID_8 & set(c)), set())
    assert len(h2_cluster & GRID_8) >= len(h1_cluster & GRID_8), (
        f"hop-2 cluster ({len(h2_cluster & GRID_8)} targets) regressed vs hop-0 "
        f"({len(h1_cluster & GRID_8)} targets)"
    )
    assert len(h2_cluster & GRID_8) == 8, "hop-2 should recover the full 8-TL grid"
