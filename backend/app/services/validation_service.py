"""Validation service for training and deployment requests."""

from pathlib import Path


def validate_training_request(
    network_id: str,
    tl_id: str,
    algorithm: str,
) -> list[str]:
    """Validate a single-junction training request. Returns list of errors."""
    errors = []

    network_path = Path(f"simulation/networks/{network_id}.net.xml")
    if not network_path.exists():
        errors.append(f"Network file not found: {network_id}")

    if algorithm.lower() not in ("dqn", "ppo"):
        errors.append(f"Invalid algorithm: {algorithm}. Must be 'dqn' or 'ppo'")

    if not tl_id:
        errors.append("Traffic light ID is required")

    return errors


def validate_multi_training_request(
    network_id: str,
    tl_ids: list[str],
    algorithm: str,
) -> list[str]:
    """Validate a multi-junction training request. Returns list of errors."""
    errors = validate_training_request(network_id, tl_ids[0] if tl_ids else "", algorithm)

    if not tl_ids:
        errors.append("At least one traffic light ID is required")

    if len(tl_ids) > 10:
        errors.append(f"Maximum 10 junctions per task, got {len(tl_ids)}")

    return errors


def validate_deployment_request(model_path: str) -> list[str]:
    """Validate a deployment request. Returns list of errors."""
    errors = []

    path = Path(model_path)
    if not path.exists():
        errors.append(f"Model file not found: {model_path}")

    return errors
