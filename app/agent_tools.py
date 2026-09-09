from __future__ import annotations

from app.document_store import material_check
from app.knowledge_store import get_policies
from app.repository import get_customer
from app.risk_rules import POLICY_EVIDENCE_IDS
from app.workflow_store import get_approval_task

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
            "application": application.__dict__,
            "customer": customer,
        }
    if tool_name == "get_material_status":
        return material_check(application.id)
    if tool_name == "get_policy_evidence":
        return {"policy_ids": [policy.id for policy in get_policies(POLICY_EVIDENCE_IDS)]}
    if tool_name == "get_approval_status":
        task = get_approval_task(f"APR-{application.id}")
        return {"task": task}
    raise ValueError(f"Agent 工具未实现：{tool_name}")
