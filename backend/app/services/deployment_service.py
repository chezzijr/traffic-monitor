"""Deployment service for managing ML model deployments to traffic lights.

This service tracks which models are deployed to which traffic lights
and handles AI control during simulation.
"""

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from app.services import ml_service, sumo_service

logger = logging.getLogger(__name__)


@dataclass
class DeployedModel:
    """Represents a deployed model on a traffic light."""

    tl_id: str
    model_id: str
    model_path: str
    network_id: str
    ai_control_enabled: bool = True
    controlled_lanes: list[str] = field(default_factory=list)
    num_phases: int = 4


class DeploymentServiceState:
    """Thread-safe state management for deployment service."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._deployments: dict[str, DeployedModel] = {}

    @property
    def deployments(self) -> dict[str, DeployedModel]:
        with self._lock:
            return self._deployments.copy()


# Global service state
_state = DeploymentServiceState()


def get_model_metadata(model_path: str) -> dict[str, Any] | None:
    """Load model metadata from JSON file.

    Args:
        model_path: Path to the model .zip file

    Returns:
        Metadata dict or None if not found
    """
    metadata_path = Path(model_path).with_suffix(".metadata.json")
    if metadata_path.exists():
        with open(metadata_path) as f:
            return json.load(f)
    return None


def deploy_model(model_path: str, tl_id: str) -> dict[str, Any]:
    """Deploy a trained model to a traffic light.

    Args:
        model_path: Path to the trained model file
        tl_id: Traffic light ID to deploy to

    Returns:
        Deployment info dict

    Raises:
        RuntimeError: If TL is already controlled or model cannot be loaded
        FileNotFoundError: If model file doesn't exist
    """
    with _state._lock:
        # Check if TL is already controlled
        if tl_id in _state._deployments:
            raise RuntimeError(f"Traffic light '{tl_id}' is already controlled by a deployed model")

        # Load model metadata
        metadata = get_model_metadata(model_path)
        network_id = metadata.get("network_id", "unknown") if metadata else "unknown"
        controlled_lanes = metadata.get("controlled_lanes", []) if metadata else []
        num_phases = metadata.get("num_phases", 4) if metadata else 4

        # Load the model via ml_service
        ml_service.load_model(model_path)

        # Extract model_id from path
        model_id = Path(model_path).stem

        # Create deployment
        deployment = DeployedModel(
            tl_id=tl_id,
            model_id=model_id,
            model_path=model_path,
            network_id=network_id,
            ai_control_enabled=True,
            controlled_lanes=controlled_lanes,
            num_phases=num_phases,
        )
        _state._deployments[tl_id] = deployment

        logger.info(f"Deployed model {model_id} to traffic light {tl_id}")

        return {
            "status": "deployed",
            "tl_id": tl_id,
            "model_id": model_id,
            "network_id": network_id,
        }


def undeploy_model(tl_id: str) -> dict[str, Any]:
    """Remove a model deployment from a traffic light.

    Args:
        tl_id: Traffic light ID to undeploy from

    Returns:
        Undeploy status dict

    Raises:
        RuntimeError: If TL is not deployed
    """
    with _state._lock:
        if tl_id not in _state._deployments:
            raise RuntimeError(f"Traffic light '{tl_id}' has no deployed model")

        deployment = _state._deployments.pop(tl_id)
        logger.info(f"Undeployed model {deployment.model_id} from traffic light {tl_id}")

        # Unload model if no other deployments use it
        # For now, just unload (single model support)
        if len(_state._deployments) == 0:
            ml_service.unload_model()

        return {
            "status": "undeployed",
            "tl_id": tl_id,
            "model_id": deployment.model_id,
        }


def get_deployments() -> list[dict[str, Any]]:
    """Get all active deployments.

    Returns:
        List of deployment info dicts
    """
    with _state._lock:
        return [
            {
                "tl_id": d.tl_id,
                "model_id": d.model_id,
                "model_path": d.model_path,
                "network_id": d.network_id,
                "ai_control_enabled": d.ai_control_enabled,
            }
            for d in _state._deployments.values()
        ]


def get_active_deployments() -> list[DeployedModel]:
    """Get deployments with AI control enabled.

    Returns:
        List of DeployedModel objects with AI enabled
    """
    with _state._lock:
        return [d for d in _state._deployments.values() if d.ai_control_enabled]


def is_tl_controlled(tl_id: str) -> bool:
    """Check if a traffic light has a deployed model.

    Args:
        tl_id: Traffic light ID

    Returns:
        True if TL has a deployed model
    """
    with _state._lock:
        return tl_id in _state._deployments


def is_ai_controlling(tl_id: str) -> bool:
    """Check if a traffic light is under active AI control.

    Args:
        tl_id: Traffic light ID

    Returns:
        True if TL is deployed AND AI control is enabled
    """
    with _state._lock:
        if tl_id not in _state._deployments:
            return False
        return _state._deployments[tl_id].ai_control_enabled


def toggle_ai_control(tl_id: str, enabled: bool) -> dict[str, Any]:
    """Enable or disable AI control for a traffic light.

    Args:
        tl_id: Traffic light ID
        enabled: Whether to enable AI control

    Returns:
        Status dict

    Raises:
        RuntimeError: If TL is not deployed
    """
    with _state._lock:
        if tl_id not in _state._deployments:
            raise RuntimeError(f"Traffic light '{tl_id}' has no deployed model")

        _state._deployments[tl_id].ai_control_enabled = enabled
        logger.info(f"AI control for {tl_id}: {'enabled' if enabled else 'disabled'}")

        return {
            "tl_id": tl_id,
            "ai_control_enabled": enabled,
        }


def get_observation_for_tl(tl_id: str) -> np.ndarray:
    """Get observation for a traffic light from SUMO.

    Args:
        tl_id: Traffic light ID

    Returns:
        Observation array for ML model
    """
    with _state._lock:
        deployment = _state._deployments.get(tl_id)
        if not deployment:
            raise RuntimeError(f"Traffic light '{tl_id}' is not deployed")

        controlled_lanes = deployment.controlled_lanes
        num_phases = deployment.num_phases

    if not sumo_service.SUMO_AVAILABLE or sumo_service.traci is None:
        obs_dim = len(controlled_lanes) * 2 + num_phases
        return np.zeros(obs_dim, dtype=np.float32)

    traci = sumo_service.traci

    # Collect queue lengths and waiting times per lane
    queue_lengths = []
    waiting_times = []

    for lane_id in controlled_lanes:
        try:
            queue_length = traci.lane.getLastStepHaltingNumber(lane_id)
            queue_lengths.append(float(queue_length))

            vehicle_ids = traci.lane.getLastStepVehicleIDs(lane_id)
            lane_wait_time = sum(traci.vehicle.getWaitingTime(vid) for vid in vehicle_ids)
            waiting_times.append(float(lane_wait_time))
        except Exception:
            queue_lengths.append(0.0)
            waiting_times.append(0.0)

    # Get current phase as one-hot encoding
    current_phase = 0
    try:
        current_phase = traci.trafficlight.getPhase(tl_id)
    except Exception:
        pass

    phase_one_hot = np.zeros(num_phases, dtype=np.float32)
    if 0 <= current_phase < num_phases:
        phase_one_hot[current_phase] = 1.0

    observation = np.concatenate([
        np.array(queue_lengths, dtype=np.float32),
        np.array(waiting_times, dtype=np.float32),
        phase_one_hot,
    ])

    return observation


def apply_ai_action(tl_id: str) -> int:
    """Get AI action and apply it to the traffic light.

    Args:
        tl_id: Traffic light ID

    Returns:
        The action (phase index) that was applied
    """
    # Get observation
    observation = get_observation_for_tl(tl_id)

    # Get prediction from loaded model
    result = ml_service.predict(observation)
    action = result["action"]

    # Apply the action
    sumo_service.set_traffic_light_phase(tl_id, action)

    return action


def clear_deployments() -> None:
    """Clear all deployments. Used when simulation stops."""
    with _state._lock:
        _state._deployments.clear()
        ml_service.unload_model()
    logger.info("Cleared all deployments")
