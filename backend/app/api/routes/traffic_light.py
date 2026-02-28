from fastapi import APIRouter, Query, status
from app.services.traffic_light_service import get_frames_from_traffic_light

router = APIRouter(prefix="/traffic_light", tags=["traffic_light"])


@router.get("/frames",
    status_code=status.HTTP_200_OK,
    summary="Get camera frames for an traffic light",
    description="Retrieve camera frames for a traffic light at a given lat/lon point.",
)
def get_frames(lat: float = Query(...), lon: float = Query(...)):

    result = get_frames_from_traffic_light(lat=lat, lon=lon)

    if not result:
        return {
            "intersection_id": None,
            "roads": [],
            "frames": []
        }

    return result
