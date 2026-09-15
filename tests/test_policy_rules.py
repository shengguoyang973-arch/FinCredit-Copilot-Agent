from fastapi.testclient import TestClient

from app.domain import LoanApplication, PolicyRule
from app.document_store import material_check
from app.main import app
from app.risk_rules import evaluate_pre_review_rules
from app.rule_store import list_policy_rules, save_policy_rule


client = TestClient(app)


def revised_amount_rule(ratio: float = 0.10) -> PolicyRule:
    return PolicyRule(
        "POL-2.1", "POL-2.1", "2026.02", "ratio_cap",
        {"application_field": "requested_amount", "base_field": "annual_revenue", "ratio": ratio, "absolute_cap": 5_000_000},
        "high", "fail", "申请额度超出建议上限 {suggested_max_amount:,} 元。",
        "申请额度未超过建议上限 {suggested_max_amount:,} 元。", "2026-02-01", "test-policy-rules",
    )


def test_rule_version_switches_active_threshold_without_code_change() -> None:
    save_policy_rule(revised_amount_rule())
    application = LoanApplication("APP-T", "C-T", 300_000, 12, "流动资金", "sales_001")
    customer = {"operating_years": 6, "annual_revenue": 2_000_000, "debt_ratio": 0.2, "overdue_days_12m": 0}
    decision = evaluate_pre_review_rules(application, customer, {"missing": []})
    assert decision.suggested_max_amount == 200_000
    assert any(item.rule_id == "POL-2.1" and item.result == "fail" for item in decision.findings)
    versions = [rule.version for rule in list_policy_rules(active_only=False) if rule.id == "POL-2.1"]
    assert versions == ["2026.02", "2026.01"]


def test_compliance_api_imports_and_audits_rule_version() -> None:
    rule = revised_amount_rule(0.20)
    body = {
        "id": rule.id, "policy_id": rule.policy_id, "version": rule.version,
        "rule_type": rule.rule_type, "parameters": rule.parameters, "severity": rule.severity,
        "failure_result": rule.failure_result, "failure_message": rule.failure_message,
        "pass_message": rule.pass_message, "effective_date": rule.effective_date,
        "source_name": rule.source_name,
    }
    response = client.post("/v1/knowledge/rules", headers={"X-User-Id": "compliance_001"}, json=body)
    assert response.status_code == 201
    listing = client.get("/v1/knowledge/rules?include_inactive=true", headers={"X-User-Id": "rm_001"})
    assert listing.status_code == 200
    versions = [(item["version"], item["is_active"]) for item in listing.json()["items"] if item["id"] == "POL-2.1"]
    assert versions == [("2026.02", True), ("2026.01", False)]
    events = client.get("/v1/audit-events", headers={"X-User-Id": "compliance_001"})
    assert any(event["action"] == "policy_rule_imported" and event["resource_id"] == "POL-2.1" for event in events.json())


def test_only_compliance_admin_can_import_rule() -> None:
    rule = revised_amount_rule()
    response = client.post("/v1/knowledge/rules", headers={"X-User-Id": "rm_001"}, json={
        "id": rule.id, "policy_id": rule.policy_id, "version": rule.version,
        "rule_type": rule.rule_type, "parameters": rule.parameters, "severity": rule.severity,
        "failure_result": rule.failure_result, "failure_message": rule.failure_message,
        "pass_message": rule.pass_message, "effective_date": rule.effective_date, "source_name": rule.source_name,
    })
    assert response.status_code == 403


def test_required_materials_are_driven_by_active_rule() -> None:
    save_policy_rule(PolicyRule(
        "MAT-1", None, "2026.02", "required_materials",
        {"required": {"business_license": "营业执照"}},
        "high", "review", "缺少以下材料：{missing_labels}。", "材料齐全。",
        "2026-02-01", "test-policy-rules",
    ))
    status = material_check("APP001")
    assert status["missing"] == [{"type": "business_license", "label": "营业执照"}]


def test_rule_import_rejects_unapproved_field_and_placeholder() -> None:
    invalid = revised_amount_rule()
    invalid = PolicyRule(
        invalid.id, invalid.policy_id, invalid.version, invalid.rule_type,
        invalid.parameters | {"base_field": "name"}, invalid.severity,
        invalid.failure_result, "{unknown}", invalid.pass_message,
        invalid.effective_date, invalid.source_name,
    )
    with __import__("pytest").raises(ValueError):
        save_policy_rule(invalid)
