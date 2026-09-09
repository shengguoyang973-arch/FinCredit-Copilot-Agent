from app.domain import LoanApplication
from app.risk_rules import evaluate_pre_review_rules


def application(amount: int = 3_000_000) -> LoanApplication:
    return LoanApplication("APP-T", "C-T", amount, 12, "补充流动资金", "sales_001")


def customer(**overrides) -> dict:
    data = {
        "name": "测试企业",
        "operating_years": 6,
        "annual_revenue": 18_500_000,
        "debt_ratio": 0.52,
        "overdue_days_12m": 0,
    }
    data.update(overrides)
    return data


def materials(missing: list[dict] | None = None) -> dict:
    return {"missing": missing or [], "complete": not missing}


def test_pre_review_rules_pass_for_standard_case() -> None:
    decision = evaluate_pre_review_rules(application(), customer(), materials())
    assert decision.conclusion == "建议进入人工审批"
    assert decision.suggested_max_amount == 5_000_000
    assert [item.severity for item in decision.findings] == ["info", "info", "info", "info"]


def test_pre_review_rules_flag_amount_above_limit() -> None:
    decision = evaluate_pre_review_rules(application(900_000), customer(annual_revenue=2_000_000), materials())
    assert decision.conclusion == "需人工强化审查"
    assert decision.suggested_max_amount == 600_000
    assert any(item.rule_id == "POL-2.1" and item.severity == "high" for item in decision.findings)


def test_pre_review_rules_block_short_operating_history() -> None:
    decision = evaluate_pre_review_rules(application(), customer(operating_years=1), materials())
    assert decision.conclusion == "需人工强化审查"
    assert any(item.rule_id == "POL-1.2" and item.severity == "block" for item in decision.findings)


def test_pre_review_rules_flag_missing_materials() -> None:
    decision = evaluate_pre_review_rules(application(), customer(), materials([{"type": "bank_statement", "label": "银行流水"}]))
    assert any(item.rule_id == "MAT-1" and item.severity == "high" for item in decision.findings)
