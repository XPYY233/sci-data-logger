from contextlib import asynccontextmanager

from fastapi import FastAPI

from sci_data_logger.api.routes import health_router, router
from sci_data_logger.config import get_settings
from sci_data_logger.db.session import get_engine_cached, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(get_engine_cached())
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    # Eagerly initialize the DB so synchronous TestClient usage (which does
    # not trigger the lifespan unless entered as a context manager) still
    # gets the tables created.
    init_db(get_engine_cached())
    # /health stays open even when API-key auth is on, so include the
    # health router separately (no router-level Depends).
    app.include_router(health_router)
    app.include_router(router)
    return app


app = create_app()
