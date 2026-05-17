from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from sci_data_logger.main import create_app

from .api import router as api_router

PACKAGE_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = PACKAGE_ROOT / "static"

pages_router = APIRouter()


@pages_router.get("/")
def redirect_to_workbench() -> RedirectResponse:
    return RedirectResponse(url="/workbench")


@pages_router.get("/workbench")
def workbench_home() -> FileResponse:
    return FileResponse(STATIC_ROOT / "index.html")


def create_workbench_app():
    app = create_app()
    app.include_router(api_router)
    app.include_router(pages_router)
    app.mount("/workbench/assets", StaticFiles(directory=STATIC_ROOT), name="workbench-assets")
    return app


app = create_workbench_app()
