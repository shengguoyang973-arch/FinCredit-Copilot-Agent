from fastapi import BackgroundTasks

from app.agent_runtime.queue import InProcessAgentQueue


def test_in_process_queue_returns_job_and_registers_handler() -> None:
    calls: list[tuple[str, int]] = []

    def handler(name: str, count: int) -> None:
        calls.append((name, count))

    background = BackgroundTasks()
    job = InProcessAgentQueue().enqueue(background, handler, "resume", 1)

    assert job.id.startswith("JOB-")
    assert job.name == "handler"
    assert len(background.tasks) == 1
    assert background.tasks[0].func is handler
