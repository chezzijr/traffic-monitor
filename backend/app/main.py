"""FastAPI application entry point."""

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    control_router,
    deployment_router,
    map_router,
    metrics_router,
    models_router,
    networks_router,
    tasks_router,
    traffic_light_router,
    traffic_light_sim_router,
    training_router,
    waiting_count_router,
)
from app.config import settings
from app.services import ml_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan: pre-warm the model list off the request path so the
    first page load doesn't pay the cold ~25s scan of the simulation/ volume."""

    def _prewarm() -> None:
        try:
            ml_service.list_models()
            logger.info("model-list cache pre-warmed")
        except Exception:
            logger.warning("model-list pre-warm failed", exc_info=True)

    threading.Thread(target=_prewarm, name="model-list-prewarm", daemon=True).start()
    yield


app = FastAPI(
    title="Traffic Monitor API",
    description="Real-time traffic monitoring and control system",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers with API prefix
app.include_router(map_router, prefix=settings.api_prefix)
app.include_router(metrics_router, prefix=settings.api_prefix)
app.include_router(control_router, prefix=settings.api_prefix)
app.include_router(traffic_light_router, prefix=settings.api_prefix)
app.include_router(traffic_light_sim_router, prefix=settings.api_prefix)
app.include_router(training_router, prefix=settings.api_prefix)
app.include_router(tasks_router, prefix=settings.api_prefix)
app.include_router(networks_router, prefix=settings.api_prefix)
app.include_router(models_router, prefix=settings.api_prefix)
app.include_router(deployment_router, prefix=settings.api_prefix)
app.include_router(waiting_count_router, prefix=settings.api_prefix)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
