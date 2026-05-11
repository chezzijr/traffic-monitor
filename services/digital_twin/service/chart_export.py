"""Chart export utilities for Digital Twin result reporting."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_DIRECTION_STYLES: dict[str, dict] = {
    "north": {"color": "#e74c3c", "label": "Bắc (North)"},
    "south": {"color": "#3498db", "label": "Nam (South)"},
    "east":  {"color": "#f39c12", "label": "Đông (East)"},
    "west":  {"color": "#9b59b6", "label": "Tây (West)"},
}


def save_waiting_timeseries_chart(
    history: list[tuple[float, int, int, int, int]],
    out_path: Path,
    title: str = "Số xe chờ theo thời gian video",
) -> Path:
    """Generate and save a waiting-count time-series chart.

    Parameters
    ----------
    history:
        List of ``(video_time_sec, north, south, east, west)`` tuples
        accumulated by ``video_analyzer.get_waiting_history()``.
    out_path:
        Destination file path (PNG).  Parent directory is created if needed.
    title:
        Chart title.

    Returns
    -------
    Path
        The resolved path of the saved image.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker

    if not history:
        raise ValueError("Waiting history is empty — nothing to plot.")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    times   = [r[0] for r in history]
    norths  = [r[1] for r in history]
    souths  = [r[2] for r in history]
    easts   = [r[3] for r in history]
    wests   = [r[4] for r in history]

    fig, ax = plt.subplots(figsize=(14, 5))

    ax.plot(times, norths, color=_DIRECTION_STYLES["north"]["color"],
            label=_DIRECTION_STYLES["north"]["label"], linewidth=1.5)
    ax.plot(times, souths, color=_DIRECTION_STYLES["south"]["color"],
            label=_DIRECTION_STYLES["south"]["label"], linewidth=1.5)
    ax.plot(times, easts,  color=_DIRECTION_STYLES["east"]["color"],
            label=_DIRECTION_STYLES["east"]["label"],  linewidth=1.5)
    ax.plot(times, wests,  color=_DIRECTION_STYLES["west"]["color"],
            label=_DIRECTION_STYLES["west"]["label"],  linewidth=1.5)

    ax.set_xlabel("Thời gian video (giây)", fontsize=11)
    ax.set_ylabel("Số xe chờ", fontsize=11)
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.legend(loc="upper right", fontsize=10)
    ax.xaxis.set_major_locator(ticker.MaxNLocator(nbins=12, integer=True))
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)

    logger.info("Saved waiting-count time-series chart → %s", out_path)
    return out_path


def default_chart_path(result_dir: Path, tag: str = "") -> Path:
    """Return a timestamped output path inside *result_dir*."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"waiting-count-timeseries_{ts}{('_' + tag) if tag else ''}.png"
    return result_dir / name
