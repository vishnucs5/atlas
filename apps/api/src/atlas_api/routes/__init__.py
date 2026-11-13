"""Route definitions for ATLAS API."""

from atlas_api.routes.health import router as health_router
from atlas_api.routes.orchestration import router as orchestration_router

__all__ = ["health_router", "orchestration_router"]
