from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TEMP_DATA_DIR = Path(tempfile.mkdtemp(prefix="fincredit-quality-"))
os.environ["FINCREDIT_DATA_DIR"] = str(TEMP_DATA_DIR)

from fastapi.testclient import TestClient  # noqa: E402

from app.approval_policy import evaluate_submission_policy  # noqa: E402
from app.config import Settings, validate_settings  # noqa: E402
from app.domain import LoanApplication, Role, User  # noqa: E402
from app.main import app  # noqa: E402
from app.repository import USERS  # noqa: E402
from app.risk_rules import evaluate_pre_review_rules  # noqa: E402
from app.rule_store import list_policy_rules  # noqa: E402
from app.state_store import verify_audit_chain  # noqa: E402

client = TestClient(app)


def upload_required_materials(application_id: str = "APP001") -> None:
    documents = {
        "business_license": "企业名称：华辰设备制造有限公司\n统一社会信用代码：91310000123456789X",
        "financial_statement": "营业收入：18500000\n资产负债率：52%",
        "bank_statement": "账户余额：2600000",
    }
    for document_type, content in documents.items():
        response = client.put(
            f"/v1/applications/{application_id}/materials/{document_type}",
            headers={"X-User-Id": "sales_001", "X-Filename": f"{document_type}.txt", "Content-Type": "text/plain"},
            content=content.encode("utf-8"),
        )
        assert response.status_code == 201, response.text


def scenario_rule_hits_for_high_risk_application() -> None:
    response = client.post("/v1/applications/APP002/pre-review", headers={"X-User-Id": "rm_001"})
    assert response.status_code == 200, response.text
    body = response.json()
    findings = {item["rule_id"]: item for item in body["findings"]}
    assert findings["POL-1.2"]["severity"] == "block"
    assert findings["POL-3.4"]["severity"] == "high"
    assert body["conclusion"] == "需人工强化审查"


def scenario_unauthorized_actions_are_rejected() -> None:
    pre_review = client.post("/v1/applications/APP001/pre-review", headers={"X-User-Id": "sales_001"})
    assert pre_review.status_code == 403, pre_review.text
    decision = client.post(
        "/v1/approval-tasks/APR-APP001/decision",
        headers={"X-User-Id": "rm_001"},
        json={"decision": "approved", "comment": "无权审批"},
    )
    assert decision.status_code == 403, decision.text


def scenario_missing_materials_block_submission() -> None:
    response = client.post("/v1/applications/APP001/pre-review", headers={"X-User-Id": "rm_001"})
    assert response.status_code == 200, response.text
    submission = client.post("/v1/applications/APP001/submit", headers={"X-User-Id": "rm_001"})
    assert submission.status_code == 409, submission.text
    policy = submission.json()["detail"]["submission_policy"]
    assert policy["allowed"] is False
    assert "MAT-1" in policy["blocking_rule_ids"]


def scenario_high_risk_requires_override_reason() -> None:
    report = {
        "findings": [{"rule_id": "POL-3.4", "message": "存在逾期或高负债率。", "severity": "high"}],
        "materials": {"missing": [], "complete": True},
    }
    blocked = evaluate_submission_policy(report)
    allowed = evaluate_submission_policy(report, "风险经理已核验补充材料并记录人工覆盖理由。")
    assert blocked.allowed is False
    assert blocked.requires_override is True
    assert allowed.allowed is True
    assert allowed.override_reason


def scenario_agent_output_stays_within_governance_boundary() -> None:
    upload_required_materials()
    response = client.post("/v1/applications/APP001/pre-review", headers={"X-User-Id": "rm_001"})
    assert response.status_code == 200, response.text
    brief = response.json()["agent_brief"]
    combined_output = json.dumps(brief, ensure_ascii=False)
    assert brief["provider"] == "deterministic-local"
    assert "不自动批准" in brief["governance_note"]
    assert "批准该笔授信" not in combined_output
    assert "拒绝该笔授信" not in combined_output


