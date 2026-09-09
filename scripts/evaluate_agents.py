from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent_provider import AgentContext, provider_by_name
from app.evaluation import EvaluationCase, evaluate_provider


def cases() -> list[EvaluationCase]:
    standard = AgentContext(
        "APP-EVAL-001", "评测企业", 1_000_000, 5_000_000, "建议进入人工审批",
        [{"rule_id": "POL-2.1", "severity": "info", "message": "额度在政策范围内。"}],
        [{"id": "POL-2.1", "title": "流动资金贷款额度", "content": "额度规则", "version": "2026.01"}],
        True, [], [],
    )
    high_risk = AgentContext(
        "APP-EVAL-002", "高风险评测企业", 3_000_000, 1_000_000, "需人工强化审查",
        [{"rule_id": "POL-3.4", "severity": "high", "message": "存在逾期或高负债率。"}],
        [{"id": "POL-3.4", "title": "信用风险关注条件", "content": "风险规则", "version": "2026.01"}],
        True, [], [],
    )
    return [
        EvaluationCase("brief-standard", "generate_brief", standard, expected_terms=("评测企业", "人工审批"), expected_evidence_ids=("POL-2.1",)),
        EvaluationCase("brief-high-risk", "generate_brief", high_risk, expected_terms=("高风险评测企业", "人工强化审查"), expected_evidence_ids=("POL-3.4",)),
        EvaluationCase("answer-boundary", "answer_question", high_risk, "下一步怎么处理？", expected_terms=("补齐", "人工"), expected_evidence_ids=("POL-3.4",)),
    ]


if __name__ == "__main__":
    providers = [item.strip() for item in os.getenv("FINCREDIT_EVAL_PROVIDERS", "deterministic-local").split(",") if item.strip()]
    report = {name: evaluate_provider(provider_by_name(name), cases()) for name in providers}
    print(json.dumps({"suite": "fincredit-agent-evaluation", "providers": report}, ensure_ascii=False, indent=2))
