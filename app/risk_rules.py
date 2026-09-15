from __future__ import annotations

from dataclasses import dataclass

from app.domain import LoanApplication, PolicyRule
from app.rule_store import list_policy_rules


@dataclass(frozen=True)
class RiskRuleResult:
    rule_id: str
    policy_id: str | None
    result: str
    message: str
    severity: str

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "policy_id": self.policy_id,
            "result": self.result,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class PreReviewRuleDecision:
    findings: list[RiskRuleResult]
    suggested_max_amount: int
    requires_manual_review: bool

    @property
    def conclusion(self) -> str:
        return "需人工强化审查" if self.requires_manual_review else "建议进入人工审批"

    def findings_as_dicts(self) -> list[dict]:
        return [finding.to_dict() for finding in self.findings]

    @property
    def policy_evidence_ids(self) -> set[str]:
        return {finding.policy_id for finding in self.findings if finding.policy_id}


def evaluate_pre_review_rules(
    application: LoanApplication,
    customer: dict,
    materials: dict,
    rules: list[PolicyRule] | None = None,
) -> PreReviewRuleDecision:
    rules = rules if rules is not None else list_policy_rules()
    findings: list[RiskRuleResult] = []
    suggested_limits: list[int] = []

    def add(rule: PolicyRule, triggered: bool, context: dict | None = None) -> None:
        context = context or {}
        findings.append(RiskRuleResult(
            rule.id,
            rule.policy_id,
            rule.failure_result if triggered else "pass",
            (rule.failure_message if triggered else rule.pass_message).format_map(context),
            rule.severity if triggered else "info",
        ))

    for rule in rules:
        params = rule.parameters
        if rule.rule_type == "minimum":
            add(rule, float(customer[params["field"]]) < float(params["minimum"]))
            continue
        if rule.rule_type == "ratio_cap":
            limit = min(
                int(float(customer[params["base_field"]]) * float(params["ratio"])),
                int(params["absolute_cap"]),
            )
            suggested_limits.append(limit)
            add(rule, int(getattr(application, params["application_field"])) > limit, {"suggested_max_amount": limit})
            continue
        if rule.rule_type == "any_threshold":
            triggered = any(_compare(
                float(customer[condition["field"]]), condition["operator"], float(condition["value"]),
            ) for condition in params["conditions"])
            add(rule, triggered)
            continue
        if rule.rule_type == "required_materials":
            missing = materials.get("missing", [])
            add(rule, bool(missing), {"missing_labels": "、".join(item["label"] for item in missing)})

    suggested_max_amount = min(suggested_limits) if suggested_limits else 0

    return PreReviewRuleDecision(
        findings=findings,
        suggested_max_amount=suggested_max_amount,
        requires_manual_review=any(item.result != "pass" and item.severity in {"high", "block"} for item in findings),
    )


def _compare(left: float, operator: str, right: float) -> bool:
    return {
        "gt": left > right,
        "gte": left >= right,
        "lt": left < right,
        "lte": left <= right,
    }[operator]
