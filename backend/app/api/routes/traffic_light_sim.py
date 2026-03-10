"""API route for the mockup traffic light simulation."""

from fastapi import APIRouter, Query, status

from app.services.traffic_light_sim_service import get_state

router = APIRouter(prefix="/traffic_light_sim", tags=["traffic_light_sim"])


@router.get(
    "/state",
    status_code=status.HTTP_200_OK,
    summary="Get simulated traffic light state",
    description=(
        "Return the current simulated traffic-light phase and countdown "
        "for each direction (N/S/E/W) at the given intersection."
    ),
)
def get_traffic_light_state(intersection_id: str = Query(...)):
    return get_state(intersection_id)
