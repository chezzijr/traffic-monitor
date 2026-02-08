"""Traffic light control API routes."""

from fastapi import APIRouter, HTTPException, status

from app.models.schemas import SetPhaseRequest, TrafficLightInfo
from app.services import sumo_service, deployment_service

router = APIRouter(prefix="/control", tags=["control"])


@router.get(
    "/traffic-lights",
    response_model=list[TrafficLightInfo],
    status_code=status.HTTP_200_OK,
    summary="Get all traffic lights",
    description="Get all traffic lights and their current states.",
)
def get_traffic_lights() -> list[TrafficLightInfo]:
    """
    Get all traffic lights and their current states.

    Returns a list of traffic light information including ID, phase, and program.
    Returns empty list if no simulation is running.
    """
    result = sumo_service.get_traffic_lights()
    return [
        TrafficLightInfo(id=tl["id"], phase=tl["phase"], program=tl["program"])
        for tl in result
    ]


@router.get(
    "/traffic-lights/{tl_id}",
    response_model=TrafficLightInfo,
    status_code=status.HTTP_200_OK,
    summary="Get a specific traffic light",
    description="Get a specific traffic light by ID.",
)
def get_traffic_light(tl_id: str) -> TrafficLightInfo:
    """
    Get a specific traffic light by ID.

    Returns the traffic light information including ID, phase, and program.
    """
    try:
        result = sumo_service.get_traffic_light(tl_id)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Traffic light '{tl_id}' not found",
            )
        return TrafficLightInfo(
            id=result["id"], phase=result["phase"], program=result["program"]
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/traffic-lights/{tl_id}/phase",
    response_model=TrafficLightInfo,
    status_code=status.HTTP_200_OK,
    summary="Set traffic light phase",
    description="Set a traffic light to a specific phase.",
)
def set_traffic_light_phase(tl_id: str, request: SetPhaseRequest) -> TrafficLightInfo:
    """
    Set a traffic light to a specific phase.

    Returns the updated traffic light state after setting the phase.
    """
    # Check if TL is under AI control
    if deployment_service.is_ai_controlling(tl_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "AI_CONTROL_ACTIVE",
                "message": f"Traffic light '{tl_id}' is under AI control. Disable AI control first.",
            },
        )

    try:
        sumo_service.set_traffic_light_phase(tl_id, request.phase)
        # Get full traffic light info after setting phase
        tl_info = sumo_service.get_traffic_light(tl_id)
        if tl_info is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Traffic light '{tl_id}' not found",
            )
        return TrafficLightInfo(
            id=tl_info["id"], phase=tl_info["phase"], program=tl_info["program"]
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
