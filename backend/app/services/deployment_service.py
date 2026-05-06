"""Service for deploying trained models to traffic lights."""

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.config import settings
from app.models.schemas import TrafficScenario
from app.services import ml_service, sumo_service, route_service

logger = logging.getLogger(__name__)


@dataclass
class DeployedModel:
    """A model deployed to control a traffic light."""
    tl_id: str
    model_id: str
    model_path: str
    network_id: str
    ai_control_enabled: bool = True
    controlled_lanes: list[str] | None = None
    num_phases: int = 4  # Number of green phases (action space)
    green_phase_indices: list[int] | None = None  # SUMO phase indices that are green


class _DeploymentState:
    """Thread-safe deployment state."""

    def __init__(self):
        self._lock = threading.Lock()
        self._deployments: dict[str, DeployedModel] = {}

    def get(self, tl_id: str) -> DeployedModel | None:
        with self._lock:
            return self._deployments.get(tl_id)

    def set(self, tl_id: str, deployment: DeployedModel) -> None:
        with self._lock:
            self._deployments[tl_id] = deployment

    def remove(self, tl_id: str) -> DeployedModel | None:
        with self._lock:
            return self._deployments.pop(tl_id, None)

    def list_all(self) -> list[DeployedModel]:
        with self._lock:
            return list(self._deployments.values())


_state = _DeploymentState()


def deploy_model(
    tl_id: str,
    model_path: str,
    network_id: str,
    controlled_lanes: list[str] | None = None,
    num_phases: int = 4,
) -> dict[str, Any]:
    """Deploy a trained model to a traffic light."""
    from pathlib import Path

    model_id = Path(model_path).stem

    # Load the model
    ml_service.load_model(model_path)

    deployment = DeployedModel(
        tl_id=tl_id,
        model_id=model_id,
        model_path=model_path,
        network_id=network_id,
        ai_control_enabled=True,
        controlled_lanes=controlled_lanes,
        num_phases=num_phases,
    )
    _state.set(tl_id, deployment)

    logger.info(f"Deployed model {model_id} to {tl_id}")
    return {
        "tl_id": tl_id,
        "model_id": model_id,
        "status": "deployed",
    }


def undeploy_model(tl_id: str) -> dict[str, Any]:
    """Remove a deployed model."""
    deployment = _state.remove(tl_id)
    if deployment is None:
        raise ValueError(f"No model deployed to {tl_id}")

    # Unload model if no more deployments
    if not _state.list_all():
        ml_service.unload_model()

    logger.info(f"Undeployed model from {tl_id}")
    return {"tl_id": tl_id, "status": "undeployed"}


def toggle_ai_control(tl_id: str, enabled: bool) -> dict[str, Any]:
    """Toggle AI control for a deployed model."""
    deployment = _state.get(tl_id)
    if deployment is None:
        raise ValueError(f"No model deployed to {tl_id}")

    deployment.ai_control_enabled = enabled
    _state.set(tl_id, deployment)

    logger.info(f"AI control for {tl_id}: {'enabled' if enabled else 'disabled'}")
    return {"tl_id": tl_id, "ai_control_enabled": enabled}


