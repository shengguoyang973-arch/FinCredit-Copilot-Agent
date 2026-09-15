from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class Role(StrEnum):
    ACCOUNT_MANAGER = "account_manager"
    RISK_MANAGER = "risk_manager"
    APPROVER = "approver"
    COMPLIANCE_ADMIN = "compliance_admin"


class ApplicationStatus(StrEnum):
    DRAFT = "draft"
    PRE_REVIEWED = "pre_reviewed"
    PENDING_APPROVAL = "pending_approval"
    RETURNED = "returned"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class User:
    id: str
    name: str
    roles: set[Role]
    organization_id: str = "demo-bank"
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class LoanApplication:
    id: str
    customer_id: str
    requested_amount: int
    term_months: int
    purpose: str
    created_by: str
    status: ApplicationStatus = ApplicationStatus.DRAFT


@dataclass(frozen=True)
class PolicyClause:
    id: str
    title: str
    content: str
    version: str
    effective_date: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class PolicyRule:
    id: str
    policy_id: str | None
    version: str
    rule_type: str
    parameters: dict
    severity: str
    failure_result: str
    failure_message: str
    pass_message: str
    effective_date: str
    source_name: str


@dataclass
class AuditEvent:
    action: str
    actor_id: str
    resource_id: str
    detail: dict
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: int | None = None
    prev_hash: str = ""
    event_hash: str = ""
