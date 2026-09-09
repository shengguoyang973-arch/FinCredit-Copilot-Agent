from app.approval_policy import evaluate_submission_policy


def base_report(findings: list[dict], missing: list[dict] | None = None) -> dict:
    return {"findings": findings, "materials": {"missing": missing or [], "complete": not missing}}


def test_submission_policy_blocks_missing_materials() -> None:
    decision = evaluate_submission_policy(base_report([], [{"type": "bank_statement", "label": "银行流水"}]))
    assert decision.allowed is False
    assert decision.requires_override is False
    assert decision.blocking_rule_ids == ["MAT-1"]


def test_submission_policy_blocks_hard_rules_even_with_override() -> None:
    report = base_report([{"rule_id": "POL-1.2", "message": "企业持续经营不足两年。", "severity": "block"}])
    decision = evaluate_submission_policy(report, "业务部门已复核并要求继续提交。")
    assert decision.allowed is False
    assert decision.requires_override is False
    assert decision.blocking_rule_ids == ["POL-1.2"]


def test_submission_policy_requires_override_for_high_risk() -> None:
    report = base_report([{"rule_id": "POL-3.4", "message": "存在逾期或高负债率。", "severity": "high"}])
    decision = evaluate_submission_policy(report)
    assert decision.allowed is False
    assert decision.requires_override is True
    assert decision.blocking_rule_ids == ["POL-3.4"]


def test_submission_policy_allows_high_risk_with_override_reason() -> None:
    report = base_report([{"rule_id": "POL-3.4", "message": "存在逾期或高负债率。", "severity": "high"}])
    decision = evaluate_submission_policy(report, "风险经理已核验补充材料并记录人工覆盖理由。")
    assert decision.allowed is True
    assert decision.requires_override is True
    assert decision.override_reason == "风险经理已核验补充材料并记录人工覆盖理由。"
