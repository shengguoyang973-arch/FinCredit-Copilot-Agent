import pytest

from app.agent_runtime import AgentRunState
from app.workflow_store import create_agent_run, list_agent_run_events, resume_agent_run, save_agent_run, transition_agent_run


def test_agent_run_events_are_persisted_in_order() -> None:
    run = save_agent_run(
        "APP001",
        "deepseek-chat",
        {"task": "answer_question", "tool_count": 1, "tool_names": ["get_material_status"]},
        {"provider": "deepseek-chat", "fallback": False},
        "rm_001",
    )

    events = list_agent_run_events(run["id"])
    assert [event["to_state"] for event in events] == [
        "context_building", "tool_running", "model_running", "validating", "completed"
    ]
    assert run["events"] == events


def test_fallback_run_records_fallback_state() -> None:
    run = save_agent_run(
        "APP001",
        "deepseek-chat",
        {"task": "answer_question", "tool_count": 0, "tool_names": []},
        {"provider": "deepseek-chat", "fallback": True, "fallback_reason": "timeout"},
        "rm_001",
    )

    assert run["state"] == "completed"
    assert any(event["to_state"] == "fallback" for event in run["events"])


def test_failed_run_can_resume_from_persisted_checkpoint() -> None:
    run = save_agent_run(
        "APP001", "deepseek-chat", {"task": "answer_question", "tool_count": 0},
        {"provider": "deepseek-chat", "fallback": False}, "rm_001",
    )
    # A completed run is intentionally not resumable.
    with pytest.raises(ValueError, match="不支持恢复"):
        resume_agent_run(run["id"], "rm_001")

    failed = create_agent_run("APP001", "deepseek-chat", "answer_question", "rm_001")
    transition_agent_run(failed["id"], AgentRunState.CONTEXT_BUILDING)
    transition_agent_run(failed["id"], AgentRunState.FAILED, error_code="MODEL_TIMEOUT")
    resumed = resume_agent_run(failed["id"], "rm_001")
    assert resumed["state"] == "context_building"
    assert resumed["events"][-1]["event_type"] == "agent_run_resumed"
