from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SubmissionPolicyDecision:
    allowed: bool
    requires_override: bool = False
    reasons: list[str] = field(default_factory=list)
    blocking_rule_ids: list[str] = field(default_factory=list)
    override_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "requires_override": self.requires_override,
            "reasons": self.reasons,
            "blocking_rule_ids": self.blocking_rule_ids,
            "override_reason": self.override_reason,
        }


class SubmissionPolicyError(Exception):
    def __init__(self, decision: SubmissionPolicyDecision):
        self.decision = decision
        super().__init__("提交审批未通过策略校验")


def evaluate_submission_policy(report: dict, override_reason: str | None = None) -> SubmissionPolicyDecision:
    findings = report.get("findings", [])
    materials = report.get("materials", {})
    blocking_findings = [item for item in findings if item.get("severity") == "block"]
    high_findings = [item for item in findings if item.get("severity") == "high"]
    reasons: list[str] = []
    blocking_rule_ids: list[str] = []

    if materials.get("missing"):
        labels = "、".join(item["label"] for item in materials["missing"])
        reasons.append(f"申请材料未齐全：{labels}。")
        blocking_rule_ids.append("MAT-1")

    if blocking_findings:
        reasons.extend(item["message"] for item in blocking_findings)
        blocking_rule_ids.extend(item["rule_id"] for item in blocking_findings)

    if blocking_rule_ids:
        return SubmissionPolicyDecision(False, False, reasons, blocking_rule_ids)

    if high_findings and not override_reason:
        reasons.extend(item["message"] for item in high_findings)
        return SubmissionPolicyDecision(False, True, reasons, [item["rule_id"] for item in high_findings])

    if high_findings:
        reasons.extend(item["message"] for item in high_findings)
        return SubmissionPolicyDecision(True, True, reasons, [item["rule_id"] for item in high_findings], override_reason)

    return SubmissionPolicyDecision(True, False, ["预审报告未命中提交拦截策略。"], [], override_reason)
