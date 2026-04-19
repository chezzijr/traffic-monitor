"""Map-related API routes."""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from app.models.schemas import (
    BoundingBox,
    ConvertToSumoResponse,
    Intersection,
    NetworkInfo,
    RouteGenerationRequest,
    RouteGenerationResponse,
    SUMOTrafficLight,
)
from app.services import network_service, osm_service

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
        # Save network metadata with junction data (one entry per SUMO TL).
        # Narrowed to expected failure modes; unexpected errors bubble up so
        # the client doesn't see 201 Created while metadata silently fails.
        try:
            intersections = osm_service.get_intersections(network_id)
            bbox_tuple = osm_service.get_network_bbox(network_id)
            osm_sumo_map: dict[str, str] = result["osm_to_sumo_tl_map"]
            sumo_tls = result["traffic_lights"]

            # Invert osm→sumo map to sumo→[osm ids] so each tl_id picks a
            # canonical representative OSM intersection for its coord.
            sumo_to_osm_ids: dict[str, list[str]] = {}
            for osm_id, tl_id in osm_sumo_map.items():
                sumo_to_osm_ids.setdefault(tl_id, []).append(osm_id)
            osm_by_id = {inter["id"]: inter for inter in intersections}

            # Reverse-projection boundary for SUMO TLs with no OSM match.
            boundary = osm_service._parse_sumo_boundary(Path(result["network_path"]))

            junctions = []
            seen_tl_ids: set[str] = set()
            skipped_no_coord: list[str] = []
            for sumo_tl in sumo_tls:
                tl_id = sumo_tl["id"]
                if tl_id in seen_tl_ids:
                    continue
                seen_tl_ids.add(tl_id)

                osm_ids = sumo_to_osm_ids.get(tl_id, [])
                # Resolve canonical OSM intersection defensively: the mapping
                # could reference an osm_id not in `intersections` if the
                # in-memory cache was rebuilt between match and save.
                canonical = None
                for oid in osm_ids:
                    canonical = osm_by_id.get(oid)
                    if canonical is not None:
                        break

                if canonical is not None:
                    lat, lon, junction_id = canonical["lat"], canonical["lon"], canonical["id"]
                elif boundary is not None:
                    lon, lat = osm_service.sumo_xy_to_lonlat(
                        sumo_tl.get("x", 0.0), sumo_tl.get("y", 0.0), boundary
                    )
                    junction_id = tl_id
                else:
                    skipped_no_coord.append(tl_id)
                    continue

                junctions.append({
                    "id": junction_id,
                    "lat": lat,
                    "lon": lon,
                    "tl_id": tl_id,
                })

            if skipped_no_coord:
                logger.error(
                    f"Dropped {len(skipped_no_coord)} SUMO TL(s) from metadata "
                    f"(no OSM match and boundary unavailable): "
                    f"{skipped_no_coord[:10]}{'…' if len(skipped_no_coord) > 10 else ''}"
                )

            if bbox_tuple:
                s, w, n, e = bbox_tuple
                network_service.save_metadata(
                    network_id=network_id,
                    bbox={"south": s, "west": w, "north": n, "east": e},
                    intersection_count=len(intersections),
                    traffic_light_count=len(junctions),
                    junctions=junctions,
                    road_count=len(intersections),
                )
        except (KeyError, OSError) as e:
            logger.warning(f"Failed to save network metadata for {network_id}: {e}", exc_info=True)

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


