"""Metrics-related API routes."""

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import MetricsSnapshotResponse, MetricsSummary
from app.services import metrics_service

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/current", response_model=MetricsSnapshotResponse)
async def get_current_metrics() -> MetricsSnapshotResponse:
    """Get the current (most recent) metrics snapshot.

    Returns:
        MetricsSnapshotResponse: The most recent metrics snapshot

    Raises:
        HTTPException: 404 if no metrics have been recorded yet
    """
    snapshot = metrics_service.get_current_metrics()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No metrics available")
    return MetricsSnapshotResponse(
        timestamp=snapshot.timestamp,
        step=snapshot.step,
        total_vehicles=snapshot.total_vehicles,
        total_wait_time=snapshot.total_wait_time,
        average_wait_time=snapshot.average_wait_time,
        throughput=snapshot.throughput,
    )


@router.get("/history", response_model=list[MetricsSnapshotResponse])
async def get_metrics_history(
    count: int = Query(default=100, ge=1, le=1000, description="Number of recent snapshots to return")
) -> list[MetricsSnapshotResponse]:
    """Get recent metrics history.

    Args:
        count: Number of recent snapshots to return (default 100, max 1000)

    Returns:
        List of MetricsSnapshotResponse objects
    """
    snapshots = metrics_service.get_metrics_history(count)
    return [
        MetricsSnapshotResponse(
            timestamp=s.timestamp,
            step=s.step,
            total_vehicles=s.total_vehicles,
            total_wait_time=s.total_wait_time,
            average_wait_time=s.average_wait_time,
            throughput=s.throughput,
        )
        for s in snapshots
    ]


@router.get("/summary", response_model=MetricsSummary)
async def get_summary_stats() -> MetricsSummary:
    """Get summary statistics from metrics history.

    Returns:
        MetricsSummary containing aggregate statistics
    """
    stats = metrics_service.get_summary_stats()
    return MetricsSummary(
        total_snapshots=stats["total_snapshots"],
        avg_vehicles=stats["avg_vehicles"],
        avg_wait_time=stats["avg_wait_time"],
        total_throughput=stats["total_throughput"],
    )


@router.delete("/clear")
async def clear_metrics() -> dict[str, str]:
    """Clear all stored metrics.

    Returns:
        Status confirmation dict
    """
    metrics_service.clear_metrics()
    return {"status": "cleared"}
