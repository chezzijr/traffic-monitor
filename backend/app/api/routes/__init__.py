"""API routes module."""

from app.api.routes.traffic_light import router as traffic_light_router
from app.api.routes.traffic_light_sim import router as traffic_light_sim_router
from app.api.routes.control import router as control_router
from app.api.routes.map import router as map_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.training import router as training_router
from app.api.routes.tasks import router as tasks_router
from app.api.routes.networks import router as networks_router
from app.api.routes.models import router as models_router
from app.api.routes.deployment import router as deployment_router
from app.api.routes.waiting_count import router as waiting_count_router

__all__ = [
    "traffic_light_router",
    "traffic_light_sim_router",
    "control_router",
    "map_router",
    "metrics_router",
    "training_router",
    "tasks_router",
    "networks_router",
    "models_router",
    "deployment_router",
    "waiting_count_router",
]
