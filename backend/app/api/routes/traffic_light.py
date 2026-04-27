import os
import httpx
from fastapi import APIRouter, Query, status
from app.services.traffic_light_service import get_frames_from_traffic_light

router = APIRouter(prefix="/traffic_light", tags=["traffic_light"])

# Placeholder intersection that uses the digital-twin video feed
DIGITAL_TWIN_OSM_ID_LAT = 10.755388   # OSM Traffic Light 6760580985
DIGITAL_TWIN_OSM_ID_LON = 106.681386
DIGITAL_TWIN_URL = os.getenv("DIGITAL_TWIN_URL", "http://localhost:8001")
COORD_TOLERANCE = 0.001  # ~100 m


def _is_digital_twin_intersection(lat: float, lon: float) -> bool:
    """Check if the requested coords match the placeholder intersection."""
    return (
        abs(lat - DIGITAL_TWIN_OSM_ID_LAT) < COORD_TOLERANCE
        and abs(lon - DIGITAL_TWIN_OSM_ID_LON) < COORD_TOLERANCE
    )


@router.get("/frames",
    status_code=status.HTTP_200_OK,
    summary="Get camera frames for an traffic light",
    description="Retrieve camera frames for a traffic light at a given lat/lon point.",
)
async def get_frames(lat: float = Query(...), lon: float = Query(...)):

    # Special case: digital-twin placeholder intersection
    if _is_digital_twin_intersection(lat, lon):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{DIGITAL_TWIN_URL}/frame")
                resp.raise_for_status()
                data = resp.json()
                return {
                    "intersection_id": "digital_twin",
                    "roads": ["Digital Twin", "Video Feed"],
                    "frames": data.get("frames", []),
                }
        except Exception as exc:
            print(f"Digital twin frame error: {exc}")
            return {
                "intersection_id": "digital_twin",
                "roads": ["Digital Twin", "Video Feed"],
                "frames": [],
            }

    # Normal flow: camera_collector
    result = get_frames_from_traffic_light(lat=lat, lon=lon)

    if not result:
        return {
            "intersection_id": None,
            "roads": [],
            "frames": []
        }

    return result

