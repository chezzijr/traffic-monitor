"""Generate a simple 4-way intersection SUMO network for the sync pipeline.

Creates node/edge definition files and runs ``netconvert`` to produce
a ``.net.xml`` with a traffic-light-controlled center junction.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from service.config import (
    SUMO_HOME,
    SUMO_NETWORK_DIR,
    SUMO_EDGE_LENGTH,
    SUMO_NUM_LANES,
)

logger = logging.getLogger(__name__)

_NETWORK_FILE = "intersection.net.xml"

# SUMO edge IDs — used throughout the pipeline for mapping
# Incoming edges (toward center)
EDGE_NORTH_IN = "north_in"   # from north toward center
EDGE_SOUTH_IN = "south_in"
EDGE_EAST_IN = "east_in"
EDGE_WEST_IN = "west_in"
# Outgoing edges (away from center)
EDGE_NORTH_OUT = "north_out"
EDGE_SOUTH_OUT = "south_out"
EDGE_EAST_OUT = "east_out"
EDGE_WEST_OUT = "west_out"

CENTER_JUNCTION = "center"


def get_network_path() -> Path:
    """Return the path to the generated network, creating it if needed."""
    net_path = SUMO_NETWORK_DIR / _NETWORK_FILE
    if not net_path.exists():
        generate_network(net_path)
    return net_path


def generate_network(output_path: Path | None = None) -> Path:
    """Generate a simple 4-way intersection with traffic light.

    Writes .nod.xml + .edg.xml, then runs netconvert.
    """
    if output_path is None:
        output_path = SUMO_NETWORK_DIR / _NETWORK_FILE

    output_path.parent.mkdir(parents=True, exist_ok=True)

    L = SUMO_EDGE_LENGTH
    lanes = SUMO_NUM_LANES

    # ── Nodes ─────────────────────────────────────────────────────────
    nod_path = output_path.with_suffix(".nod.xml")
    nod_content = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<nodes>
    <node id="center" x="0"  y="0"  type="traffic_light"/>
    <node id="north"  x="0"  y="{L}"  type="priority"/>
    <node id="south"  x="0"  y="-{L}" type="priority"/>
    <node id="east"   x="{L}"  y="0"  type="priority"/>
    <node id="west"   x="-{L}" y="0"  type="priority"/>
</nodes>
"""
    nod_path.write_text(nod_content)

    # ── Edges ─────────────────────────────────────────────────────────
    edg_path = output_path.with_suffix(".edg.xml")
    edg_content = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<edges>
    <!-- incoming edges (toward center) -->
    <edge id="{EDGE_NORTH_IN}" from="north"  to="center" numLanes="{lanes}" speed="13.89"/>
    <edge id="{EDGE_SOUTH_IN}" from="south"  to="center" numLanes="{lanes}" speed="13.89"/>
    <edge id="{EDGE_EAST_IN}"  from="east"   to="center" numLanes="{lanes}" speed="13.89"/>
    <edge id="{EDGE_WEST_IN}"  from="west"   to="center" numLanes="{lanes}" speed="13.89"/>
    <!-- outgoing edges (away from center) -->
    <edge id="{EDGE_NORTH_OUT}" from="center" to="north"  numLanes="{lanes}" speed="13.89"/>
    <edge id="{EDGE_SOUTH_OUT}" from="center" to="south"  numLanes="{lanes}" speed="13.89"/>
    <edge id="{EDGE_EAST_OUT}"  from="center" to="east"   numLanes="{lanes}" speed="13.89"/>
    <edge id="{EDGE_WEST_OUT}"  from="center" to="west"   numLanes="{lanes}" speed="13.89"/>
</edges>
"""
    edg_path.write_text(edg_content)

    # ── netconvert ────────────────────────────────────────────────────
    netconvert = os.path.join(SUMO_HOME, "bin", "netconvert")

    cmd = [
        netconvert,
        f"--node-files={nod_path}",
        f"--edge-files={edg_path}",
        "--no-turnarounds=true",
        "--offset.disable-normalization=true",
        f"-o={output_path}",
    ]

    logger.info("Generating SUMO network: %s", " ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info("Network generated: %s", output_path)
        if result.stderr:
            logger.debug("netconvert stderr: %s", result.stderr.strip())
    except FileNotFoundError:
        raise RuntimeError(
            f"netconvert not found at {netconvert}. "
            f"Is SUMO_HOME set correctly? (current: {SUMO_HOME})"
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"netconvert failed (rc={exc.returncode}): {exc.stderr}"
        )

    # Clean up intermediate files
    for tmp in (nod_path, edg_path):
        try:
            tmp.unlink()
        except OSError:
            pass

    return output_path
