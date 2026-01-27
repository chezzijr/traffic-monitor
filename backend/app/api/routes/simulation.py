"""Simulation-related API routes."""

from fastapi import APIRouter, HTTPException, status

from app.models.schemas import (
    SimulationStartRequest,
    SimulationStatus,
    SimulationStepMetrics,
)
from app.services import osm_service, sumo_service

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.post(
    "/start",
    response_model=SimulationStatus,
    status_code=status.HTTP_200_OK,
    summary="Start simulation",
    description="Start a SUMO simulation for the given network.",
)
def start_simulation(request: SimulationStartRequest) -> SimulationStatus:
    """
    Start a SUMO simulation for the given network.

    The network must have been previously extracted and converted to SUMO format.
    """
    try:
        # Get the SUMO network path from osm_service
        network_path = osm_service.convert_to_sumo(request.network_id)

        # Start the simulation
        result = sumo_service.start_simulation(
            network_path=str(network_path),
            network_id=request.network_id,
            gui=request.gui,
        )

        return SimulationStatus(
            status=result["status"],
            step=result["step"],
            network_id=result["network_id"],
        )
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/step",
    response_model=SimulationStepMetrics,
    status_code=status.HTTP_200_OK,
    summary="Advance simulation by one step",
    description="Advance the simulation by one step and return metrics.",
)
def step_simulation() -> SimulationStepMetrics:
    """
    Advance the simulation by one step.

    Returns metrics including vehicle count and wait times.
    """
    try:
        result = sumo_service.step()
        return SimulationStepMetrics(
            step=result["step"],
            total_vehicles=result["total_vehicles"],
            total_wait_time=result["total_wait_time"],
            average_wait_time=result["average_wait_time"],
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/pause",
    response_model=SimulationStatus,
    status_code=status.HTTP_200_OK,
    summary="Pause simulation",
    description="Pause the currently running simulation.",
)
def pause_simulation() -> SimulationStatus:
    """
    Pause the currently running simulation.

    The simulation can be resumed later with the /resume endpoint.
    """
    try:
        result = sumo_service.pause_simulation()
        status_info = sumo_service.get_status()
        return SimulationStatus(
            status=result["status"],
            step=result["step"],
            network_id=status_info.get("network_id"),
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/resume",
    response_model=SimulationStatus,
    status_code=status.HTTP_200_OK,
    summary="Resume simulation",
    description="Resume a paused simulation.",
)
def resume_simulation() -> SimulationStatus:
    """
    Resume a paused simulation.

    The simulation must have been previously paused.
    """
    try:
        result = sumo_service.resume_simulation()
        status_info = sumo_service.get_status()
        return SimulationStatus(
            status=result["status"],
            step=result["step"],
            network_id=status_info.get("network_id"),
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/stop",
    response_model=SimulationStatus,
    status_code=status.HTTP_200_OK,
    summary="Stop simulation",
    description="Stop and cleanup the current simulation.",
)
def stop_simulation() -> SimulationStatus:
    """
    Stop and cleanup the current simulation.

    Returns the final status including the step count when stopped.
    """
    result = sumo_service.stop_simulation()
    return SimulationStatus(
        status=result["status"],
        step=result["final_step"],
        network_id=None,
    )


@router.get(
    "/status",
    response_model=SimulationStatus,
    status_code=status.HTTP_200_OK,
    summary="Get simulation status",
    description="Get the current status of the simulation.",
)
def get_simulation_status() -> SimulationStatus:
    """
    Get the current status of the simulation.

    Returns status (idle, running, paused), current step, and network ID.
    """
    result = sumo_service.get_status()
    return SimulationStatus(
        status=result["status"],
        step=result["step"],
        network_id=result.get("network_id"),
    )
