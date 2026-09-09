from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.config import get_settings, validate_settings
from app.database import connection

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": settings.service_name, "version": settings.app_version}


@router.get("/ready")
def ready() -> dict:
    errors = validate_settings(settings)
    try:
        with connection() as database:
            database.execute("SELECT 1").fetchone()
    except Exception as error:
        errors.append(f"database_unavailable:{type(error).__name__}")
    if errors:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "errors": errors})
    return {"status": "ready", "service": settings.service_name, "provider": settings.agent_provider}
