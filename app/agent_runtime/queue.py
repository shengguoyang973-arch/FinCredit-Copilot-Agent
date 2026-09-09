from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol
from uuid import uuid4

from fastapi import BackgroundTasks


@dataclass(frozen=True)
class AgentJob:
    id: str
    name: str
    payload: dict[str, Any]


class AgentExecutionQueue(Protocol):
    def enqueue(self, background_tasks: BackgroundTasks, handler: Callable[..., Any], *args: Any, **kwargs: Any) -> AgentJob:
        ...


class InProcessAgentQueue:
    """Demo adapter; the interface is ready for Redis/Celery/RQ replacement."""

    def enqueue(self, background_tasks: BackgroundTasks, handler: Callable[..., Any], *args: Any, **kwargs: Any) -> AgentJob:
        job = AgentJob(
            id=f"JOB-{uuid4().hex[:12]}",
            name=getattr(handler, "__name__", "agent_job"),
            payload={"args": list(args), "kwargs": kwargs},
        )
        background_tasks.add_task(handler, *args, **kwargs)
        return job


_QUEUE: AgentExecutionQueue = InProcessAgentQueue()


def get_agent_queue() -> AgentExecutionQueue:
    return _QUEUE
