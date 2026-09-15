from __future__ import annotations

from app.document_store import material_check
from app.knowledge_store import get_policies
from app.repository import get_customer
from app.rule_store import active_policy_ids
from app.workflow_store import get_latest_approval_task

ALLOWED_AGENT_TOOLS = {
    "get_application_snapshot",
    "get_material_status",
    "get_policy_evidence",
    "get_approval_status",
}


def execute_agent_tools(application, question: str | None = None) -> list[dict]:
    selected_tools = _select_tools(question)
    results = []
    for tool_name in selected_tools:
        results.append({
            "tool_name": tool_name,
            "status": "success",
            "result": _execute_tool(tool_name, application),
        })
    return results


def _select_tools(question: str | None) -> list[str]:
    if not question:
        return ["get_application_snapshot", "get_material_status", "get_policy_evidence"]
    selected = {"get_application_snapshot", "get_material_status", "get_policy_evidence"}
    if any(token in question for token in ("审批", "提交", "状态", "处理")):
        selected.add("get_approval_status")
    return [tool for tool in ("get_application_snapshot", "get_material_status", "get_policy_evidence", "get_approval_status") if tool in selected]


def _execute_tool(tool_name: str, application) -> dict:
    if tool_name not in ALLOWED_AGENT_TOOLS:
        raise ValueError(f"Agent 工具未在白名单中：{tool_name}")
    if tool_name == "get_application_snapshot":
        customer = get_customer(application.customer_id)
        return {
            "application": {
                "id": application.id,
                "requested_amount": application.requested_amount,
                "term_months": application.term_months,
                "purpose": application.purpose,
                "status": application.status,
            },
            "customer": _safe_customer_snapshot(customer),
        }
    if tool_name == "get_material_status":
        status = material_check(application.id)
        return {
            "complete": status["complete"],
            "missing": status["missing"],
            "documents": [
                {
                    "document_type": item["document_type"],
                    "byte_size": item["byte_size"],
                    "sha256": item["sha256"],
                    "extracted_fields": sorted(key for key in item["extracted"] if key != "text_preview"),
                }
                for item in status["documents"]
            ],
        }
    if tool_name == "get_policy_evidence":
        return {"policy_ids": [policy.id for policy in get_policies(active_policy_ids())]}
    if tool_name == "get_approval_status":
        task = get_latest_approval_task(application.id)
        if not task:
            return {"task": None}
        return {"task": {
            "id": task["id"],
            "status": task["status"],
            "submitted_at": task["submitted_at"],
            "decided_at": task["decided_at"],
        }}
    raise ValueError(f"Agent 工具未实现：{tool_name}")


def _safe_customer_snapshot(customer: dict | None) -> dict | None:
    if customer is None:
        return None
    allowed_fields = {
        "industry",
        "operating_years",
        "annual_revenue",
        "debt_ratio",
        "overdue_days_12m",
        "credit_grade",
    }
    return {key: value for key, value in customer.items() if key in allowed_fields}
