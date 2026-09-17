from __future__ import annotations

import hashlib
import json
import sqlite3
from uuid import uuid4
from datetime import datetime, timezone

from app.database import connection as database_connection
from app.agent_runtime import AgentRun, AgentRunEvent, AgentRunState
from app.domain import ApplicationStatus
from app.state_store import audit_in_transaction


def _connection() -> sqlite3.Connection:
    return database_connection()


def initialize() -> None:
    return None


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
    now = datetime.now(timezone.utc).isoformat()
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            raise KeyError("Agent Run 不存在")
        runtime_run = AgentRun(
            run_id, row["application_id"], row["task"], row["created_by"], AgentRunState(row["state"])
        )
        event = runtime_run.transition(next_state, event_type=event_type, **metadata)
        updated = connection.execute(
            "UPDATE agent_runs SET state = ?, updated_at = ? WHERE id = ? AND state = ?",
            (next_state.value, now, run_id, row["state"]),
        )
        if updated.rowcount != 1:
            raise ValueError("Agent Run 状态已被并发修改")
        _insert_agent_run_event(connection, event)
    return get_agent_run(run_id)  # type: ignore[return-value]


def resume_agent_run(run_id: str, actor_id: str) -> dict:
    """Move a failed or human-paused Run back to context reconstruction.

    The persisted snapshot is intentionally kept so a worker can rebuild the
    context deterministically before invoking the model again.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            raise KeyError("Agent Run 不存在")
        runtime_run = AgentRun(
            run_id, row["application_id"], row["task"], row["created_by"], AgentRunState(row["state"])
        )
        event = runtime_run.resume(resumed_by=actor_id)
        updated = connection.execute(
            "UPDATE agent_runs SET state = ?, updated_at = ? WHERE id = ? AND state = ?",
            (runtime_run.state.value, now, run_id, row["state"]),
        )
        if updated.rowcount != 1:
            raise ValueError("Agent Run 状态已被并发修改")
        _insert_agent_run_event(connection, event)
    return get_agent_run(run_id)  # type: ignore[return-value]


def finalize_agent_run(run_id: str, input_snapshot: dict, output: dict) -> dict:
    """Atomically persist output, COMPLETED state, and its lifecycle event."""
    now = datetime.now(timezone.utc).isoformat()
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            raise KeyError("Agent Run 不存在")
        runtime_run = AgentRun(
            run_id,
            row["application_id"],
            row["task"],
            row["created_by"],
            AgentRunState(row["state"]),
        )
        event = runtime_run.transition(AgentRunState.COMPLETED)
        updated = connection.execute(
            """UPDATE agent_runs SET state = ?, input_snapshot_json = ?, output_json = ?, updated_at = ?
               WHERE id = ? AND state = ?""",
            (
                AgentRunState.COMPLETED.value,
                json.dumps(input_snapshot, ensure_ascii=False),
                json.dumps(output, ensure_ascii=False),
                now,
                run_id,
                row["state"],
            ),
        )
        if updated.rowcount != 1:
            raise ValueError("Agent Run 状态已被并发修改")
        _insert_agent_run_event(connection, event)
    return get_agent_run(run_id)  # type: ignore[return-value]


def finalize_pre_review(
    application_id: str,
    run_id: str,
    report: dict,
    created_by: str,
    input_snapshot: dict,
    output: dict,
) -> dict:
    """Commit report, Agent Run completion, and application status together."""
    now = datetime.now(timezone.utc).isoformat()
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        application = connection.execute(
            "SELECT status FROM loan_applications WHERE id = ?", (application_id,)
        ).fetchone()
        if not application:
            raise KeyError("授信申请不存在")
        allowed_statuses = {
            ApplicationStatus.DRAFT.value,
            ApplicationStatus.PRE_REVIEWED.value,
            ApplicationStatus.RETURNED.value,
        }
        if application["status"] not in allowed_statuses:
            raise ValueError("当前申请状态不允许重新生成预审报告")
        row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        if not row or row["application_id"] != application_id:
            raise KeyError("Agent Run 不存在或不属于当前申请")
        runtime_run = AgentRun(
            run_id,
            application_id,
            row["task"],
            row["created_by"],
            AgentRunState(row["state"]),
        )
        event = runtime_run.transition(AgentRunState.COMPLETED)
        connection.execute(
            """INSERT INTO review_reports(application_id, report_json, created_by, created_at)
               VALUES (?, ?, ?, ?) ON CONFLICT(application_id) DO UPDATE SET
               report_json=excluded.report_json, created_by=excluded.created_by, created_at=excluded.created_at""",
            (application_id, json.dumps(report, ensure_ascii=False), created_by, now),
        )
        updated_run = connection.execute(
            """UPDATE agent_runs SET state = ?, input_snapshot_json = ?, output_json = ?, updated_at = ?
               WHERE id = ? AND state = ?""",
            (
                AgentRunState.COMPLETED.value,
                json.dumps(input_snapshot, ensure_ascii=False),
                json.dumps(output, ensure_ascii=False),
                now,
                run_id,
                row["state"],
            ),
        )
        if updated_run.rowcount != 1:
            raise ValueError("Agent Run 状态已被并发修改")
        _insert_agent_run_event(connection, event)
        placeholders = ",".join("?" for _ in allowed_statuses)
        updated_application = connection.execute(
            f"UPDATE loan_applications SET status = ? WHERE id = ? AND status IN ({placeholders})",
            (ApplicationStatus.PRE_REVIEWED.value, application_id, *sorted(allowed_statuses)),
        )
        if updated_application.rowcount != 1:
            raise ValueError("申请状态已被并发修改")
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


def list_agent_run_workflow_outcomes(run_ids: list[str]) -> list[dict]:
    """Return minimal final human-workflow outcomes for the supplied Agent Runs.

    The outcomes are audit metadata for Prompt release observation. They are not
    labels for model training and never alter a credit decision.
    """
    if not run_ids:
        return []
    placeholders = ",".join("?" for _ in run_ids)
    with _connection() as connection:
        rows = connection.execute(
            f"""SELECT approval_task_id, application_id, run_id, prompt_id, prompt_version,
                       decision, decided_at
                FROM agent_run_workflow_outcomes WHERE run_id IN ({placeholders})""",
            run_ids,
        ).fetchall()
    return [{
        "approval_task_id": row["approval_task_id"], "application_id": row["application_id"],
        "run_id": row["run_id"], "prompt_id": row["prompt_id"], "prompt_version": row["prompt_version"],
        "decision": row["decision"], "decided_at": row["decided_at"],
    } for row in rows]


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
    task_id, now = f"APR-{application_id}-{uuid4().hex[:8]}", datetime.now(timezone.utc).isoformat()
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        application = connection.execute(
            "SELECT status FROM loan_applications WHERE id = ?", (application_id,)
        ).fetchone()
        if not application:
            raise KeyError("授信申请不存在")
        if application["status"] != ApplicationStatus.PRE_REVIEWED.value:
            raise ValueError("申请状态已变化，不能重复提交审批")
        report = connection.execute(
            "SELECT report_json, created_by FROM review_reports WHERE application_id = ?", (application_id,)
        ).fetchone()
        if not report:
            raise ValueError("提交审批前必须先生成预审报告")
        connection.execute(
            """INSERT INTO approval_tasks(
                id, application_id, status, submitted_by, submitted_at, reviewed_by, report_hash
            ) VALUES (?, ?, 'pending', ?, ?, ?, ?)""",
            (
                task_id,
                application_id,
                submitted_by,
                now,
                report["created_by"],
                _report_hash(report["report_json"]),
            ),
        )
        updated = connection.execute(
            "UPDATE loan_applications SET status = ? WHERE id = ? AND status = ?",
            (ApplicationStatus.PENDING_APPROVAL.value, application_id, ApplicationStatus.PRE_REVIEWED.value),
        )
        if updated.rowcount != 1:
            raise ValueError("申请状态已被并发修改")
    return get_approval_task(task_id)  # type: ignore[return-value]


def get_approval_task(task_id: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute("SELECT * FROM approval_tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row) if row else None


def get_latest_approval_task(application_id: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute(
            "SELECT * FROM approval_tasks WHERE application_id = ? ORDER BY submitted_at DESC, id DESC LIMIT 1",
            (application_id,),
        ).fetchone()
    return dict(row) if row else None


def decide_approval_task(task_id: str, decision: str, approver_id: str, comment: str) -> dict:
    target_status = {
        "approved": ApplicationStatus.APPROVED.value,
        "rejected": ApplicationStatus.REJECTED.value,
        "returned": ApplicationStatus.RETURNED.value,
    }[decision]
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        task = connection.execute("SELECT * FROM approval_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            raise KeyError("审批任务不存在")
        if task["status"] != "pending":
            raise ValueError("审批任务已处理，不能重复决策")
        application = connection.execute(
            "SELECT status, created_by FROM loan_applications WHERE id = ?", (task["application_id"],)
        ).fetchone()
        if not application or application["status"] != ApplicationStatus.PENDING_APPROVAL.value:
            raise ValueError("申请不处于待审批状态")
        conflicting_actors = {task["submitted_by"], task["reviewed_by"], application["created_by"]}
        if approver_id in conflicting_actors:
            raise ValueError("职责分离校验失败：申请创建、预审/提交与最终审批必须由不同人员完成")
        report = connection.execute(
            "SELECT report_json FROM review_reports WHERE application_id = ?", (task["application_id"],)
        ).fetchone()
        if not report or _report_hash(report["report_json"]) != task["report_hash"]:
            raise ValueError("审批依据的预审报告已变化，请退回并重新提交")
        decided_at = datetime.now(timezone.utc).isoformat()
        updated_task = connection.execute(
            """UPDATE approval_tasks SET status=?, decided_by=?, decided_at=?, decision_comment=?
               WHERE id=? AND status='pending'""",
            (decision, approver_id, decided_at, comment, task_id),
        )
        if updated_task.rowcount != 1:
            raise ValueError("审批任务已被并发处理")
        updated_application = connection.execute(
            "UPDATE loan_applications SET status = ? WHERE id = ? AND status = ?",
            (target_status, task["application_id"], ApplicationStatus.PENDING_APPROVAL.value),
        )
        if updated_application.rowcount != 1:
            raise ValueError("申请状态已被并发修改")
        _record_prompt_workflow_outcome_in_transaction(
            connection,
            task=task,
            report_json=report["report_json"],
            decision=decision,
            approver_id=approver_id,
            decided_at=decided_at,
        )
    return get_approval_task(task_id)  # type: ignore[return-value]


def _record_prompt_workflow_outcome_in_transaction(
    connection: sqlite3.Connection,
    *,
    task: sqlite3.Row,
    report_json: str,
    decision: str,
    approver_id: str,
    decided_at: str,
) -> None:
    """Link an immutable human decision to the exact pre-review Agent Run.

    Historic reports without an Agent Run or Prompt snapshot remain valid
    approval evidence, but cannot be attributed to a governed Prompt cohort.
    """
    try:
        report = json.loads(report_json)
        run_id = str(report.get("agent_brief", {}).get("run_id") or "")
    except (AttributeError, json.JSONDecodeError):
        return
    if not run_id:
        return
    run = connection.execute(
        "SELECT application_id, input_snapshot_json FROM agent_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if not run or run["application_id"] != task["application_id"]:
        return
    try:
        snapshot = json.loads(run["input_snapshot_json"])
    except json.JSONDecodeError:
        return
    prompt_id = str(snapshot.get("prompt_id") or "untracked")
    prompt_version = str(snapshot.get("prompt_version") or "untracked")
    connection.execute(
        """INSERT INTO agent_run_workflow_outcomes(
            approval_task_id, application_id, run_id, prompt_id, prompt_version, report_hash,
            decision, decided_by, decided_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            task["id"], task["application_id"], run_id, prompt_id, prompt_version,
            task["report_hash"], decision, approver_id, decided_at,
        ),
    )
    audit_in_transaction(
        connection,
        "prompt_workflow_outcome_recorded",
        approver_id,
        run_id,
        approval_task_id=task["id"],
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        decision=decision,
    )


def _insert_agent_run_event(connection: sqlite3.Connection, event: AgentRunEvent) -> None:
    connection.execute(
        """INSERT INTO agent_run_events(
            run_id, event_type, from_state, to_state, metadata_json, occurred_at
        ) VALUES (?, ?, ?, ?, ?, ?)""",
        (
            event.run_id,
            event.event_type,
            event.from_state.value,
            event.to_state.value,
            json.dumps(event.metadata, ensure_ascii=False),
            event.occurred_at,
        ),
    )


def _report_hash(report_json: str) -> str:
    return hashlib.sha256(report_json.encode("utf-8")).hexdigest()
