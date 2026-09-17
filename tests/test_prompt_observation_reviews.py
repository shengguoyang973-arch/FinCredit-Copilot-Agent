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


def create_final_human_outcome(monkeypatch) -> None:
    monkeypatch.setenv("FINCREDIT_PROMPT_OUTCOME_MIN_SAMPLES", "1")
    upload_required_materials()
    report = client.post("/v1/applications/APP001/pre-review", headers=RISK)
    assert report.status_code == 200
    submission = client.post("/v1/applications/APP001/submit", headers=RISK)
    assert submission.status_code == 200
    decision = client.post(
        f"/v1/approval-tasks/{submission.json()['approval_task']['id']}/decision",
        headers=APPROVER,
        json={"decision": "returned", "comment": "独立人工复核后要求补充尽调记录。"},
    )
    assert decision.status_code == 200


def test_prompt_observation_review_requires_outcomes_and_independent_acknowledgement(monkeypatch) -> None:
    unavailable = client.post(
        "/v1/observability/prompt-performance/generate_brief/v1/reviews",
        headers=AUTHOR,
        json={"recommendation": "investigate", "rationale": "没有人工工作流结果时不能发起复盘。"},
    )
    assert unavailable.status_code == 409

    create_final_human_outcome(monkeypatch)
    created = client.post(
        "/v1/observability/prompt-performance/generate_brief/v1/reviews",
        headers=AUTHOR,
        json={"recommendation": "rollback_recommended", "rationale": "人工复盘认为需要启动受控回滚评估，但不能自动变更版本。"},
    )
    assert created.status_code == 201
    review = created.json()["review"]
    assert review["status"] == "pending_review"
    assert review["snapshot"]["cohort"]["workflow_outcome_count"] == 1
    assert "APP001" not in str(review["snapshot"])

    self_decision = client.post(
        f"/v1/observability/prompt-performance/generate_brief/v1/reviews/{review['id']}/decision",
        headers=AUTHOR,
        json={"decision": "acknowledged", "comment": "创建人不得确认自己的复盘。"},
    )
    assert self_decision.status_code == 409
    wrong_path = client.post(
        f"/v1/observability/prompt-performance/answer_question/v1/reviews/{review['id']}/decision",
        headers=REVIEWER,
        json={"decision": "acknowledged", "comment": "错误路径不能处理另一个 Prompt 的复盘。"},
    )
    assert wrong_path.status_code == 404
    acknowledged = client.post(
        f"/v1/observability/prompt-performance/generate_brief/v1/reviews/{review['id']}/decision",
        headers=REVIEWER,
        json={"decision": "acknowledged", "comment": "独立确认观察快照、建议和人工决策边界。"},
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["review"]["status"] == "acknowledged"
    assert get_prompt("generate_brief").version == "v1"

    performance = client.get("/v1/observability/prompt-performance", headers=AUTHOR)
    cohort = next(item for item in performance.json()["cohorts"] if item["task"] == "generate_brief")
    assert cohort["observation_review"]["status"] == "acknowledged"
    listed = client.get("/v1/observability/prompt-performance/generate_brief/v1/reviews", headers=AUTHOR)
    assert listed.status_code == 200
    assert listed.json()["items"][0]["recommendation"] == "rollback_recommended"
