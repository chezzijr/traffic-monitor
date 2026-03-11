"""Network management API routes."""

from fastapi import APIRouter, HTTPException, status

from app.services import network_service

router = APIRouter(prefix="/networks", tags=["networks"])


@router.get("/")
def list_networks():
    """List all persisted networks."""
    return network_service.list_networks()


@router.get("/{network_id}")
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
