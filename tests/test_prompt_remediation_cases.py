from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.prompt_registry import get_prompt


client = TestClient(app)
AUTHOR = {"X-User-Id": "compliance_001"}
REVIEWER = {"X-User-Id": "compliance_002"}
RISK = {"X-User-Id": "rm_001"}
APPROVER = {"X-User-Id": "approver_001"}


def upload_required_materials() -> None:
    for document_type, content in {
        "business_license": "企业名称：华辰设备制造有限公司\n统一社会信用代码：91310000123456789X",
        "financial_statement": "营业收入：18500000\n资产负债率：52%",
        "bank_statement": "账户余额：2600000",
    }.items():
        response = client.put(
            f"/v1/applications/APP001/materials/{document_type}",
            headers={"X-User-Id": "sales_001", "X-Filename": f"{document_type}.txt", "Content-Type": "text/plain"},
            content=content.encode(),
        )
        assert response.status_code == 201


def create_acknowledged_review(monkeypatch) -> dict:
    monkeypatch.setenv("FINCREDIT_PROMPT_OUTCOME_MIN_SAMPLES", "1")
    upload_required_materials()
    assert client.post("/v1/applications/APP001/pre-review", headers=RISK).status_code == 200
    task_id = client.post("/v1/applications/APP001/submit", headers=RISK).json()["approval_task"]["id"]
    assert client.post(
        f"/v1/approval-tasks/{task_id}/decision", headers=APPROVER,
        json={"decision": "returned", "comment": "独立人工复核后要求补充尽调记录。"},
    ).status_code == 200
    review = client.post(
        "/v1/observability/prompt-performance/generate_brief/v1/reviews", headers=AUTHOR,
        json={"recommendation": "rollback_recommended", "rationale": "需要创建受控处置作业单并评估回滚草稿。"},
    )
    assert review.status_code == 201
    review_id = review.json()["review"]["id"]
    acknowledged = client.post(
        f"/v1/observability/prompt-performance/generate_brief/v1/reviews/{review_id}/decision",
        headers=REVIEWER,
        json={"decision": "acknowledged", "comment": "独立确认处置作业单应进入人工执行。"},
    )
    assert acknowledged.status_code == 200
    return acknowledged.json()["review"]


def test_prompt_remediation_case_is_owned_auditable_and_never_auto_rolls_back(monkeypatch) -> None:
    review = create_acknowledged_review(monkeypatch)
    due_date = (date.today() + timedelta(days=1)).isoformat()
    invalid_owner = client.post(
        f"/v1/observability/prompt-performance/generate_brief/v1/reviews/{review['id']}/remediation-cases",
        headers=AUTHOR,
        json={"owner_id": "sales_001", "due_date": due_date},
    )
    assert invalid_owner.status_code == 422
    created = client.post(
        f"/v1/observability/prompt-performance/generate_brief/v1/reviews/{review['id']}/remediation-cases",
        headers=AUTHOR,
        json={"owner_id": "compliance_001", "due_date": due_date},
    )
    assert created.status_code == 201
    item = created.json()["case"]
    assert item["status"] == "open"
    assert item["owner_id"] == "compliance_001"
    assert item["due_state"] == "on_track"

    duplicate = client.post(
        f"/v1/observability/prompt-performance/generate_brief/v1/reviews/{review['id']}/remediation-cases",
        headers=AUTHOR,
        json={"owner_id": "compliance_001", "due_date": due_date},
    )
    assert duplicate.status_code == 409
    non_owner = client.post(
        f"/v1/observability/prompt-remediation-cases/{item['id']}/status", headers=REVIEWER,
        json={"status": "in_progress", "comment": "非负责人不应推进作业单。"},
    )
    assert non_owner.status_code == 403
    in_progress = client.post(
        f"/v1/observability/prompt-remediation-cases/{item['id']}/status", headers=AUTHOR,
        json={"status": "in_progress", "comment": "开始执行脱敏回放与受控回滚评估。"},
    )
    assert in_progress.status_code == 200
    invalid_resolution = client.post(
        f"/v1/observability/prompt-remediation-cases/{item['id']}/status", headers=AUTHOR,
        json={"status": "resolved", "comment": "没有结论参考编号时不得关闭。"},
    )
    assert invalid_resolution.status_code == 422
    resolved = client.post(
        f"/v1/observability/prompt-remediation-cases/{item['id']}/status", headers=AUTHOR,
        json={
            "status": "resolved", "comment": "已创建供四眼复核的回滚草稿并完成脱敏回放。",
            "resolution_type": "rollback_draft_created", "resolution_reference": "RB-v2",
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["case"]["status"] == "resolved"
    assert get_prompt("generate_brief").version == "v1"

    events = client.get(f"/v1/observability/prompt-remediation-cases/{item['id']}/events", headers=REVIEWER)
    assert events.status_code == 200
    assert [event["to_status"] for event in events.json()["items"]] == ["open", "in_progress", "resolved"]
    listed = client.get("/v1/observability/prompt-remediation-cases", headers=REVIEWER)
    assert listed.status_code == 200
    assert listed.json()["summary"]["open"] == 0
    performance = client.get("/v1/observability/prompt-performance", headers=REVIEWER)
    cohort = next(item for item in performance.json()["cohorts"] if item["task"] == "generate_brief")
    assert cohort["remediation_case"]["status"] == "resolved"
