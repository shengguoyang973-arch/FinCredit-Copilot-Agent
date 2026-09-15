from __future__ import annotations

from app.domain import Role, User
from app.state_store import audit, get_application, get_customer

__all__ = ["USERS", "audit", "get_application", "get_customer"]

USERS = {
    "sales_001": User("sales_001", "王客户经理", {Role.ACCOUNT_MANAGER}, "branch-shanghai", {"region": "华东"}),
    "rm_001": User("rm_001", "李风险经理", {Role.RISK_MANAGER}, "branch-shanghai", {"region": "华东"}),
    "approver_001": User("approver_001", "陈审批人", {Role.APPROVER}, "branch-shanghai", {"region": "华东"}),
    "compliance_001": User("compliance_001", "周合规管理员", {Role.COMPLIANCE_ADMIN}, "head-office", {"region": "全国"}),
}
