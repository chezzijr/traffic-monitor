"""Service for deploying trained models to traffic lights.

This is a thin proxy that forwards deploy requests to the Digital Twin service
(services/digital_twin). The Digital Twin service handles:
  - Camera/video detection
  - Vehicle spawning into SUMO
  - Traffic light control (AI + fixed-time)
"""

import json
import logging
import os
import threading
from typing import Any

import httpx
import redis

from app.config import settings

logger = logging.getLogger(__name__)

DIGITAL_TWIN_URL = os.getenv("DIGITAL_TWIN_URL", "http://localhost:8001")
REDIS_HOST = settings.redis_host
REDIS_PORT = settings.redis_port


def _get_redis():
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def _dt_url(path: str) -> str:
    """Build full Digital Twin service URL."""
    return f"{DIGITAL_TWIN_URL}{path}"


# ── Deploy (proxy to Digital Twin) ───────────────────────────────────


def deploy_model(
    tl_id: str,
    model_path: str,
    network_id: str | None = None,
    grid_rows: int = 2,
    grid_cols: int = 3,
) -> dict[str, Any]:
    """Deploy a trained model by forwarding to the Digital Twin service.

    The Digital Twin service runs the full pipeline:
      - Loads the model (single or multi-agent)
      - Starts SUMO with the correct network
      - Applies AI control on trained intersections
      - Applies fixed-time on uncontrolled intersections
    """
    from app.services import ml_service

    # Read model metadata to determine tl_ids
    metadata = ml_service.get_model_metadata(model_path)
    resolved_network_id = network_id or metadata.get("network_id")
    if not resolved_network_id or resolved_network_id == "unknown":
        raise ValueError("Network ID is required or missing from model metadata")

    tl_ids = metadata.get("tl_ids") or []
    if not tl_ids and tl_id:
        tl_ids = [tl_id]

    # Forward to Digital Twin service
    payload = {
        "model_path": model_path,
        "tl_id": tl_id,
        "tl_ids": tl_ids,
        "network_id": resolved_network_id,
        "grid_rows": grid_rows,
        "grid_cols": grid_cols,
    }

    try:
        resp = httpx.post(_dt_url("/deploy/start"), json=payload, timeout=30.0)
        resp.raise_for_status()
        result = resp.json()
    except httpx.HTTPStatusError as e:
        detail = e.response.text if e.response else str(e)
        raise RuntimeError(f"Digital Twin deploy failed: {detail}")
    except httpx.ConnectError:
        raise RuntimeError("Cannot connect to Digital Twin service. Is it running?")
    except Exception as e:
        raise RuntimeError(f"Digital Twin deploy error: {e}")

    # Store deployment info in Redis for quick lookups
    r = _get_redis()
    deploy_info = {
        "tl_id": tl_id,
        "tl_ids": tl_ids,
        "model_path": model_path,
        "network_id": resolved_network_id,
        "model_id": os.path.basename(model_path).rsplit(".", 1)[0],
        "status": "deployed",
        "is_multi_agent": result.get("is_multi_agent", False),
    }
    r.hset("deployments", tl_id, json.dumps(deploy_info))
    # Also store under all tl_ids for multi-agent
    for tid in tl_ids:
        r.hset("deployments", tid, json.dumps(deploy_info))

    logger.info("Deployed model %s via Digital Twin (tl_ids=%s)", model_path, tl_ids)
    return {
        "tl_id": tl_id,
        "model_id": deploy_info["model_id"],
        "status": "deployed",
        "is_multi_agent": deploy_info["is_multi_agent"],
    }


def undeploy_model(tl_id: str) -> dict[str, Any]:
    """Stop deployment by calling Digital Twin stop."""
    r = _get_redis()
    deploy_json = r.hget("deployments", tl_id)
    if not deploy_json:
        raise ValueError(f"No model deployed to {tl_id}")

    # Stop the Digital Twin deploy
    try:
        resp = httpx.post(_dt_url("/deploy/stop"), timeout=15.0)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Failed to stop Digital Twin deploy: %s", e)

    # Clean up Redis
    deploy_info = json.loads(deploy_json)
    tl_ids = deploy_info.get("tl_ids", [tl_id])
    for tid in tl_ids:
        r.hdel("deployments", tid)
    r.hdel("deployments", tl_id)

    logger.info("Undeployed model from %s", tl_id)
    return {"tl_id": tl_id, "status": "undeployed"}


def toggle_ai_control(tl_id: str, enabled: bool) -> dict[str, Any]:
    """Toggle AI control — currently a no-op since DT controls everything."""
    logger.info("AI control for %s: %s (note: DT manages control)", tl_id, enabled)
    return {"tl_id": tl_id, "ai_control_enabled": enabled}


def get_deployment_snapshot(tl_id: str) -> dict[str, Any]:
    """Get a live snapshot from the Digital Twin service."""
    r = _get_redis()
    deploy_json = r.hget("deployments", tl_id)
    if not deploy_json:
        raise ValueError(f"No model deployed to {tl_id}")

    deploy_info = json.loads(deploy_json)

    # Query Digital Twin for live snapshot
    try:
        resp = httpx.get(_dt_url("/deploy/snapshot"), timeout=10.0)
        resp.raise_for_status()
        snapshot = resp.json()
    except httpx.ConnectError:
        raise RuntimeError("Cannot connect to Digital Twin service")
    except Exception as e:
        raise RuntimeError(f"Failed to get snapshot: {e}")

    # Merge deployment info into snapshot
    snapshot.update({
        "model_id": deploy_info.get("model_id"),
        "model_path": deploy_info.get("model_path"),
        "network_id": deploy_info.get("network_id"),
        "ai_control_enabled": True,
        "tl_id": tl_id,
        "is_multi_agent": deploy_info.get("is_multi_agent", False),
    })
    return snapshot


def list_deployments() -> list[dict[str, Any]]:
    """List all active deployments from Redis."""
    r = _get_redis()
    all_deploys = r.hgetall("deployments")

    # Deduplicate by model_path (multi-agent stores under each tl_id)
    seen_models = set()
    deployments = []
    for tl_id, deploy_json in all_deploys.items():
        deploy_info = json.loads(deploy_json)
        model_path = deploy_info.get("model_path", "")
        if model_path in seen_models:
            continue
        seen_models.add(model_path)
        deployments.append({
            "tl_id": deploy_info.get("tl_id", tl_id),
            "tl_ids": deploy_info.get("tl_ids", []),
            "model_id": deploy_info.get("model_id"),
            "model_path": model_path,
            "network_id": deploy_info.get("network_id"),
            "ai_control_enabled": True,
            "is_multi_agent": deploy_info.get("is_multi_agent", False),
        })
    return deployments


def get_deployment(tl_id: str) -> dict[str, Any] | None:
    """Get deployment info for a traffic light."""
    r = _get_redis()
    deploy_json = r.hget("deployments", tl_id)
    if not deploy_json:
        return None
    return json.loads(deploy_json)
