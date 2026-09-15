from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import database, rule_store
from app.domain import LoanApplication, PolicyRule
from app.document_store import material_check
from app.main import app
from app.risk_rules import evaluate_pre_review_rules
from app.rule_store import (
    create_policy_rule_draft,
    decide_policy_rule,
    list_policy_rules,
    save_policy_rule,
    submit_policy_rule,
)
from app.state_store import list_audit_events, verify_audit_chain


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


def rule_body(rule: PolicyRule) -> dict:
    return {
        "id": rule.id, "policy_id": rule.policy_id, "version": rule.version,
        "rule_type": rule.rule_type, "parameters": rule.parameters, "severity": rule.severity,
        "failure_result": rule.failure_result, "failure_message": rule.failure_message,
        "pass_message": rule.pass_message, "effective_date": rule.effective_date,
        "source_name": rule.source_name,
    }


def test_compliance_api_enforces_four_eyes_and_audits_lifecycle() -> None:
    rule = revised_amount_rule(0.20)
    response = client.post("/v1/knowledge/rules", headers={"X-User-Id": "compliance_001"}, json=rule_body(rule))
    assert response.status_code == 201
    assert response.json()["rule"]["status"] == "draft"
    assert len(response.json()["rule"]["content_hash"]) == 64
    difference = client.get(
        "/v1/knowledge/rules/POL-2.1/versions/2026.02/diff",
        headers={"X-User-Id": "compliance_002"},
    )
    assert difference.status_code == 200
    assert difference.json()["baseline_version"] == "2026.01"
    assert difference.json()["content_hash_valid"] is True
    assert difference.json()["changes"]["parameters"]["to"]["ratio"] == 0.20
    submitted = client.post(
        "/v1/knowledge/rules/POL-2.1/versions/2026.02/submit",
        headers={"X-User-Id": "compliance_001"},
    )
    assert submitted.status_code == 200
    own_decision = client.post(
        "/v1/knowledge/rules/POL-2.1/versions/2026.02/decision",
        headers={"X-User-Id": "compliance_001"},
        json={"decision": "approved", "comment": "作者不能自行通过该规则。"},
    )
    assert own_decision.status_code == 409
    approved = client.post(
        "/v1/knowledge/rules/POL-2.1/versions/2026.02/decision",
        headers={"X-User-Id": "compliance_002"},
        json={"decision": "approved", "comment": "已独立复核阈值、依据和回放结果。"},
    )
    assert approved.status_code == 200
    assert approved.json()["rule"]["status"] == "active"
    listing = client.get("/v1/knowledge/rules?include_inactive=true", headers={"X-User-Id": "rm_001"})
    assert listing.status_code == 200
    versions = [(item["version"], item["is_active"]) for item in listing.json()["items"] if item["id"] == "POL-2.1"]
    assert versions == [("2026.02", True), ("2026.01", False)]
    events = client.get("/v1/audit-events", headers={"X-User-Id": "compliance_001"})
    actions = {event["action"] for event in events.json() if event["resource_id"] == "POL-2.1"}
    assert {"policy_rule_draft_created", "policy_rule_submitted", "policy_rule_approved"}.issubset(actions)


def test_only_compliance_admin_can_import_rule() -> None:
    rule = revised_amount_rule()
    response = client.post("/v1/knowledge/rules", headers={"X-User-Id": "rm_001"}, json=rule_body(rule))
    assert response.status_code == 403


def test_future_rule_is_scheduled_and_activates_on_effective_date() -> None:
    future_rule = revised_amount_rule(0.20)
    future_rule = PolicyRule(
        future_rule.id, future_rule.policy_id, "2027.01", future_rule.rule_type,
        future_rule.parameters, future_rule.severity, future_rule.failure_result,
        future_rule.failure_message, future_rule.pass_message, "2027-01-01", future_rule.source_name,
    )
    create_policy_rule_draft(future_rule, "compliance_001")
    submit_policy_rule(future_rule.id, future_rule.version, "compliance_001")
    scheduled = decide_policy_rule(
        future_rule.id, future_rule.version, "compliance_002", "approved",
        "已复核，按计划日期生效。", today=date(2026, 9, 15),
    )
    assert scheduled.status == "scheduled"
    assert next(rule for rule in list_policy_rules(as_of_date=date(2026, 12, 31)) if rule.id == "POL-2.1").version == "2026.01"
    activated = next(rule for rule in list_policy_rules(as_of_date=date(2027, 1, 1)) if rule.id == "POL-2.1")
    assert activated.version == "2027.01"
    assert activated.status == "active"
    assert any(event.action == "policy_rule_scheduled_activated" for event in list_audit_events())
    assert verify_audit_chain()["valid"] is True


def test_rollback_creates_new_draft_and_does_not_bypass_review() -> None:
    rollback = client.post(
        "/v1/knowledge/rules/POL-2.1/rollback",
        headers={"X-User-Id": "compliance_001"},
        json={
            "target_version": "2026.01", "new_version": "2026.01-r1",
            "effective_date": "2026-09-15", "reason": "回退到已验证的原始阈值。",
        },
    )
    assert rollback.status_code == 201
    assert rollback.json()["rule"]["status"] == "draft"
    active = next(rule for rule in list_policy_rules() if rule.id == "POL-2.1")
    assert active.version == "2026.01"


def test_rule_content_hash_blocks_tampered_pending_version() -> None:
    rule = revised_amount_rule()
    create_policy_rule_draft(rule, "compliance_001")
    submit_policy_rule(rule.id, rule.version, "compliance_001")
    with database.connection() as connection:
        connection.execute(
            "UPDATE policy_rules SET severity = 'medium' WHERE id = ? AND version = ?",
            (rule.id, rule.version),
        )
    with pytest.raises(ValueError, match="内容哈希不匹配"):
        decide_policy_rule(
            rule.id, rule.version, "compliance_002", "approved", "已完成独立复核。",
        )


def test_rule_state_rolls_back_when_transactional_audit_fails(monkeypatch) -> None:
    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(rule_store, "audit_in_transaction", fail_audit)
    rule = revised_amount_rule()
    with pytest.raises(RuntimeError, match="audit unavailable"):
        create_policy_rule_draft(rule, "compliance_001")
    with database.connection() as connection:
        stored = connection.execute(
            "SELECT 1 FROM policy_rules WHERE id = ? AND version = ?", (rule.id, rule.version),
        ).fetchone()
    assert stored is None


def test_rule_api_rejects_impossible_effective_date() -> None:
    body = rule_body(revised_amount_rule()) | {"effective_date": "2026-13-40"}
    response = client.post("/v1/knowledge/rules", headers={"X-User-Id": "compliance_001"}, json=body)
    assert response.status_code == 422


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
    with pytest.raises(ValueError):
        save_policy_rule(invalid)
