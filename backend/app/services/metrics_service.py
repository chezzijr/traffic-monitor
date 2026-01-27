"""Metrics collection and storage service.

This service collects and stores simulation metrics history in memory using a bounded
deque. Thread safety is ensured for concurrent access from simulation steps and API endpoints.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import threading


@dataclass
class MetricsSnapshot:
    """A single snapshot of simulation metrics."""

    timestamp: datetime
    step: int
    total_vehicles: int
    total_wait_time: float
    average_wait_time: float
    throughput: int  # vehicles that completed their trip


@dataclass
class MetricsHistory:
    """Stores metrics history with a max size.

    Uses a bounded deque to maintain a fixed-size history of metrics snapshots.
    Thread-safe for concurrent read/write access.
    """

    max_size: int = 1000
    snapshots: deque = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, snapshot: MetricsSnapshot) -> None:
        """Add a snapshot to the history.

        If the history is at max capacity, the oldest snapshot is removed.

        Args:
            snapshot: The metrics snapshot to add
        """
        with self._lock:
            if len(self.snapshots) >= self.max_size:
                self.snapshots.popleft()
            self.snapshots.append(snapshot)

    def get_recent(self, count: int = 100) -> list[MetricsSnapshot]:
        """Get the most recent snapshots.

        Args:
            count: Number of recent snapshots to return

        Returns:
            List of the most recent MetricsSnapshot objects
        """
        with self._lock:
            return list(self.snapshots)[-count:]

    def clear(self) -> None:
        """Clear all stored snapshots."""
        with self._lock:
            self.snapshots.clear()


# Global metrics history
_history = MetricsHistory()


def record_metrics(
    step: int,
    total_vehicles: int,
    total_wait_time: float,
    average_wait_time: float,
    throughput: int = 0,
) -> MetricsSnapshot:
    """Record a metrics snapshot.

    Args:
        step: Current simulation step
        total_vehicles: Number of vehicles in simulation
        total_wait_time: Total waiting time of all vehicles
        average_wait_time: Average waiting time per vehicle
        throughput: Vehicles that completed their trip

    Returns:
        The recorded snapshot
    """
    snapshot = MetricsSnapshot(
        timestamp=datetime.now(),
        step=step,
        total_vehicles=total_vehicles,
        total_wait_time=total_wait_time,
        average_wait_time=average_wait_time,
        throughput=throughput,
    )
    _history.add(snapshot)
    return snapshot


def get_current_metrics() -> Optional[MetricsSnapshot]:
    """Get the most recent metrics snapshot.

    Returns:
        The most recent MetricsSnapshot, or None if no metrics recorded
    """
    recent = _history.get_recent(1)
    return recent[0] if recent else None


def get_metrics_history(count: int = 100) -> list[MetricsSnapshot]:
    """Get recent metrics history.

    Args:
        count: Number of recent snapshots to return

    Returns:
        List of MetricsSnapshot objects
    """
    return _history.get_recent(count)


def clear_metrics() -> None:
    """Clear all stored metrics."""
    _history.clear()


def get_summary_stats() -> dict:
    """Get summary statistics from metrics history.

    Returns:
        dict containing:
            - total_snapshots: Number of snapshots in history
            - avg_vehicles: Average number of vehicles across all snapshots
            - avg_wait_time: Average waiting time across all snapshots
            - total_throughput: Total vehicles that completed their trip
    """
    snapshots = _history.get_recent(1000)
    if not snapshots:
        return {
            "total_snapshots": 0,
            "avg_vehicles": 0,
            "avg_wait_time": 0,
            "total_throughput": 0,
        }

    return {
        "total_snapshots": len(snapshots),
        "avg_vehicles": sum(s.total_vehicles for s in snapshots) / len(snapshots),
        "avg_wait_time": sum(s.average_wait_time for s in snapshots) / len(snapshots),
        "total_throughput": sum(s.throughput for s in snapshots),
    }
