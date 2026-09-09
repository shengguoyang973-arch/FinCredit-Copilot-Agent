import pytest

from app.agent_runtime import AgentRun, AgentRunState


def test_agent_run_follows_governed_lifecycle() -> None:
    run = AgentRun("AGT-test", "APP001", "generate_brief", "rm_001")

    run.transition(AgentRunState.CONTEXT_BUILDING)
    run.transition(AgentRunState.MODEL_RUNNING, provider="deepseek-chat")
    run.transition(AgentRunState.TOOL_RUNNING, tool_name="get_material_status")
    run.transition(AgentRunState.MODEL_RUNNING)
    run.transition(AgentRunState.VALIDATING)
    run.transition(AgentRunState.COMPLETED)

    assert run.state is AgentRunState.COMPLETED
    assert len(run.events) == 6
    assert run.events[1].metadata == {"provider": "deepseek-chat"}


def test_agent_run_rejects_invalid_transition_and_terminal_mutation() -> None:
    run = AgentRun("AGT-test", "APP001", "generate_brief", "rm_001")

    with pytest.raises(ValueError, match="非法 Agent Run"):
        run.transition(AgentRunState.COMPLETED)

    run.transition(AgentRunState.CONTEXT_BUILDING)
    run.transition(AgentRunState.FAILED, error_code="MODEL_TIMEOUT")
    with pytest.raises(ValueError, match="终态 Agent Run"):
        run.transition(AgentRunState.MODEL_RUNNING)
