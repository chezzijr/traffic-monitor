"""Metrics collector and evaluation comparator.

Collects per-step metrics during a sync run and provides a comparison
between an RL-controlled run and a fixed-time baseline run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StepMetric:
    step: int
    waiting_time: float
    queue_length: int
    avg_speed: float
    arrived: int


class MetricsCollector:
    """Accumulates per-step metrics for one sync run."""

    def __init__(self) -> None:
        self._records: list[StepMetric] = []

    def record(
        self,
        step: int,
        waiting_time: float,
        queue_length: int,
        avg_speed: float,
        arrived: int,
    ) -> None:
        self._records.append(StepMetric(
            step=step,
            waiting_time=waiting_time,
            queue_length=queue_length,
            avg_speed=avg_speed,
            arrived=arrived,
        ))

    def summary(self) -> dict:
        """Return aggregated metrics."""
        if not self._records:
            return {
                "total_steps": 0,
                "total_waiting_time": 0.0,
                "avg_waiting_time": 0.0,
                "avg_speed": 0.0,
                "throughput": 0,
                "avg_queue_length": 0.0,
            }

        total_wt = sum(r.waiting_time for r in self._records)
        total_arrived = sum(r.arrived for r in self._records)
        n = len(self._records)

        return {
            "total_steps": n,
            "total_waiting_time": round(total_wt, 2),
            "avg_waiting_time": round(total_wt / n, 2),
            "avg_speed": round(sum(r.avg_speed for r in self._records) / n, 2),
            "throughput": total_arrived,
            "avg_queue_length": round(
                sum(r.queue_length for r in self._records) / n, 2,
            ),
        }

    def reset(self) -> None:
        self._records.clear()

    @property
    def records(self) -> list[StepMetric]:
        return self._records


def build_comparison(rl_summary: dict, baseline_summary: dict) -> dict:
    """Build a comparison report between RL and fixed-time baseline.

    Returns a dict with 'rl_metrics', 'baseline_metrics', and
    'improvement_pct' sections.
    """
    improvement: dict[str, str] = {}

    # Lower waiting time is better
    if baseline_summary["avg_waiting_time"] > 0:
        wt_change = (
            (rl_summary["avg_waiting_time"] - baseline_summary["avg_waiting_time"])
            / baseline_summary["avg_waiting_time"]
            * 100
        )
        improvement["waiting_time"] = f"{wt_change:+.1f}%"
    else:
        improvement["waiting_time"] = "N/A"

    # Higher throughput is better
    if baseline_summary["throughput"] > 0:
        tp_change = (
            (rl_summary["throughput"] - baseline_summary["throughput"])
            / baseline_summary["throughput"]
            * 100
        )
        improvement["throughput"] = f"{tp_change:+.1f}%"
    else:
        improvement["throughput"] = "N/A"

    # Higher avg speed is better
    if baseline_summary["avg_speed"] > 0:
        sp_change = (
            (rl_summary["avg_speed"] - baseline_summary["avg_speed"])
            / baseline_summary["avg_speed"]
            * 100
        )
        improvement["avg_speed"] = f"{sp_change:+.1f}%"
    else:
        improvement["avg_speed"] = "N/A"

    return {
        "rl_metrics": rl_summary,
        "baseline_metrics": baseline_summary,
        "improvement_pct": improvement,
    }
