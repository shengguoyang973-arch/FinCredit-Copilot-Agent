from fastapi.testclient import TestClient

from app import database
from app.main import app
from app.prompt_registry import DEFAULT_PROMPTS, get_prompt


client = TestClient(app)
AUTHOR = {"X-User-Id": "compliance_001"}
REVIEWER = {"X-User-Id": "compliance_002"}
RISK = {"X-User-Id": "rm_001"}


def revised_answer_prompt() -> str:
    return DEFAULT_PROMPTS["answer_question"].content + "回答前应明确区分已知事实、政策证据和人工后续动作。"


def create_feedback_id() -> str:
    answer = client.post(
        "/v1/applications/APP001/agent-question", headers=RISK, json={"question": "下一步如何处理？"},
    )
    assert answer.status_code == 200
    run_id = answer.json()["answer"]["run_id"]
    feedback = client.post(
        f"/v1/applications/APP001/agent-runs/{run_id}/feedback", headers=RISK,
        json={"verdict": "needs_revision", "category": "evidence", "comment": "请更明确说明政策证据与后续动作的关系。"},
    )
    assert feedback.status_code == 201
    return feedback.json()["feedback"]["id"]


def test_prompt_change_is_feedback_linked_four_eyes_and_used_at_runtime() -> None:
    feedback_id = create_feedback_id()
    draft = client.post(
        "/v1/knowledge/prompts", headers=AUTHOR,
        json={
            "task": "answer_question", "version": "v2", "content": revised_answer_prompt(),
            "feedback_ids": [feedback_id], "rationale": "根据人工复核反馈强化证据与后续动作表达。",
        },
    )
    assert draft.status_code == 201
    assert draft.json()["prompt"]["status"] == "draft"
    assert draft.json()["prompt"]["feedback_ids"] == [feedback_id]
    diff = client.get("/v1/knowledge/prompts/answer_question/versions/v2/diff", headers=REVIEWER)
    assert diff.status_code == 200
    assert diff.json()["baseline_version"] == "v1"
    assert diff.json()["content_hash_valid"] is True
    submitted = client.post("/v1/knowledge/prompts/answer_question/versions/v2/submit", headers=AUTHOR)
    assert submitted.status_code == 200
    self_review = client.post(
        "/v1/knowledge/prompts/answer_question/versions/v2/decision", headers=AUTHOR,
        json={"decision": "approved", "comment": "作者不能批准自己的 Prompt 变更。"},
    )
    assert self_review.status_code == 409
    approved = client.post(
        "/v1/knowledge/prompts/answer_question/versions/v2/decision", headers=REVIEWER,
        json={"decision": "approved", "comment": "已独立复核反馈依据、决策边界和输出字段。"},
    )
    assert approved.status_code == 200
    assert approved.json()["prompt"]["status"] == "active"
    assert get_prompt("answer_question").version == "v2"
    run = client.post(
        "/v1/applications/APP001/agent-question", headers=RISK, json={"question": "当前风险如何处理？"},
    )
    assert run.status_code == 200
    run_id = run.json()["answer"]["run_id"]
    runs = client.get("/v1/applications/APP001/agent-runs", headers=REVIEWER)
    stored = next(item for item in runs.json()["items"] if item["id"] == run_id)
    assert stored["input_snapshot"]["prompt_version"] == "v2"
    listed = client.get("/v1/knowledge/prompts?include_inactive=true", headers=REVIEWER)
    versions = [(item["version"], item["status"]) for item in listed.json()["items"] if item["task"] == "answer_question"]
    assert versions == [("v2", "active"), ("v1", "retired")]


def test_prompt_content_hash_blocks_tampered_pending_version() -> None:
    draft = client.post(
        "/v1/knowledge/prompts", headers=AUTHOR,
        json={
            "task": "generate_brief", "version": "v2",
            "content": DEFAULT_PROMPTS["generate_brief"].content + "补充说明：关键风险应逐项列出。",
            "feedback_ids": [], "rationale": "提升预审草稿的风险可读性。",
        },
    )
    assert draft.status_code == 201
    assert client.post("/v1/knowledge/prompts/generate_brief/versions/v2/submit", headers=AUTHOR).status_code == 200
    with database.connection() as connection:
        connection.execute(
            "UPDATE prompt_versions SET content = ? WHERE task = ? AND version = ?",
            ("篡改后的内容", "generate_brief", "v2"),
        )
    response = client.post(
        "/v1/knowledge/prompts/generate_brief/versions/v2/decision", headers=REVIEWER,
        json={"decision": "approved", "comment": "内容哈希不一致时不得激活。"},
    )
    assert response.status_code == 409
    assert "内容哈希不匹配" in response.json()["detail"]


def test_prompt_rollback_creates_new_draft_without_bypassing_review() -> None:
    rollback = client.post(
        "/v1/knowledge/prompts/generate_brief/rollback", headers=AUTHOR,
        json={"target_version": "v1", "new_version": "v2", "reason": "回退到经过验证的初始 Prompt 基线。"},
    )
    assert rollback.status_code == 201
    assert rollback.json()["prompt"]["status"] == "draft"
    assert get_prompt("generate_brief").version == "v1"


def test_prompt_api_rejects_missing_governance_boundary_and_unknown_feedback() -> None:
    missing_boundary = client.post(
        "/v1/knowledge/prompts", headers=AUTHOR,
        json={
            "task": "answer_question", "version": "v2", "content": "这是一个足够长但没有保留必要授信治理边界的错误 Prompt 内容。" * 4,
            "feedback_ids": [], "rationale": "无效样例必须被拒绝。",
        },
    )
    assert missing_boundary.status_code == 422
    unknown_feedback = client.post(
        "/v1/knowledge/prompts", headers=AUTHOR,
        json={
            "task": "answer_question", "version": "v2", "content": revised_answer_prompt(),
            "feedback_ids": ["AFB-UNKNOWN"], "rationale": "未找到反馈不能作为变更依据。",
        },
    )
    assert unknown_feedback.status_code == 422
