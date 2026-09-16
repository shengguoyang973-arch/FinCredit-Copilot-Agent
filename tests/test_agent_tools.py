from app.agent_tools import ALLOWED_AGENT_TOOLS, execute_agent_tools
from app.data_platform import ingest_records
from app.domain import LoanApplication


def application() -> LoanApplication:
    return LoanApplication("APP001", "C001", 3_000_000, 12, "补充流动资金", "sales_001")


def test_agent_tools_are_read_only_and_allowlisted() -> None:
    results = execute_agent_tools(application(), "为什么这个申请风险高？")
    tool_names = [item["tool_name"] for item in results]
    assert set(tool_names).issubset(ALLOWED_AGENT_TOOLS)
    assert tool_names == [
        "get_application_snapshot", "get_canonical_customer_snapshot", "get_material_status", "get_policy_evidence"
    ]
    assert all(item["status"] == "success" for item in results)


def test_agent_tools_include_approval_status_for_process_questions() -> None:
    results = execute_agent_tools(application(), "下一步能不能提交审批？")
    tool_names = [item["tool_name"] for item in results]
    assert "get_approval_status" in tool_names


def test_agent_tool_context_excludes_document_preview_and_registration_number() -> None:
    results = execute_agent_tools(application())
    snapshot = next(item["result"] for item in results if item["tool_name"] == "get_application_snapshot")
    assert "masked_registration_no" not in snapshot["customer"]
    materials = next(item["result"] for item in results if item["tool_name"] == "get_material_status")
    assert all("extracted" not in document for document in materials["documents"])


def test_agent_can_read_minimized_canonical_customer_context() -> None:
    ingest_records(
        source_system="crm", contract_id="DC-CRM-CUSTOMER", organization_id="branch-shanghai", actor_id="compliance_001",
        records=[{
            "customer_id": "C001", "name": "华辰设备制造有限公司", "operating_years": 6,
            "annual_revenue": 18_500_000, "debt_ratio": 0.52, "industry": "通用设备制造",
        }],
    )
    results = execute_agent_tools(application())
    canonical = next(item["result"] for item in results if item["tool_name"] == "get_canonical_customer_snapshot")
    assert canonical["available"] is True
    assert canonical["source"] == "data_platform"
    assert canonical["fields"] == {
        "industry": "通用设备制造", "operating_years": 6, "annual_revenue": 18_500_000, "debt_ratio": 0.52,
    }
    assert "name" not in canonical["fields"]
