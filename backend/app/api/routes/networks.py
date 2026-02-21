"""Network persistence API routes."""

import logging

from fastapi import APIRouter, HTTPException, status

from app.models.schemas import NetworkMetadata
import app.services.network_service as network_service

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/networks", tags=["networks"])


@router.get(
    "",
    response_model=list[NetworkMetadata],
    status_code=status.HTTP_200_OK,
    summary="List all persisted networks",
    description="Scan simulation/networks/ for .meta.json files and return metadata sorted by created_at desc.",
)
def list_networks() -> list[NetworkMetadata]:
    """Return all persisted network metadata sorted by creation date descending."""
    networks = network_service.list_networks()
    return [NetworkMetadata(**n) for n in networks]


@router.get(
    "/{network_id}",
    response_model=NetworkMetadata,
    status_code=status.HTTP_200_OK,
    summary="Get network metadata",
    description="Load metadata for a single network by ID.",
)
def get_network(network_id: str) -> NetworkMetadata:
    """Load and return metadata for a single network."""
    metadata = network_service.load_network_metadata(network_id)
    if metadata is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Network '{network_id}' not found.",
        )
    return NetworkMetadata(**metadata)


@router.delete(
    "/{network_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a network and its files",
    description="Delete .net.xml, .meta.json, and route files for the given network.",
)
def delete_network(network_id: str) -> dict:
    """Delete all files associated with a network."""
    files_removed = network_service.delete_network(network_id)
    if files_removed == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Network '{network_id}' not found or has no files.",
        )
    return {"status": "deleted", "files_removed": files_removed}


@router.post(
    "/{network_id}/load",
    response_model=NetworkMetadata,
    status_code=status.HTTP_200_OK,
    summary="Restore network to in-memory cache",
    description="Read .meta.json and populate the in-memory network cache for subsequent operations.",
)
def load_network(network_id: str) -> NetworkMetadata:
    """Restore network metadata into the in-memory cache."""
    metadata = network_service.restore_network_to_cache(network_id)
    if metadata is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Network '{network_id}' metadata not found.",
        )
    return NetworkMetadata(**metadata)
