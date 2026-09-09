from __future__ import annotations

import json
import sqlite3
from uuid import uuid4
from datetime import datetime, timezone

from app.database import connection as database_connection
from app.agent_runtime import AgentRun, AgentRunEvent, AgentRunState


def _connection() -> sqlite3.Connection:
    return database_connection()


def initialize() -> None:
    return None


def save_report(application_id: str, report: dict, created_by: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connection() as connection:
        connection.execute("""INSERT INTO review_reports(application_id, report_json, created_by, created_at)
            VALUES (?, ?, ?, ?) ON CONFLICT(application_id) DO UPDATE SET report_json=excluded.report_json,
            created_by=excluded.created_by, created_at=excluded.created_at""",
            (application_id, json.dumps(report, ensure_ascii=False), created_by, now))


def get_report(application_id: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute("SELECT report_json, created_by, created_at FROM review_reports WHERE application_id = ?", (application_id,)).fetchone()
    if not row:
        return None
    report = json.loads(row["report_json"])
    return report | {"created_by": row["created_by"], "created_at": row["created_at"]}


def save_agent_run(application_id: str, provider: str, input_snapshot: dict, output: dict, created_by: str) -> dict:
    run_id, now = f"AGT-{uuid4().hex[:12]}", datetime.now(timezone.utc).isoformat()
    task = str(input_snapshot.get("task") or "unknown")
    runtime_run = AgentRun(run_id, application_id, task, created_by)
    event_chain = [
        (AgentRunState.CONTEXT_BUILDING, "context_built", {}),
    ]
    if input_snapshot.get("tool_count", 0):
        event_chain.append((AgentRunState.TOOL_RUNNING, "tools_executed", {"tool_names": input_snapshot.get("tool_names", [])}))
        event_chain.append((AgentRunState.MODEL_RUNNING, "model_started", {"provider": provider}))
    else:
        event_chain.append((AgentRunState.MODEL_RUNNING, "model_started", {"provider": provider}))
    event_chain.append((AgentRunState.VALIDATING, "output_validation_started", {}))
    if output.get("fallback"):
        event_chain.append((AgentRunState.FALLBACK, "agent_fallback", {"reason": output.get("fallback_reason")}))
        event_chain.append((AgentRunState.VALIDATING, "fallback_output_validation_started", {}))
    event_chain.append((AgentRunState.COMPLETED, "agent_run_completed", {"provider": provider}))
    events: list[AgentRunEvent] = []
    for next_state, event_type, metadata in event_chain:
        events.append(runtime_run.transition(next_state, event_type=event_type, **metadata))
    updated_at = datetime.now(timezone.utc).isoformat()
    with _connection() as connection:
        connection.execute("""INSERT INTO agent_runs(
            id, application_id, provider, task, state, input_snapshot_json, output_json,
            created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            run_id, application_id, provider, task, runtime_run.state.value,
            json.dumps(input_snapshot, ensure_ascii=False),
            json.dumps(output, ensure_ascii=False), created_by, now, updated_at))
        connection.executemany("""INSERT INTO agent_run_events(
            run_id, event_type, from_state, to_state, metadata_json, occurred_at
        ) VALUES (?, ?, ?, ?, ?, ?)""", [(
            event.run_id, event.event_type, event.from_state.value, event.to_state.value,
            json.dumps(event.metadata, ensure_ascii=False), event.occurred_at,
        ) for event in events])
    return get_agent_run(run_id)  # type: ignore[return-value]


def create_agent_run(application_id: str, provider: str, task: str, created_by: str, input_snapshot: dict | None = None) -> dict:
    """Create a durable Run before any model or tool work starts."""
    run_id, now = f"AGT-{uuid4().hex[:12]}", datetime.now(timezone.utc).isoformat()
    snapshot = input_snapshot or {"task": task}
    with _connection() as connection:
        connection.execute("""INSERT INTO agent_runs(
            id, application_id, provider, task, state, input_snapshot_json, output_json,
            created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            run_id, application_id, provider, task, AgentRunState.CREATED.value,
            json.dumps(snapshot, ensure_ascii=False), json.dumps({}, ensure_ascii=False),
            created_by, now, now,
        ))
    return get_agent_run(run_id)  # type: ignore[return-value]


def update_agent_run_snapshot(run_id: str, input_snapshot: dict) -> dict:
    with _connection() as connection:
        connection.execute(
            "UPDATE agent_runs SET input_snapshot_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(input_snapshot, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), run_id),
        )
    return get_agent_run(run_id)  # type: ignore[return-value]


def transition_agent_run(run_id: str, next_state: AgentRunState, *, event_type: str | None = None, **metadata: object) -> dict:
    """Validate and persist one lifecycle transition atomically."""
    run = get_agent_run(run_id)
    if not run:
        raise KeyError("Agent Run 不存在")
    runtime_run = AgentRun(run_id, run["application_id"], run["task"], run["created_by"], AgentRunState(run["state"]))
    event = runtime_run.transition(next_state, event_type=event_type, **metadata)
    now = datetime.now(timezone.utc).isoformat()
    with _connection() as connection:
        connection.execute("UPDATE agent_runs SET state = ?, updated_at = ? WHERE id = ?", (next_state.value, now, run_id))
        connection.execute("""INSERT INTO agent_run_events(
            run_id, event_type, from_state, to_state, metadata_json, occurred_at
        ) VALUES (?, ?, ?, ?, ?, ?)""", (
            event.run_id, event.event_type, event.from_state.value, event.to_state.value,
            json.dumps(event.metadata, ensure_ascii=False), event.occurred_at,
        ))
    return get_agent_run(run_id)  # type: ignore[return-value]


def resume_agent_run(run_id: str, actor_id: str) -> dict:
    """Move a failed or human-paused Run back to context reconstruction.

    The persisted snapshot is intentionally kept so a worker can rebuild the
    context deterministically before invoking the model again.
    """
    run = get_agent_run(run_id)
    if not run:
        raise KeyError("Agent Run 不存在")
    runtime_run = AgentRun(run_id, run["application_id"], run["task"], run["created_by"], AgentRunState(run["state"]))
    event = runtime_run.resume(resumed_by=actor_id)
    now = datetime.now(timezone.utc).isoformat()
    with _connection() as connection:
        connection.execute("UPDATE agent_runs SET state = ?, updated_at = ? WHERE id = ?", (runtime_run.state.value, now, run_id))
        connection.execute("""INSERT INTO agent_run_events(
            run_id, event_type, from_state, to_state, metadata_json, occurred_at
        ) VALUES (?, ?, ?, ?, ?, ?)""", (
            event.run_id, event.event_type, event.from_state.value, event.to_state.value,
            json.dumps(event.metadata, ensure_ascii=False), event.occurred_at,
        ))
    return get_agent_run(run_id)  # type: ignore[return-value]


def complete_agent_run(run_id: str, input_snapshot: dict, output: dict) -> dict:
    """Persist the final structured output after VALIDATING/COMPLETED."""
    now = datetime.now(timezone.utc).isoformat()
    with _connection() as connection:
        connection.execute(
            "UPDATE agent_runs SET input_snapshot_json = ?, output_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(input_snapshot, ensure_ascii=False), json.dumps(output, ensure_ascii=False), now, run_id),
        )
    return get_agent_run(run_id)  # type: ignore[return-value]


def get_agent_run(run_id: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    return _to_agent_run(row) if row else None


def list_agent_runs(application_id: str) -> list[dict]:
    with _connection() as connection:
        rows = connection.execute("SELECT * FROM agent_runs WHERE application_id = ? ORDER BY created_at DESC", (application_id,)).fetchall()
    return [_to_agent_run(row) for row in rows]


def list_agent_run_events(run_id: str) -> list[dict]:
    with _connection() as connection:
        rows = connection.execute(
            "SELECT * FROM agent_run_events WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
    return [{
        "id": row["id"],
        "run_id": row["run_id"],
        "event_type": row["event_type"],
        "from_state": row["from_state"],
        "to_state": row["to_state"],
        "metadata": json.loads(row["metadata_json"]),
        "occurred_at": row["occurred_at"],
    } for row in rows]


def list_all_agent_runs(limit: int = 200) -> list[dict]:
    with _connection() as connection:
        rows = connection.execute("SELECT * FROM agent_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_to_agent_run(row) for row in rows]


def _to_agent_run(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "application_id": row["application_id"],
        "provider": row["provider"],
        "task": row["task"],
        "state": row["state"],
        "input_snapshot": json.loads(row["input_snapshot_json"]),
        "output": json.loads(row["output_json"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "events": list_agent_run_events(row["id"]),
    }


def create_approval_task(application_id: str, submitted_by: str) -> dict:
    task_id, now = f"APR-{application_id}", datetime.now(timezone.utc).isoformat()
    with _connection() as connection:
        connection.execute("""INSERT INTO approval_tasks(id, application_id, status, submitted_by, submitted_at)
            VALUES (?, ?, 'pending', ?, ?) ON CONFLICT(id) DO UPDATE SET status='pending',
            submitted_by=excluded.submitted_by, submitted_at=excluded.submitted_at, decided_by=NULL,
            decided_at=NULL, decision_comment=NULL""", (task_id, application_id, submitted_by, now))
    return get_approval_task(task_id)  # type: ignore[return-value]


def get_approval_task(task_id: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute("SELECT * FROM approval_tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row) if row else None


def decide_approval_task(task_id: str, decision: str, approver_id: str, comment: str) -> dict:
    task = get_approval_task(task_id)
    if not task:
        raise KeyError("审批任务不存在")
    if task["status"] != "pending":
        raise ValueError("审批任务已处理，不能重复决策")
    with _connection() as connection:
        connection.execute("UPDATE approval_tasks SET status=?, decided_by=?, decided_at=?, decision_comment=? WHERE id=?",
            (decision, approver_id, datetime.now(timezone.utc).isoformat(), comment, task_id))
    return get_approval_task(task_id)  # type: ignore[return-value]
