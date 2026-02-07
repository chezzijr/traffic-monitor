"""Map-related API routes."""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status

from app.models.schemas import (
    BoundingBox,
    ConvertToSumoResponse,
    Intersection,
    NetworkInfo,
    RouteGenerationRequest,
    RouteGenerationResponse,
    SUMOTrafficLight,
    TrafficLight,
    TrafficSignal,
)
from app.services import osm_service

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/map", tags=["map"])


@router.post(
    "/extract-region",
    response_model=NetworkInfo,
    status_code=status.HTTP_201_CREATED,
    summary="Extract road network from OSM",
    description="Extract road network from OpenStreetMap for the given bounding box.",
)
def extract_region(bbox: BoundingBox) -> NetworkInfo:
    """
    Extract road network from OpenStreetMap for the given bounding box.

    Returns network info including intersections and road count.
    """
    logger.info(f"Received extract-region request: {bbox}")
    try:
        result = osm_service.extract_network(bbox.as_tuple())
        logger.info(f"Extraction complete: {len(result['intersections'])} intersections found")
        # Convert bbox dict back to BoundingBox model
        result["bbox"] = BoundingBox(**result["bbox"])
        # Convert intersection dicts to Intersection models
        result["intersections"] = [Intersection(**i) for i in result["intersections"]]
        return NetworkInfo(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/intersections/{network_id}",
    response_model=list[Intersection],
    status_code=status.HTTP_200_OK,
    summary="Get intersections for a network",
    description="Retrieve all intersections for a previously extracted network.",
)
def get_intersections(network_id: str) -> list[Intersection]:
    """
    Get cached intersections for a given network ID.

    Returns list of intersections with their coordinates and metadata.
    """
    try:
        intersections = osm_service.get_intersections(network_id)
        return [Intersection(**i) for i in intersections]
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.post(
    "/convert-to-sumo/{network_id}",
    response_model=ConvertToSumoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Convert network to SUMO format",
    description="Convert a cached OSM network to SUMO simulation format.",
)
def convert_to_sumo(network_id: str) -> ConvertToSumoResponse:
    """
    Convert cached OSM network to SUMO format using netconvert.

    Returns path to the generated SUMO network file, traffic light data, and OSM-to-SUMO mapping.
    """
    try:
        result = osm_service.convert_to_sumo(network_id)
        # Convert traffic light dicts to SUMOTrafficLight models
        traffic_lights = [
            SUMOTrafficLight(
                id=tl["id"],
                type=tl["type"],
                program_id=tl.get("program_id", "0"),
                num_phases=len(tl.get("phases", [])),
            )
            for tl in result["traffic_lights"]
        ]
        return ConvertToSumoResponse(
            sumo_network_path=result["network_path"],
            network_id=network_id,
            traffic_lights=traffic_lights,
            osm_sumo_mapping=result["osm_to_sumo_tl_map"],
        )
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/networks",
    response_model=list[str],
    status_code=status.HTTP_200_OK,
    summary="List cached networks",
    description="Get list of all cached network IDs.",
)
def get_networks() -> list[str]:
    """
    Get list of all cached network IDs.

    Returns list of network IDs that can be used with other endpoints.
    """
    return osm_service.get_cached_network_ids()


@router.post(
    "/generate-routes/{network_id}",
    response_model=RouteGenerationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate routes for a network",
    description="Generate vehicle routes with Vietnamese traffic patterns.",
)
def generate_routes(network_id: str, request: RouteGenerationRequest) -> RouteGenerationResponse:
    """Generate routes for a SUMO network with Vietnamese traffic patterns."""
    try:
        # Get the SUMO network path
        sumo_result = osm_service.convert_to_sumo(network_id)
        network_path = sumo_result["network_path"]

        # Generate routes using route_service
        from app.services import route_service

        # Output directory for routes (same as network)
        output_dir = str(Path(network_path).parent)

        result = route_service.generate_routes(
            network_path=network_path,
            output_dir=output_dir,
            scenario=request.scenario,
            duration=request.duration,
            seed=request.seed,
        )

        return RouteGenerationResponse(**result)
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except (RuntimeError, FileNotFoundError) as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get(
    "/traffic-lights",
    response_model=list[TrafficLight],
    status_code=status.HTTP_200_OK,
    summary="Get traffic lights around a point",
    description="Retrieve OSM traffic lights within a radius of a lat/lng point.",
)
def get_traffic_lights(
    lat: float = Query(..., ge=-90, le=90, description="Latitude"),
    lng: float = Query(..., ge=-180, le=180, description="Longitude"),
    radius: int = Query(500, ge=1, le=50000, description="Search radius in meters"),
) -> list[TrafficLight]:
    """Get traffic lights from OSM around a given point."""
    lights = osm_service.get_traffic_lights_by_point(lat=lat, lon=lng, radius=radius)
    return [TrafficLight(**l) for l in lights]


@router.get(
    "/traffic-signals",
    response_model=list[TrafficSignal],
    status_code=status.HTTP_200_OK,
    summary="Get traffic signals around a point",
    description="Retrieve OSM traffic signals within a radius of a lat/lng point.",
)
def get_traffic_signals(
    lat: float = Query(..., ge=-90, le=90, description="Latitude"),
    lng: float = Query(..., ge=-180, le=180, description="Longitude"),
    radius: int = Query(500, ge=1, le=50000, description="Search radius in meters"),
) -> list[TrafficSignal]:
    """Get traffic signals from OSM around a given point."""
    signals = osm_service.get_traffic_signals_by_point(lat=lat, lon=lng, radius=radius)
    return [TrafficSignal(**s) for s in signals]
