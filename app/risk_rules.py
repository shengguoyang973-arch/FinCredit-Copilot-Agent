from __future__ import annotations

from dataclasses import dataclass

from app.domain import LoanApplication

POLICY_EVIDENCE_IDS = {"POL-1.2", "POL-2.1", "POL-3.4"}


@dataclass(frozen=True)
class RiskRuleResult:
    rule_id: str
    result: str
    message: str
    severity: str

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
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


def evaluate_pre_review_rules(application: LoanApplication, customer: dict, materials: dict) -> PreReviewRuleDecision:
    findings: list[RiskRuleResult] = []
    suggested_max_amount = min(int(customer["annual_revenue"] * 0.30), 5_000_000)

    def add(rule_id: str, result: str, message: str, severity: str) -> None:
        findings.append(RiskRuleResult(rule_id, result, message, severity))

    if customer["operating_years"] < 2:
        add("POL-1.2", "fail", "企业持续经营不足两年，不满足基础准入要求。", "block")
    else:
        add("POL-1.2", "pass", "企业持续经营年限满足准入要求。", "info")

    if application.requested_amount > suggested_max_amount:
        add("POL-2.1", "fail", f"申请额度超出建议上限 {suggested_max_amount:,} 元。", "high")
    else:
        add("POL-2.1", "pass", f"申请额度未超过建议上限 {suggested_max_amount:,} 元。", "info")

    if customer["overdue_days_12m"] > 10 or customer["debt_ratio"] > 0.75:
        add("POL-3.4", "review", "存在逾期或高负债率，必须人工强化审查。", "high")
    else:
        add("POL-3.4", "pass", "未触发逾期与高负债率人工强化审查条件。", "info")

    if materials["missing"]:
        labels = "、".join(item["label"] for item in materials["missing"])
        add("MAT-1", "review", f"缺少以下材料：{labels}，须补齐后由人工复核。", "high")
    else:
        add("MAT-1", "pass", "必需材料已齐全。", "info")

    return PreReviewRuleDecision(
        findings=findings,
        suggested_max_amount=suggested_max_amount,
        requires_manual_review=any(item.severity in {"high", "block"} for item in findings),
    )
