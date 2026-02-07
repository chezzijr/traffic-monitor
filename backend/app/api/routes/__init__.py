"""API routes module."""

from app.api.routes.camera import router as camera_router
from app.api.routes.control import router as control_router
from app.api.routes.map import router as map_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.simulation import router as simulation_router

__all__ = ["camera_router", "control_router", "map_router", "metrics_router", "simulation_router"]
