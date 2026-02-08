"""Validation service for training and deployment constraints.

This service provides validation functions that enforce business rules
for ML training and model deployment operations.
"""

import logging
from pathlib import Path

from fastapi import HTTPException, status

from app.services import ml_service

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Custom exception for validation errors with error codes."""

    def __init__(self, error_code: str, message: str, status_code: int = 400):
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def validate_tl_not_controlled(tl_id: str) -> None:
    """Validate that a traffic light is not already under AI control.

    Args:
        tl_id: Traffic light ID to check

    Raises:
        HTTPException: If TL is already controlled (409 Conflict)
    """
    from app.services import deployment_service

    if deployment_service.is_tl_controlled(tl_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "TL_ALREADY_CONTROLLED",
                "message": f"Traffic light '{tl_id}' is already controlled by a deployed model",
            },
        )


def validate_model_network_compatibility(model_path: str, network_id: str) -> None:
    """Validate that a model was trained on the specified network.

    Args:
        model_path: Path to the model file
        network_id: Expected network ID

    Raises:
        HTTPException: If model was trained on a different network (400 Bad Request)
    """
    metadata = ml_service.get_model_metadata(model_path)

    if metadata is None:
        logger.warning(f"No metadata found for model {model_path}, skipping network validation")
        return

    model_network_id = metadata.get("network_id")
    if model_network_id and model_network_id != network_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "NETWORK_MISMATCH",
                "message": f"Model was trained on network '{model_network_id}', but simulation is running on '{network_id}'",
            },
        )


def validate_no_training_in_progress() -> None:
    """Validate that no training job is currently running.

    Raises:
        HTTPException: If training is in progress (409 Conflict)
    """
    if ml_service.is_training_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "TRAINING_IN_PROGRESS",
                "message": "A training job is already running. Stop it first.",
            },
        )


def validate_timesteps_range(total_timesteps: int, min_steps: int = 100, max_steps: int = 100000) -> None:
    """Validate that timesteps is within acceptable range.

    Args:
        total_timesteps: Requested training timesteps
        min_steps: Minimum allowed timesteps
        max_steps: Maximum allowed timesteps

    Raises:
        HTTPException: If timesteps out of range (400 Bad Request)
    """
    if total_timesteps < min_steps or total_timesteps > max_steps:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "TIMESTEPS_OUT_OF_RANGE",
                "message": f"total_timesteps must be between {min_steps} and {max_steps}, got {total_timesteps}",
            },
        )


def validate_model_exists(model_path: str) -> None:
    """Validate that a model file exists.

    Args:
        model_path: Path to the model file

    Raises:
        HTTPException: If model file not found (404 Not Found)
    """
    if not Path(model_path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "MODEL_NOT_FOUND",
                "message": f"Model file not found: {model_path}",
            },
        )


def validate_network_exists(network_id: str) -> None:
    """Validate that a network exists.

    Args:
        network_id: Network ID to check

    Raises:
        HTTPException: If network not found (404 Not Found)
    """
    from app.services.osm_service import SIMULATION_NETWORKS_DIR

    network_path = SIMULATION_NETWORKS_DIR / f"{network_id}.net.xml"
    if not network_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "NETWORK_NOT_FOUND",
                "message": f"Network '{network_id}' not found",
            },
        )


def validate_no_active_deployments() -> None:
    """Validate that no models are currently deployed.

    Raises:
        HTTPException: If there are active deployments (409 Conflict)
    """
    from app.services import deployment_service

    deployments = deployment_service.get_deployments()
    if deployments:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "DEPLOYMENTS_ACTIVE",
                "message": "Cannot start training while models are deployed. Undeploy all models first.",
            },
        )


def validate_tl_deployed(tl_id: str) -> None:
    """Validate that a traffic light has a deployed model.

    Args:
        tl_id: Traffic light ID to check

    Raises:
        HTTPException: If TL is not deployed (404 Not Found)
    """
    from app.services import deployment_service

    if not deployment_service.is_tl_controlled(tl_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "TL_NOT_DEPLOYED",
                "message": f"Traffic light '{tl_id}' has no deployed model",
            },
        )
