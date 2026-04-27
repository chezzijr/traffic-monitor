"""Waiting count service – proxies to the Digital Twin microservice.

The heavy YOLO processing has been moved to the standalone
``services/digital_twin`` service (port 8001).  This module simply
forwards requests and returns the response.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

DIGITAL_TWIN_URL = os.getenv("DIGITAL_TWIN_URL", "http://localhost:8001")


async def get_waiting_count(id_camera: str) -> dict:
    """Proxy the waiting-count request to the Digital Twin service.

    Parameters
    ----------
    id_camera:
        Camera identifier passed through to the downstream service.

    Returns
    -------
    dict with keys ``id_camera``, ``north``, ``south``, ``east``,
    ``west``, ``total``.
    """
    url = f"{DIGITAL_TWIN_URL}/waiting_count"
    logger.info("Proxying waiting_count for camera %s → %s", id_camera, url)

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url, params={"id_camera": id_camera})
        resp.raise_for_status()
        return resp.json()
