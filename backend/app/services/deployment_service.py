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


class DeployConflictError(RuntimeError):
    """Raised when DT returns 409 even after stop-then-start orchestration.

    Carries the structured body so the route can re-emit it as HTTP 409.
    """

    def __init__(self, detail: dict[str, Any]):
        super().__init__("Deploy conflict: DT reports active deploy")
        self.detail = detail


def _clear_redis_deployments() -> None:
    """Wipe the deployments hash so the next deploy starts clean.

    Single-agent and multi-agent both write per-TL keys; stale keys from a
    previous deploy must be removed before a swap or the list would contain
    both old + new TLs.
    """
    r = _get_redis()
    try:
        r.delete("deployments")
    except Exception as exc:
        logger.warning("Failed to clear deployments hash: %s", exc)


def _stop_existing_deploy() -> None:
    """Ask DT to stop any active deploy. Idempotent — safe to call when nothing runs."""
    try:
        resp = httpx.post(_dt_url("/deploy/stop"), timeout=15.0)
        if resp.status_code >= 500:
            logger.warning("DT /deploy/stop returned %s: %s", resp.status_code, resp.text)
    except httpx.ConnectError:
        # DT may be down; surface only when /deploy/start fails for the same reason
        logger.warning("DT unreachable on /deploy/stop (continuing — start will surface)")
    except Exception as exc:
        logger.warning("DT /deploy/stop error (continuing): %s", exc)


def precheck_video() -> dict[str, Any]:
    """Pre-flight check that DT can read the configured video file.

    Returns the DT body verbatim plus an ``ok: bool`` shortcut so the frontend
    can branch with a single field. Used by the deploy button to block early
    when git-LFS files are missing.
    """
    try:
        resp = httpx.get(_dt_url("/deploy/videos/check"), timeout=10.0)
        resp.raise_for_status()
        body = resp.json()
    except httpx.ConnectError:
        return {
            "ok": False,
            "error": "dt_unreachable",
            "hint": "Digital Twin service is offline. Is the container running?",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"precheck_failed: {exc}",
            "hint": None,
        }
    body["ok"] = bool(body.get("exists"))
    return body


def deploy_model(
    tl_id: str,
    model_path: str,
    network_id: str | None = None,
    grid_rows: int = 2,
    grid_cols: int = 3,
) -> dict[str, Any]:
    """Deploy a trained model by forwarding to the Digital Twin service.

    Always issues ``/deploy/stop`` first (idempotent) so a fresh deploy can
    swap out any in-flight run. Clears the Redis deployments hash before
    writing the new entries so stale TL keys from a previous model never
    appear in the listing.
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

    # ── Stop any prior deploy. Keep Redis until the new start succeeds so
    # an empty list never overlaps a still-running DT (C9 — fixes a state
    # divergence window where the previous order wiped Redis before /start
    # returned, leaving the UI blank if DT was unreachable).
    _stop_existing_deploy()

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
        if resp.status_code == 409:
            # DT still has an active deploy — surface as structured conflict.
            # FastAPI wraps HTTPException(detail=...) into a JSON envelope
            # {"detail": {...}}, so unwrap one level so the frontend's
            # `current_model_path` lookup hits a flat dict (C1).
            try:
                body = resp.json()
            except Exception:
                body = {"detail": resp.text}
            inner: dict = body  # type: ignore[assignment]
            if isinstance(body, dict) and isinstance(body.get("detail"), dict):
                inner = body["detail"]
            elif not isinstance(body, dict):
                inner = {"detail": body}
            raise DeployConflictError(inner)
        resp.raise_for_status()
        result = resp.json()
    except DeployConflictError:
        raise
    except httpx.HTTPStatusError as e:
        detail = e.response.text if e.response else str(e)
        raise RuntimeError(f"Digital Twin deploy failed: {detail}")
    except httpx.ConnectError:
        raise RuntimeError("Cannot connect to Digital Twin service. Is it running?")
    except Exception as e:
        raise RuntimeError(f"Digital Twin deploy error: {e}")

    # ── Start succeeded — now wipe stale keys + write new state. Order
    # matters: if the process dies before the writes finish, listing
    # returns an empty list rather than mixed-state stale entries.
    _clear_redis_deployments()

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
        "deploy_id": result.get("deploy_id"),
    }
    r.hset("deployments", tl_id, json.dumps(deploy_info))
    # Also store under all tl_ids for multi-agent
    for tid in tl_ids:
        r.hset("deployments", tid, json.dumps(deploy_info))

    logger.info(
        "Deployed model %s via Digital Twin (tl_ids=%s, deploy_id=%s)",
        model_path, tl_ids, result.get("deploy_id"),
    )
    # C7 — return everything the frontend Deployment type expects, so the
    # optimistic addDeployment doesn't shove undefined into the store.
    return {
        "tl_id": tl_id,
        "tl_ids": tl_ids,
        "model_id": deploy_info["model_id"],
        "model_path": model_path,
        "network_id": resolved_network_id,
        "status": "deployed",
        "is_multi_agent": deploy_info["is_multi_agent"],
        "deploy_id": result.get("deploy_id"),
        "ai_control_enabled": True,
    }


def stop_all_deployments() -> dict[str, Any]:
    """Stop the active DT deploy and wipe the Redis deployments hash.

    Cleaner than iterating undeploy_model per TL — DT is singleton, so one
    /deploy/stop covers every controlled TL; clearing Redis once removes
    all keys for both single- and multi-agent deploys.
    """
    stop_result: dict[str, Any] = {"dt_stopped": False}
    try:
        resp = httpx.post(_dt_url("/deploy/stop"), timeout=15.0)
        if resp.status_code < 500:
            stop_result["dt_stopped"] = True
            try:
                stop_result["dt_response"] = resp.json()
            except Exception:
                stop_result["dt_response"] = resp.text
    except httpx.ConnectError:
        stop_result["error"] = "dt_unreachable"
    except Exception as exc:
        stop_result["error"] = f"dt_stop_failed: {exc}"

    _clear_redis_deployments()
    logger.info("Stopped all deployments (dt_stopped=%s)", stop_result["dt_stopped"])
    return {"status": "stopped_all", **stop_result}


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
            "deploy_id": deploy_info.get("deploy_id"),
        })
    return deployments


def get_deployment(tl_id: str) -> dict[str, Any] | None:
    """Get deployment info for a traffic light."""
    r = _get_redis()
    deploy_json = r.hget("deployments", tl_id)
    if not deploy_json:
        return None
    return json.loads(deploy_json)
