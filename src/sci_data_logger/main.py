import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from sci_data_logger.api.routes import health_router, router
from sci_data_logger.config import get_settings
from sci_data_logger.db.session import get_engine_cached, init_db
from sci_data_logger.errors import SciDataLoggerError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(get_engine_cached())
    yield


async def _domain_exception_handler(
    request: Request, exc: SciDataLoggerError
) -> JSONResponse:
    """Translate any SciDataLoggerError subclass to its mapped HTTP status +
    structured body. The error class itself carries ``http_status`` and
    ``retryable``; the response shape is::

        {"error": {"type": "<ClassName>", "detail": "...", "retryable": <bool>}}

    Retryable errors also get ``Retry-After: 60`` so well-behaved clients
    back off. We log at WARNING (not ERROR) because these are *expected*
    failure paths — not 500-level bugs in our code.
    """
    headers: dict[str, str] = {}
    if exc.retryable:
        headers["Retry-After"] = "60"
    body = {
        "error": {
            "type": exc.__class__.__name__,
            "detail": str(exc),
            "retryable": exc.retryable,
        }
    }
    logger.warning(
        "domain exception %s on %s %s -> HTTP %d: %s",
        exc.__class__.__name__,
        request.method,
        request.url.path,
        exc.http_status,
        exc,
    )
    return JSONResponse(status_code=exc.http_status, content=body, headers=headers)


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
    # Register the domain exception handler at the app level. FastAPI walks
    # the MRO to find the most specific registered handler, so this single
    # registration on the base class catches every subclass.
    app.add_exception_handler(SciDataLoggerError, _domain_exception_handler)
    return app


app = create_app()
