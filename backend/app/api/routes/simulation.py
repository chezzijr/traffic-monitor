"""Simulation-related API routes."""

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.models.schemas import (
    SimulationStartRequest,
    SimulationStatus,
    SimulationStepMetrics,
)
from app.services import osm_service, sumo_service, metrics_service

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
        # Clear metrics from any previous simulation
        metrics_service.clear_metrics()

        # Get the SUMO network path from osm_service
        sumo_result = osm_service.convert_to_sumo(request.network_id)

        # Start the simulation
        result = sumo_service.start_simulation(
            network_path=sumo_result["network_path"],
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
        # TODO: Implement throughput tracking from SUMO departed vehicles
        metrics_service.record_metrics(
            step=result["step"],
            total_vehicles=result["total_vehicles"],
            total_wait_time=result["total_wait_time"],
            average_wait_time=result["average_wait_time"],
            throughput=0,
        )
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


async def _simulation_event_generator(step_interval: int):
    """Async generator that yields SSE events for simulation streaming.

    Args:
        step_interval: Interval between steps in milliseconds.

    Yields:
        SSE-formatted event strings.
    """
    final_step = 0
    try:
        while sumo_service.get_is_running():
            if sumo_service.get_is_paused():
                # Simulation is paused, yield heartbeat
                yield f"event: heartbeat\ndata: {{}}\n\n"
            else:
                # Simulation is running, perform step
                try:
                    result = await sumo_service.step_async()
                    final_step = result["step"]

                    # Record metrics (same as /step endpoint)
                    metrics_service.record_metrics(
                        step=result["step"],
                        total_vehicles=result["total_vehicles"],
                        total_wait_time=result["total_wait_time"],
                        average_wait_time=result["average_wait_time"],
                        throughput=0,
                    )

                    # Yield step event
                    step_data = {
                        "step": result["step"],
                        "total_vehicles": result["total_vehicles"],
                        "total_wait_time": result["total_wait_time"],
                        "average_wait_time": result["average_wait_time"],
                    }
                    yield f"event: step\ndata: {json.dumps(step_data)}\n\n"
                except RuntimeError:
                    # Simulation may have ended or encountered an error
                    break

            # Sleep for the configured interval
            await asyncio.sleep(step_interval / 1000.0)

    except Exception as e:
        # Yield error event on unexpected exception
        error_data = {"message": str(e) or "Simulation ended unexpectedly"}
        yield f"event: error\ndata: {json.dumps(error_data)}\n\n"
        return

    # Simulation stopped normally
    stopped_data = {"final_step": final_step}
    yield f"event: stopped\ndata: {json.dumps(stopped_data)}\n\n"


@router.get(
    "/stream",
    summary="Stream simulation events via SSE",
    description="Stream simulation step metrics via Server-Sent Events (SSE).",
)
async def stream_simulation(
    step_interval: int = Query(
        default=100,
        ge=10,
        le=10000,
        description="Interval between steps in milliseconds (default: 100, min: 10, max: 10000)",
    ),
) -> StreamingResponse:
    """
    Stream simulation events via Server-Sent Events (SSE).

    Event types:
    - step: Emitted after each simulation step with metrics
    - heartbeat: Emitted when simulation is paused
    - stopped: Emitted when simulation ends normally
    - error: Emitted on unexpected errors

    Args:
        step_interval: Time between simulation steps in milliseconds.

    Returns:
        StreamingResponse with SSE events.
    """
    return StreamingResponse(
        _simulation_event_generator(step_interval),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
