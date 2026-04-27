"""Network management API routes."""

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.models.schemas import NetworkMetadata
from app.services import graph_service, network_service

router = APIRouter(prefix="/networks", tags=["networks"])


@router.get("/")
def list_networks():
    """List all persisted networks."""
    return network_service.list_networks()


@router.get("/{network_id}", response_model=NetworkMetadata)
def get_network(network_id: str):
    """Get network metadata."""
    metadata = network_service.load_metadata(network_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail=f"Network not found: {network_id}")
    return metadata


@router.delete("/{network_id}")
def delete_network(network_id: str):
    """Delete a network and its files."""
    try:
        return network_service.delete_network(network_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Network not found: {network_id}")


@router.get("/{network_id}/tl-clusters")
def get_tl_clusters(network_id: str):
    """Return connected components of the TL-to-TL graph.

    Each cluster is a set of TLs reachable from each other via direct SUMO
    edges. Users should select a whole cluster for CoLight training so the
    graph-attention layer has meaningful neighbors to aggregate.
    """
    metadata = network_service.load_metadata(network_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail=f"Network not found: {network_id}")
    net_path = settings.simulation_networks_dir / f"{network_id}.net.xml"
    if not net_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Network .net.xml missing — run convert-to-sumo first",
        )
    components = graph_service.build_tl_clusters(str(net_path))
    return [
        {"cluster_id": f"c{i}", "size": len(tl_ids), "tl_ids": tl_ids}
        for i, tl_ids in enumerate(components)
    ]