def apply_ai_action(tl_id: str, traci_conn) -> int | None:
    """Build observation from TraCI and predict action.

    The model was trained with green-only phase indexing (0..N-1 for N green phases).
    We map the current SUMO phase to a green phase index for the observation,
    and map the predicted action (green index) back to a SUMO phase index.

    Returns the predicted action (SUMO phase index), or None if AI control is disabled.
    """
    deployment = _state.get(tl_id)
    if deployment is None or not deployment.ai_control_enabled:
        return None

    controlled_lanes = deployment.controlled_lanes or []
    num_phases = deployment.num_phases  # Number of green phases
    green_indices = deployment.green_phase_indices  # SUMO indices of green phases

    # Build observation: [vehicle_counts, phase_one_hot]
    vehicle_counts = []
    for lane in controlled_lanes:
        try:
            count = traci_conn.lane.getLastStepVehicleNumber(lane)
            vehicle_counts.append(float(count))
        except Exception:
            vehicle_counts.append(0.0)

    # Map SUMO phase to green phase index
    try:
        sumo_phase = traci_conn.trafficlight.getPhase(tl_id)
    except Exception:
        sumo_phase = 0

    current_green_idx = 0
    if green_indices and sumo_phase in green_indices:
        current_green_idx = green_indices.index(sumo_phase)

    phase_one_hot = np.zeros(num_phases, dtype=np.float32)
    if 0 <= current_green_idx < num_phases:
        phase_one_hot[current_green_idx] = 1.0

    observation = np.concatenate([
        np.array(vehicle_counts, dtype=np.float32),
        phase_one_hot,
    ])

    result = ml_service.predict(observation, deterministic=True)
    action_green_idx = result["action"]

    # Map green index back to SUMO phase index
    if green_indices and 0 <= action_green_idx < len(green_indices):
        sumo_action = green_indices[action_green_idx]
    else:
        sumo_action = action_green_idx

    traci_conn.trafficlight.setPhase(tl_id, sumo_action)
    return sumo_action


def list_deployments() -> list[dict[str, Any]]:
    """List all active deployments."""
    return [
        {
            "tl_id": d.tl_id,
            "model_id": d.model_id,
            "model_path": d.model_path,
            "network_id": d.network_id,
            "ai_control_enabled": d.ai_control_enabled,
        }
        for d in _state.list_all()
    ]


def get_deployment(tl_id: str) -> dict[str, Any] | None:
    """Get deployment info for a traffic light."""
    d = _state.get(tl_id)
    if d is None:
        return None
    return {
        "tl_id": d.tl_id,
        "model_id": d.model_id,
        "model_path": d.model_path,
        "network_id": d.network_id,
        "ai_control_enabled": d.ai_control_enabled,
    }


def get_deployment_snapshot(tl_id: str) -> dict[str, Any]:
    """Return a live snapshot for a deployed traffic light."""
    deployment = _state.get(tl_id)
    if deployment is None:
        raise ValueError(f"No model deployed to {tl_id}")

    _ensure_simulation_running(deployment.network_id)

    snapshot = sumo_service.get_tl_snapshot(tl_id)
    snapshot.update({
        "model_id": deployment.model_id,
        "model_path": deployment.model_path,
        "network_id": deployment.network_id,
        "ai_control_enabled": deployment.ai_control_enabled,
    })
    return snapshot


def _find_route_file(network_path: Path) -> str | None:
    parent = network_path.parent
    network_stem = network_path.stem.replace(".net", "")
    for candidate in sorted(parent.glob(f"{network_stem}_*.rou.xml")):
        return str(candidate)
    return None


def _ensure_simulation_running(network_id: str) -> None:
    status = sumo_service.get_status()
    if status["status"] in {"running", "paused"}:
        if status.get("network_id") == network_id:
            return
        raise RuntimeError("Simulation is running for another network")

    network_path = settings.simulation_networks_dir / f"{network_id}.net.xml"
    if not network_path.exists():
        raise RuntimeError(f"Network not found: {network_path}")

    routes_path = _find_route_file(network_path)
    if routes_path is None:
        try:
            result = route_service.generate_routes(
                network_path=str(network_path),
                output_dir=str(network_path.parent),
                scenario=TrafficScenario.MODERATE,
                duration=3600,
                seed=None,
            )
            routes_path = result["routes_path"]
        except Exception as exc:
            logger.warning("Route generation failed: %s", exc)
            routes_path = None

    additional_files: list[str] | None = None
    vtypes_file = settings.simulation_vtypes_dir / "vietnamese_vtypes.add.xml"
    if vtypes_file.exists():
        additional_files = [str(vtypes_file)]

    sumo_service.start_simulation(
        network_path=str(network_path),
        network_id=network_id,
        routes_path=routes_path,
        additional_files=additional_files,
        gui=False,
    )
