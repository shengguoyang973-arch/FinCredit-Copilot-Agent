import pytest

from app.task_planner import build_task_plan


def test_pre_review_plan_uses_only_governed_read_tools_and_controls() -> None:
    plan = build_task_plan("generate_brief")
    assert plan.version == "v2"
    assert plan.tool_names == (
        "get_application_snapshot", "get_canonical_customer_snapshot", "get_material_status", "get_policy_evidence",
    )
    assert plan.steps[-1].id == "human_boundary"
    assert plan.steps[-1].kind == "governance"
    assert any(step.id == "context_quality" for step in plan.steps)
    trace = plan.execution_trace([{"tool_name": name, "status": "success"} for name in plan.tool_names])
    assert all(item["status"] == "completed" for item in trace)


def test_process_question_plan_adds_only_approval_status_tool() -> None:
    plan = build_task_plan("answer_question", "下一步能否提交审批？")
    assert plan.question_class == "process_question"
    assert plan.tool_names[-1] == "get_approval_status"


def test_unknown_task_cannot_be_planned() -> None:
    with pytest.raises(ValueError, match="不支持"):
        build_task_plan("execute_credit_decision")
