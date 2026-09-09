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
from app.main import app  # noqa: E402

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
    assert input_snapshot["tool_names"] == ["get_application_snapshot", "get_material_status", "get_policy_evidence", "get_approval_status"]


def scenario_observability_metrics_track_agent_health() -> None:
    response = client.post("/v1/applications/APP002/agent-question", headers={"X-User-Id": "rm_001"}, json={"question": "下一步能不能提交审批？"})
    assert response.status_code == 200, response.text
    metrics = client.get("/v1/observability/agent-metrics", headers={"X-User-Id": "compliance_001"})
    assert metrics.status_code == 200, metrics.text
    body = metrics.json()
    assert body["total_runs"] >= 1
    assert body["average_duration_ms"] >= 0
    assert body["tool_counts"]["get_approval_status"] >= 1


SCENARIOS: tuple[tuple[str, Callable[[], None]], ...] = (
    ("rule_hits_for_high_risk_application", scenario_rule_hits_for_high_risk_application),
    ("unauthorized_actions_are_rejected", scenario_unauthorized_actions_are_rejected),
    ("missing_materials_block_submission", scenario_missing_materials_block_submission),
    ("high_risk_requires_override_reason", scenario_high_risk_requires_override_reason),
    ("agent_output_stays_within_governance_boundary", scenario_agent_output_stays_within_governance_boundary),
    ("business_question_is_answered_and_traced", scenario_business_question_is_answered_and_traced),
    ("observability_metrics_track_agent_health", scenario_observability_metrics_track_agent_health),
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