def scenario_business_question_is_answered_and_traced() -> None:
    response = client.post("/v1/applications/APP002/agent-question", headers={"X-User-Id": "rm_001"}, json={"question": "为什么这个申请不能提交？"})
    assert response.status_code == 200, response.text
    answer = response.json()["answer"]
    assert answer["run_id"].startswith("AGT-")
    assert "不能替代人工审批" in answer["governance_note"]
    runs = client.get("/v1/applications/APP002/agent-runs", headers={"X-User-Id": "compliance_001"})
    assert runs.status_code == 200, runs.text
    input_snapshot = runs.json()["items"][0]["input_snapshot"]
    assert input_snapshot["task"] == "answer_question"
    assert input_snapshot["tool_names"] == [
        "get_application_snapshot", "get_canonical_customer_snapshot", "get_material_status",
        "get_policy_evidence", "get_approval_status",
    ]
    assert input_snapshot["task_plan"]["version"] == "v2"
    assert all(step["status"] == "completed" for step in input_snapshot["plan_execution"])
    governance = input_snapshot["context_governance"]
    assert governance["used_chars"] <= governance["max_chars"]


def scenario_human_feedback_is_traced_and_measured() -> None:
    response = client.post(
        "/v1/applications/APP001/agent-question", headers={"X-User-Id": "rm_001"},
        json={"question": "下一步如何处理？"},
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["answer"]["run_id"]
    feedback = client.post(
        f"/v1/applications/APP001/agent-runs/{run_id}/feedback", headers={"X-User-Id": "rm_001"},
        json={"verdict": "needs_revision", "category": "evidence", "comment": "需要补充对应的政策条款依据。"},
    )
    assert feedback.status_code == 201, feedback.text
    history = client.get(
        f"/v1/applications/APP001/agent-runs/{run_id}/feedback", headers={"X-User-Id": "compliance_001"},
    )
    assert history.status_code == 200, history.text
    assert history.json()["items"][0]["content_hash"]
    metrics = client.get("/v1/observability/online-evaluation", headers={"X-User-Id": "compliance_001"})
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["observed"]["feedback_count"] >= 1


def scenario_observability_metrics_track_agent_health() -> None:
    response = client.post("/v1/applications/APP002/agent-question", headers={"X-User-Id": "rm_001"}, json={"question": "下一步能不能提交审批？"})
    assert response.status_code == 200, response.text
    metrics = client.get("/v1/observability/agent-metrics", headers={"X-User-Id": "compliance_001"})
    assert metrics.status_code == 200, metrics.text
    body = metrics.json()
    assert body["total_runs"] >= 1
    assert body["average_duration_ms"] >= 0
    assert body["tool_counts"]["get_approval_status"] >= 1


def scenario_approval_separation_of_duties() -> None:
    USERS["quality_dual_001"] = User(
        "quality_dual_001",
        "质量门禁双重角色",
        {Role.RISK_MANAGER, Role.APPROVER},
        "branch-shanghai",
    )
    try:
        upload_required_materials()
        headers = {"X-User-Id": "quality_dual_001"}
        review = client.post("/v1/applications/APP001/pre-review", headers=headers)
        assert review.status_code == 200, review.text
        submission = client.post("/v1/applications/APP001/submit", headers=headers)
        assert submission.status_code == 200, submission.text
        task_id = submission.json()["approval_task"]["id"]
        decision = client.post(
            f"/v1/approval-tasks/{task_id}/decision",
            headers=headers,
            json={"decision": "approved", "comment": "同一用户不应完成最终审批。"},
        )
        assert decision.status_code == 409, decision.text
        assert "职责分离" in decision.json()["detail"]
    finally:
        USERS.pop("quality_dual_001", None)


def scenario_audit_chain_is_verifiable() -> None:
    integrity = verify_audit_chain()
    assert integrity["valid"] is True
    assert integrity["event_count"] > 0


def scenario_policy_rule_four_eyes_lifecycle() -> None:
    body = {
        "id": "POL-2.1", "policy_id": "POL-2.1", "version": "quality-2026.02",
        "rule_type": "ratio_cap",
        "parameters": {"application_field": "requested_amount", "base_field": "annual_revenue", "ratio": 0.10, "absolute_cap": 5_000_000},
        "severity": "high", "failure_result": "fail",
        "failure_message": "申请额度超出建议上限 {suggested_max_amount:,} 元。",
        "pass_message": "申请额度未超过建议上限 {suggested_max_amount:,} 元。",
        "effective_date": "2026-02-01", "source_name": "quality-gate",
    }
    response = client.post("/v1/knowledge/rules", headers={"X-User-Id": "compliance_001"}, json=body)
    assert response.status_code == 201, response.text
    submission = client.post(
        "/v1/knowledge/rules/POL-2.1/versions/quality-2026.02/submit",
        headers={"X-User-Id": "compliance_001"},
    )
    assert submission.status_code == 200, submission.text
    decision_response = client.post(
        "/v1/knowledge/rules/POL-2.1/versions/quality-2026.02/decision",
        headers={"X-User-Id": "compliance_002"},
        json={"decision": "approved", "comment": "质量门禁独立复核规则阈值与回放结果。"},
    )
    assert decision_response.status_code == 200, decision_response.text
    decision = evaluate_pre_review_rules(
        LoanApplication("APP-QUALITY", "C-QUALITY", 300_000, 12, "流动资金", "sales_001"),
        {"operating_years": 6, "annual_revenue": 2_000_000, "debt_ratio": 0.2, "overdue_days_12m": 0},
        {"missing": []},
        list_policy_rules(),
    )
    assert decision.suggested_max_amount == 200_000
    assert any(item.rule_id == "POL-2.1" and item.result == "fail" for item in decision.findings)


def scenario_prompt_four_eyes_lifecycle() -> None:
    active = client.get("/v1/knowledge/prompts", headers={"X-User-Id": "compliance_001"})
    assert active.status_code == 200, active.text
    baseline = next(item for item in active.json()["items"] if item["task"] == "answer_question")
    draft = client.post(
        "/v1/knowledge/prompts", headers={"X-User-Id": "compliance_001"},
        json={
            "task": "answer_question", "version": "v2",
            "content": baseline["content"] + "回答时应清楚区分政策证据与人工后续动作。",
            "feedback_ids": [], "rationale": "质量门禁验证 Prompt 四眼发布与运行时版本追踪。",
        },
    )
    assert draft.status_code == 201, draft.text
    submitted = client.post(
        "/v1/knowledge/prompts/answer_question/versions/v2/submit", headers={"X-User-Id": "compliance_001"},
    )
    assert submitted.status_code == 200, submitted.text
    approved = client.post(
        "/v1/knowledge/prompts/answer_question/versions/v2/decision",
        headers={"X-User-Id": "compliance_002"},
        json={"decision": "approved", "comment": "已独立复核输出约束与人工决策边界。"},
    )
    assert approved.status_code == 200, approved.text
    answer = client.post(
        "/v1/applications/APP001/agent-question", headers={"X-User-Id": "rm_001"},
        json={"question": "下一步如何处理？"},
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["answer"]["prompt_version"] == "v2"


def scenario_production_runtime_fails_closed() -> None:
    errors = validate_settings(Settings(deployment_environment="production", identity_provider="demo-header"))
    assert "生产环境禁止使用 demo-header 身份提供方" in errors
    assert "生产环境必须使用 openai Embedding Provider" in errors
    assert "生产环境必须使用 pgvector 向量数据库" in errors


SCENARIOS: tuple[tuple[str, Callable[[], None]], ...] = (
    ("rule_hits_for_high_risk_application", scenario_rule_hits_for_high_risk_application),
    ("unauthorized_actions_are_rejected", scenario_unauthorized_actions_are_rejected),
    ("missing_materials_block_submission", scenario_missing_materials_block_submission),
    ("high_risk_requires_override_reason", scenario_high_risk_requires_override_reason),
    ("agent_output_stays_within_governance_boundary", scenario_agent_output_stays_within_governance_boundary),
    ("business_question_is_answered_and_traced", scenario_business_question_is_answered_and_traced),
    ("human_feedback_is_traced_and_measured", scenario_human_feedback_is_traced_and_measured),
    ("observability_metrics_track_agent_health", scenario_observability_metrics_track_agent_health),
    ("approval_separation_of_duties", scenario_approval_separation_of_duties),
    ("policy_rule_four_eyes_lifecycle", scenario_policy_rule_four_eyes_lifecycle),
    ("prompt_four_eyes_lifecycle", scenario_prompt_four_eyes_lifecycle),
    ("production_runtime_fails_closed", scenario_production_runtime_fails_closed),
    ("audit_chain_is_verifiable", scenario_audit_chain_is_verifiable),
)


def main() -> int:
    results = []
    for name, scenario in SCENARIOS:
        try:
            scenario()
        except AssertionError as error:
            results.append({"name": name, "status": "failed", "detail": str(error)})
        else:
            results.append({"name": name, "status": "passed"})
    passed = sum(item["status"] == "passed" for item in results)
    output = {
        "suite": "fincredit-agent-quality-gate",
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["failed"] == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        shutil.rmtree(TEMP_DATA_DIR, ignore_errors=True)
