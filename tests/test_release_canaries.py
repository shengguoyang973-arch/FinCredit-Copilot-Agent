from fastapi.testclient import TestClient

from app.main import app
from app.prompt_registry import get_prompt


client = TestClient(app)
AUTHOR = {"X-User-Id": "compliance_001"}
REVIEWER = {"X-User-Id": "compliance_002"}


def test_deidentified_canary_requires_four_eyes_and_never_auto_activates() -> None:
    created = client.post("/v1/release-canaries", headers=AUTHOR, json={
        "name": "v13-deid-canary", "candidate_provider": "deterministic-local", "baseline_provider": "deterministic-local", "traffic_percent": 10,
    })
    assert created.status_code == 201
    canary_id = created.json()["canary"]["id"]
    assert client.post(f"/v1/release-canaries/{canary_id}/submit", headers=AUTHOR).status_code == 200
    self_review = client.post(f"/v1/release-canaries/{canary_id}/decision", headers=AUTHOR, json={"decision": "approved", "comment": "创建人不能自行批准。"})
    assert self_review.status_code == 409
    approved = client.post(f"/v1/release-canaries/{canary_id}/decision", headers=REVIEWER, json={"decision": "approved", "comment": "独立确认使用脱敏评测集执行灰度验证。"})
    assert approved.status_code == 200
    executed = client.post(f"/v1/release-canaries/{canary_id}/execute", headers=AUTHOR)
    assert executed.status_code == 200
    assert executed.json()["canary"]["status"] == "passed"
    final = client.post(f"/v1/release-canaries/{canary_id}/finalize", headers=REVIEWER, json={"action": "promoted", "comment": "允许按既有部署治理流程人工推进。"})
    assert final.status_code == 200
    assert final.json()["canary"]["status"] == "promoted"
    assert get_prompt("generate_brief").version == "v1"
