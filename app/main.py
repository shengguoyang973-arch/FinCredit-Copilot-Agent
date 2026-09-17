from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.bootstrap import initialize_application
from app.config import get_settings
from app.observability import RequestIdMiddleware, configure_logging
from app.routers import applications, approval, audit, data_platform, health, knowledge, observability, operations, release_canaries

settings = get_settings()
STATIC_DIRECTORY = Path(__file__).parent / "static"

configure_logging()
app = FastAPI(title=settings.app_name, version=settings.app_version, description="授信尽调与审批协同 Agent MVP；不自动作出授信决定。")
initialize_application()
app.add_middleware(RequestIdMiddleware)
app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")
app.include_router(health.router)
app.include_router(applications.router)
app.include_router(knowledge.router)
app.include_router(approval.router)
app.include_router(audit.router)
app.include_router(observability.router)
app.include_router(data_platform.router)
app.include_router(operations.router)
app.include_router(release_canaries.router)


@app.get("/", include_in_schema=False)
def workbench() -> FileResponse:
    return FileResponse(STATIC_DIRECTORY / "index.html")
