from __future__ import annotations

from fastapi import APIRouter, Depends

from app.domain import Role, User
from app.security import require_roles
from app.state_store import list_audit_events, verify_audit_chain

router = APIRouter(prefix="/v1/audit-events", tags=["audit"])


@router.get("")
def audit_events(user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> list[dict]:
    return [{
        "id": e.id,
        "action": e.action,
        "actor_id": e.actor_id,
        "resource_id": e.resource_id,
        "detail": e.detail,
        "timestamp": e.timestamp,
        "prev_hash": e.prev_hash,
        "event_hash": e.event_hash,
    } for e in list_audit_events()]


@router.get("/integrity")
def audit_integrity(user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    del user
    return verify_audit_chain()
