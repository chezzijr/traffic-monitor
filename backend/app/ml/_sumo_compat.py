"""Shared SUMO/TraCI lazy-loader for ML training environments."""

import os
import sys

_traci = None


def get_traci():
    """Import traci, adding SUMO_HOME/tools to sys.path if needed."""
    global _traci
    if _traci is None:
        sumo_home = os.environ.get("SUMO_HOME", "/usr/share/sumo")
        sumo_tools = os.path.join(sumo_home, "tools")
        if os.path.isdir(sumo_tools) and sumo_tools not in sys.path:
            sys.path.append(sumo_tools)
        try:
            import traci
            _traci = traci
        except ImportError:
            raise RuntimeError(
                f"SUMO TraCI not available. SUMO_HOME={sumo_home}, "
                f"tools dir exists={os.path.isdir(sumo_tools)}"
            )
    return _traci
