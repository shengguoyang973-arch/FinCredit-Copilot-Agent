from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.domain import Role, User
from app.integration_outbox import dispatch_pending, get_event, list_attempts, list_events
from app.repository import audit
from app.security import require_roles


router = APIRouter(prefix="/v1/operations", tags=["operations"])


@router.get("/integration-outbox")
def integration_outbox(
    event_status: Literal["pending", "retryable", "delivered", "dead_letter", "blocked"] | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN)),
) -> dict:
    items = list_events(status=event_status, limit=limit)
    audit("integration_outbox_viewed", user.id, "integration_outbox", status=event_status, result_count=len(items))
    return {"items": items}


@router.get("/integration-outbox/{event_id}/attempts")
def integration_outbox_attempts(event_id: str, user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    if not get_event(event_id):
        raise HTTPException(status_code=404, detail="出站事件不存在")
    items = list_attempts(event_id)
    audit("integration_outbox_attempts_viewed", user.id, event_id, result_count=len(items))
    return {"event_id": event_id, "items": items}


@router.post("/integration-outbox/dispatch")
def dispatch_integration_outbox(
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN)),
) -> dict:
    result = dispatch_pending(limit=limit)
    audit("integration_outbox_dispatched", user.id, "integration_outbox", **result)
    return result
