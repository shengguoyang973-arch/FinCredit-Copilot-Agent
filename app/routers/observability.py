from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.domain import Role, User
from app.metrics import agent_metrics
from app.security import require_roles

router = APIRouter(prefix="/v1/observability", tags=["observability"])


@router.get("/agent-metrics")
def get_agent_metrics(limit: int = Query(default=200, ge=1, le=1000), user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    return agent_metrics(limit)
