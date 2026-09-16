"""Immutable human review labels and drift-alert handling history."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from app.database import connection as database_connection


def _connection() -> sqlite3.Connection:
    return database_connection()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: dict) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_agent_feedback(
    *, run_id: str, application_id: str, verdict: str, category: str, comment: str, actor_id: str,
) -> dict:
    item = {
        "id": f"AFB-{uuid4().hex[:16].upper()}", "run_id": run_id, "application_id": application_id,
        "verdict": verdict, "category": category, "comment": comment.strip(), "created_by": actor_id, "created_at": _now(),
    }
    item["content_hash"] = _hash({key: item[key] for key in ("run_id", "verdict", "category", "comment", "created_by")})
    try:
        with _connection() as connection:
            connection.execute(
                """INSERT INTO agent_feedback(
                    id, run_id, application_id, verdict, category, comment, content_hash, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                tuple(item[key] for key in (
                    "id", "run_id", "application_id", "verdict", "category", "comment", "content_hash", "created_by", "created_at"
                )),
            )
    except sqlite3.IntegrityError as error:
        raise ValueError("同一复核人对当前 Agent Run 只能提交一次反馈") from error
    return item


def list_agent_feedback(run_id: str) -> list[dict]:
    with _connection() as connection:
        rows = connection.execute("SELECT * FROM agent_feedback WHERE run_id = ? ORDER BY created_at DESC", (run_id,)).fetchall()
    return [_feedback_row(row) for row in rows]


def feedback_metrics(run_ids: list[str]) -> dict:
    if not run_ids:
        return {"feedback_count": 0, "feedback_coverage": 0.0, "human_acceptance_rate": None, "human_correction_rate": None}
    placeholders = ",".join("?" for _ in run_ids)
    with _connection() as connection:
        rows = connection.execute(
            f"SELECT run_id, verdict FROM agent_feedback WHERE run_id IN ({placeholders})", run_ids
        ).fetchall()
    reviewed_runs = {row["run_id"] for row in rows}
    total = len(rows)
    accepted = sum(row["verdict"] == "accepted" for row in rows)
    corrections = sum(row["verdict"] in {"needs_revision", "incorrect"} for row in rows)
    return {
        "feedback_count": total,
        "feedback_coverage": round(len(reviewed_runs) / len(run_ids), 4),
        "human_acceptance_rate": round(accepted / total, 4) if total else None,
        "human_correction_rate": round(corrections / total, 4) if total else None,
    }


def record_drift_alert_action(*, alert_id: str, action: str, comment: str, actor_id: str) -> dict:
    now = _now()
    with _connection() as connection:
        alert = connection.execute("SELECT id FROM agent_drift_alerts WHERE id = ?", (alert_id,)).fetchone()
        if not alert:
            raise ValueError("漂移告警不存在")
        item = {
            "id": f"ADA-ACT-{uuid4().hex[:16].upper()}", "alert_id": alert_id, "action": action,
            "comment": comment.strip(), "created_by": actor_id, "created_at": now,
        }
        connection.execute(
            """INSERT INTO agent_drift_alert_actions(id, alert_id, action, comment, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            tuple(item[key] for key in ("id", "alert_id", "action", "comment", "created_by", "created_at")),
        )
    return item


def list_drift_alert_actions(alert_id: str) -> list[dict]:
    with _connection() as connection:
        rows = connection.execute(
            "SELECT * FROM agent_drift_alert_actions WHERE alert_id = ? ORDER BY created_at DESC", (alert_id,)
        ).fetchall()
    return [{
        "id": row["id"], "alert_id": row["alert_id"], "action": row["action"], "comment": row["comment"],
        "created_by": row["created_by"], "created_at": row["created_at"],
    } for row in rows]


def drift_alert_exists(alert_id: str) -> bool:
    with _connection() as connection:
        return connection.execute("SELECT 1 FROM agent_drift_alerts WHERE id = ?", (alert_id,)).fetchone() is not None


def _feedback_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "run_id": row["run_id"], "application_id": row["application_id"],
        "verdict": row["verdict"], "category": row["category"], "comment": row["comment"],
        "content_hash": row["content_hash"], "created_by": row["created_by"], "created_at": row["created_at"],
    }
