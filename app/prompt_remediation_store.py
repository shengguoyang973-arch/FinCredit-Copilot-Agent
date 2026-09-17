"""Human-owned remediation cases for acknowledged Prompt observation reviews."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from uuid import uuid4

from app.config import get_settings
from app.database import connection as database_connection
from app.state_store import audit_in_transaction


ACTIONABLE_RECOMMENDATIONS = frozenset({"investigate", "rollback_recommended"})
CASE_STATUSES = frozenset({"open", "in_progress", "resolved", "cancelled"})
RESOLUTION_TYPES = frozenset({
    "investigation_completed", "monitoring_completed", "rollback_draft_created", "no_change_justified",
})
_ALLOWED_TRANSITIONS = {
    "open": frozenset({"in_progress", "cancelled"}),
    "in_progress": frozenset({"resolved", "cancelled"}),
    "resolved": frozenset(),
    "cancelled": frozenset(),
}


def _connection() -> sqlite3.Connection:
    return database_connection()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_remediation_case(
    *, review_id: str, owner_id: str, due_date: str, actor_id: str,
) -> dict:
    """Open one human-owned work item for an independently acknowledged review."""
    _validate_due_date(due_date)
    case_id, now = f"PRC-{uuid4().hex[:16].upper()}", _now()
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        review = connection.execute(
            "SELECT * FROM prompt_observation_reviews WHERE id = ?", (review_id,)
        ).fetchone()
        if not review:
            raise KeyError("Prompt 观察复盘不存在")
        if review["status"] != "acknowledged":
            raise ValueError("仅已被独立确认的 Prompt 观察复盘可以创建处置作业单")
        if review["recommendation"] not in ACTIONABLE_RECOMMENDATIONS:
            raise ValueError("仅建议排查或建议受控回滚的复盘可以创建处置作业单")
        try:
            connection.execute(
                """INSERT INTO prompt_remediation_cases(
                    id, observation_review_id, task, version, prompt_id, recommendation, status,
                    owner_id, due_date, created_by, created_at, updated_at, resolved_by,
                    resolved_at, resolution_type, resolution_reference, resolution_note
                ) VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL)""",
                (
                    case_id, review_id, review["task"], review["version"], review["prompt_id"],
                    review["recommendation"], owner_id, due_date, actor_id, now, now,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("该 Prompt 观察复盘已经关联处置作业单") from error
        _append_event(
            connection, case_id=case_id, event_type="case_created", from_status="", to_status="open",
            comment="基于已确认的 Prompt 观察复盘创建处置作业单。", actor_id=actor_id, occurred_at=now,
        )
        audit_in_transaction(
            connection,
            "prompt_remediation_case_created",
            actor_id,
            case_id,
            review_id=review_id,
            task=review["task"],
            version=review["version"],
            recommendation=review["recommendation"],
            owner_id=owner_id,
            due_date=due_date,
        )
    return get_remediation_case(case_id)  # type: ignore[return-value]


def update_remediation_case(
    case_id: str,
    *,
    next_status: str,
    comment: str,
    actor_id: str,
    resolution_type: str | None = None,
    resolution_reference: str | None = None,
) -> dict:
    if next_status not in CASE_STATUSES:
        raise ValueError("不支持的处置作业单状态")
    if next_status == "resolved":
        if resolution_type not in RESOLUTION_TYPES or not (resolution_reference or "").strip():
            raise ValueError("关闭处置作业单必须记录结论类型与结论参考编号")
    elif resolution_type is not None or resolution_reference is not None:
        raise ValueError("仅关闭处置作业单时可以记录结论类型与结论参考编号")

    now = _now()
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM prompt_remediation_cases WHERE id = ?", (case_id,)).fetchone()
        if not row:
            raise KeyError("Prompt 处置作业单不存在")
        if row["owner_id"] != actor_id:
            raise PermissionError("仅处置作业单负责人可以更新状态")
        if next_status not in _ALLOWED_TRANSITIONS[row["status"]]:
            raise ValueError("处置作业单状态迁移不被允许")
        resolved_fields = (
            actor_id if next_status == "resolved" else None,
            now if next_status == "resolved" else None,
            resolution_type if next_status == "resolved" else None,
            resolution_reference.strip() if next_status == "resolved" and resolution_reference else None,
            comment.strip() if next_status == "resolved" else None,
        )
        updated = connection.execute(
            """UPDATE prompt_remediation_cases
               SET status = ?, updated_at = ?, resolved_by = ?, resolved_at = ?, resolution_type = ?,
                   resolution_reference = ?, resolution_note = ?
               WHERE id = ? AND status = ?""",
            (next_status, now, *resolved_fields, case_id, row["status"]),
        )
        if updated.rowcount != 1:
            raise ValueError("处置作业单已被并发修改")
        _append_event(
            connection, case_id=case_id, event_type=f"status_{next_status}", from_status=row["status"],
            to_status=next_status, comment=comment.strip(), actor_id=actor_id, occurred_at=now,
        )
        audit_in_transaction(
            connection,
            "prompt_remediation_case_status_updated",
            actor_id,
            case_id,
            from_status=row["status"],
            to_status=next_status,
            resolution_type=resolution_type if next_status == "resolved" else None,
            resolution_reference=resolution_reference.strip() if next_status == "resolved" and resolution_reference else None,
        )
    return get_remediation_case(case_id)  # type: ignore[return-value]


def get_remediation_case(case_id: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute("SELECT * FROM prompt_remediation_cases WHERE id = ?", (case_id,)).fetchone()
    return _to_case(row) if row else None


def list_remediation_cases(*, status: str | None = None, limit: int = 100) -> list[dict]:
    query = "SELECT * FROM prompt_remediation_cases"
    values: list[object] = []
    if status:
        query += " WHERE status = ?"
        values.append(status)
    query += " ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, due_date, created_at DESC LIMIT ?"
    values.append(limit)
    with _connection() as connection:
        rows = connection.execute(query, values).fetchall()
    return [_to_case(row) for row in rows]


def list_remediation_case_events(case_id: str) -> list[dict]:
    with _connection() as connection:
        rows = connection.execute(
            "SELECT * FROM prompt_remediation_case_events WHERE case_id = ? ORDER BY id", (case_id,)
        ).fetchall()
    return [{
        "id": row["id"], "case_id": row["case_id"], "event_type": row["event_type"],
        "from_status": row["from_status"] or None, "to_status": row["to_status"],
        "comment": row["comment"], "actor_id": row["actor_id"], "occurred_at": row["occurred_at"],
    } for row in rows]


def remediation_case_summary() -> dict:
    with _connection() as connection:
        rows = connection.execute("SELECT status, due_date FROM prompt_remediation_cases").fetchall()
    items = [(row["status"], row["due_date"]) for row in rows]
    return {
        "total": len(items),
        "open": sum(status == "open" for status, _ in items),
        "in_progress": sum(status == "in_progress" for status, _ in items),
        "overdue": sum(_due_state(status, due_date) == "overdue" for status, due_date in items),
    }


def latest_remediation_case_summaries() -> dict[tuple[str, str], dict]:
    """Expose operational status, without comments or resolution references."""
    with _connection() as connection:
        rows = connection.execute("SELECT * FROM prompt_remediation_cases ORDER BY created_at DESC").fetchall()
    items = [_to_case(row) for row in rows]
    latest: dict[tuple[str, str], dict] = {}
    for item in items:
        key = (item["task"], item["version"])
        if key not in latest:
            latest[key] = {
                "id": item["id"], "status": item["status"], "due_date": item["due_date"],
                "due_state": item["due_state"], "recommendation": item["recommendation"],
            }
    return latest


def _append_event(
    connection: sqlite3.Connection,
    *,
    case_id: str,
    event_type: str,
    from_status: str,
    to_status: str,
    comment: str,
    actor_id: str,
    occurred_at: str,
) -> None:
    connection.execute(
        """INSERT INTO prompt_remediation_case_events(
            case_id, event_type, from_status, to_status, comment, actor_id, occurred_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (case_id, event_type, from_status, to_status, comment, actor_id, occurred_at),
    )


def _validate_due_date(value: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("处置作业单截止日期必须是有效 ISO 日期") from error


def _due_state(status: str, due_date: str) -> str:
    if status in {"resolved", "cancelled"}:
        return "closed"
    today = datetime.now(ZoneInfo(get_settings().policy_timezone)).date()
    due = date.fromisoformat(due_date)
    if due < today:
        return "overdue"
    if due == today:
        return "due_today"
    return "on_track"


def _to_case(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "observation_review_id": row["observation_review_id"], "task": row["task"],
        "version": row["version"], "prompt_id": row["prompt_id"], "recommendation": row["recommendation"],
        "status": row["status"], "owner_id": row["owner_id"], "due_date": row["due_date"],
        "due_state": _due_state(row["status"], row["due_date"]), "created_by": row["created_by"],
        "created_at": row["created_at"], "updated_at": row["updated_at"], "resolved_by": row["resolved_by"],
        "resolved_at": row["resolved_at"], "resolution_type": row["resolution_type"],
        "resolution_reference": row["resolution_reference"], "resolution_note": row["resolution_note"],
    }
