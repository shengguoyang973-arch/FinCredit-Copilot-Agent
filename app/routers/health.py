from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.config import get_settings, validate_settings
from app.database import connection
from app.vector_store import vector_store_healthcheck

router = APIRouter(tags=["health"])
@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "service": settings.service_name, "version": settings.app_version}


@router.get("/ready")
def ready() -> dict:
    settings = get_settings()
    errors = validate_settings(settings)
    try:
        with connection() as database:
            database.execute("SELECT 1").fetchone()
    except Exception as error:
        errors.append(f"database_unavailable:{type(error).__name__}")
    try:
        vector_store_healthcheck(settings)
    except Exception as error:
        errors.append(f"vector_store_unavailable:{type(error).__name__}")
    if errors:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "errors": errors})
    return {
        "status": "ready", "service": settings.service_name, "provider": settings.agent_provider,
        "embedding_provider": settings.embedding_provider, "vector_store": settings.vector_store_backend,
        "identity_provider": settings.identity_provider,
    }
