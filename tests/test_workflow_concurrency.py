from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.main import app
from app.workflow_store import decide_approval_task, get_approval_task

client = TestClient(app)


def _prepare_pending_task() -> str:
    documents = {
        "business_license": "企业名称：华辰设备制造有限公司\n统一社会信用代码：91310000123456789X",
        "financial_statement": "营业收入：18500000\n资产负债率：52%",
        "bank_statement": "账户余额：2600000",
    }
    for document_type, content in documents.items():
        response = client.put(
            f"/v1/applications/APP001/materials/{document_type}",
            headers={
                "X-User-Id": "sales_001",
                "X-Filename": f"{document_type}.txt",
                "Content-Type": "text/plain",
            },
            content=content.encode("utf-8"),
        )
        assert response.status_code == 201
    assert client.post(
        "/v1/applications/APP001/pre-review", headers={"X-User-Id": "rm_001"}
    ).status_code == 200
    response = client.post("/v1/applications/APP001/submit", headers={"X-User-Id": "rm_001"})
    assert response.status_code == 200
    return response.json()["approval_task"]["id"]


def test_only_one_concurrent_approval_decision_commits() -> None:
    task_id = _prepare_pending_task()

    def decide(approver_id: str) -> str:
        try:
            decide_approval_task(task_id, "approved", approver_id, "并发审批一致性测试。")
        except ValueError:
            return "conflict"
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(decide, ("approver_parallel_1", "approver_parallel_2")))

    assert sorted(outcomes) == ["committed", "conflict"]
    task = get_approval_task(task_id)
    assert task is not None
    assert task["status"] == "approved"
    assert task["decided_by"] in {"approver_parallel_1", "approver_parallel_2"}
