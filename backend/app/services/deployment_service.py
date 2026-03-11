"""Service for deploying trained models to traffic lights."""

import logging
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.services import ml_service

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
    num_phases: int = 4


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

    Returns the predicted action, or None if AI control is disabled.
    """
    deployment = _state.get(tl_id)
    if deployment is None or not deployment.ai_control_enabled:
        return None

    controlled_lanes = deployment.controlled_lanes or []
    num_phases = deployment.num_phases

    # Build observation: [vehicle_counts, phase_one_hot]
    vehicle_counts = []
    for lane in controlled_lanes:
        try:
            count = traci_conn.lane.getLastStepVehicleNumber(lane)
            vehicle_counts.append(float(count))
        except Exception:
            vehicle_counts.append(0.0)

    try:
        current_phase = traci_conn.trafficlight.getPhase(tl_id)
    except Exception:
        current_phase = 0

    phase_one_hot = np.zeros(num_phases, dtype=np.float32)
    if 0 <= current_phase < num_phases:
        phase_one_hot[current_phase] = 1.0

    observation = np.concatenate([
        np.array(vehicle_counts, dtype=np.float32),
        phase_one_hot,
    ])

    result = ml_service.predict(observation, deterministic=True)
    action = result["action"]

    traci_conn.trafficlight.setPhase(tl_id, action)
    return action


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
