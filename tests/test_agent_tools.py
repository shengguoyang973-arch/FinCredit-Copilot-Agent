from app.agent_tools import ALLOWED_AGENT_TOOLS, execute_agent_tools
from app.domain import LoanApplication


def application() -> LoanApplication:
    return LoanApplication("APP001", "C001", 3_000_000, 12, "补充流动资金", "sales_001")


def test_agent_tools_are_read_only_and_allowlisted() -> None:
    results = execute_agent_tools(application(), "为什么这个申请风险高？")
    tool_names = [item["tool_name"] for item in results]
    assert set(tool_names).issubset(ALLOWED_AGENT_TOOLS)
    assert tool_names == ["get_application_snapshot", "get_material_status", "get_policy_evidence"]
    assert all(item["status"] == "success" for item in results)


def test_agent_tools_include_approval_status_for_process_questions() -> None:
    results = execute_agent_tools(application(), "下一步能不能提交审批？")
    tool_names = [item["tool_name"] for item in results]
    assert "get_approval_status" in tool_names
