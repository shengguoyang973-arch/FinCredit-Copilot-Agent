from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class AgentRunState(StrEnum):
    """Persistable lifecycle states for one governed Agent execution."""

    CREATED = "created"
    CONTEXT_BUILDING = "context_building"
    MODEL_RUNNING = "model_running"
    TOOL_RUNNING = "tool_running"
    WAITING_HUMAN = "waiting_human"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    FALLBACK = "fallback"
    CANCELLED = "cancelled"


TERMINAL_STATES = frozenset({AgentRunState.COMPLETED, AgentRunState.FAILED, AgentRunState.CANCELLED})


_ALLOWED_TRANSITIONS: dict[AgentRunState, frozenset[AgentRunState]] = {
    AgentRunState.CREATED: frozenset({AgentRunState.CONTEXT_BUILDING, AgentRunState.CANCELLED}),
    AgentRunState.CONTEXT_BUILDING: frozenset({AgentRunState.MODEL_RUNNING, AgentRunState.TOOL_RUNNING, AgentRunState.FAILED, AgentRunState.CANCELLED}),
    AgentRunState.MODEL_RUNNING: frozenset({
        AgentRunState.TOOL_RUNNING,
        AgentRunState.VALIDATING,
        AgentRunState.WAITING_HUMAN,
        AgentRunState.FALLBACK,
        AgentRunState.FAILED,
        AgentRunState.CANCELLED,
    }),
    AgentRunState.TOOL_RUNNING: frozenset({
        AgentRunState.MODEL_RUNNING,
        AgentRunState.VALIDATING,
        AgentRunState.FAILED,
        AgentRunState.CANCELLED,
    }),
    AgentRunState.WAITING_HUMAN: frozenset({AgentRunState.MODEL_RUNNING, AgentRunState.VALIDATING, AgentRunState.CANCELLED}),
    AgentRunState.VALIDATING: frozenset({AgentRunState.COMPLETED, AgentRunState.FALLBACK, AgentRunState.FAILED}),
    AgentRunState.FALLBACK: frozenset({AgentRunState.VALIDATING, AgentRunState.FAILED}),
    AgentRunState.COMPLETED: frozenset(),
    AgentRunState.FAILED: frozenset(),
    AgentRunState.CANCELLED: frozenset(),
}


@dataclass(frozen=True)
class AgentRunEvent:
    """An append-only lifecycle event suitable for audit and tracing."""

    run_id: str
    event_type: str
    from_state: AgentRunState
    to_state: AgentRunState
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentRun:
    """In-memory runtime contract; persistence is intentionally added later."""

    id: str
    application_id: str
    task: str
    actor_id: str
    state: AgentRunState = AgentRunState.CREATED
    events: list[AgentRunEvent] = field(default_factory=list)

    def transition(self, next_state: AgentRunState, *, event_type: str | None = None, **metadata: object) -> AgentRunEvent:
        if self.state in TERMINAL_STATES:
            raise ValueError(f"终态 Agent Run 不能继续流转：{self.state}")
        allowed = _ALLOWED_TRANSITIONS[self.state]
        if next_state not in allowed:
            raise ValueError(f"非法 Agent Run 状态流转：{self.state} -> {next_state}")
        event = AgentRunEvent(
            run_id=self.id,
            event_type=event_type or f"agent_run_{next_state.value}",
            from_state=self.state,
            to_state=next_state,
            metadata=dict(metadata),
        )
        self.state = next_state
        self.events.append(event)
        return event

    def resume(self, **metadata: object) -> AgentRunEvent:
        """Resume a failed or human-paused run from context reconstruction."""
        if self.state not in {AgentRunState.FAILED, AgentRunState.WAITING_HUMAN}:
            raise ValueError(f"当前状态不支持恢复：{self.state}")
        previous = self.state
        event = AgentRunEvent(
            run_id=self.id,
            event_type="agent_run_resumed",
            from_state=previous,
            to_state=AgentRunState.CONTEXT_BUILDING,
            metadata=dict(metadata),
        )
        self.state = AgentRunState.CONTEXT_BUILDING
        self.events.append(event)
        return event
