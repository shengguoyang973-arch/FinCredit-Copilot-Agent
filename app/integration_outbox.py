"""Durable, privacy-minimized outbox for SIEM and work-item webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from app.config import get_settings
from app.database import connection as database_connection


_DESTINATIONS = {"siem", "work_item"}
_SENSITIVE_KEY_PARTS = {"application", "customer", "material", "document", "prompt_content", "comment", "record_json", "report"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _validate_payload(payload: dict) -> None:
    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                lowered = str(key).lower()
                if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
                    raise ValueError("出站事件不得包含客户、材料、报告、Prompt 或评论字段")
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)
    visit(payload)


def enqueue_in_transaction(
    connection: sqlite3.Connection, *, destination: str, event_type: str, severity: str, payload: dict, dedupe_key: str,
) -> dict | None:
    """Queue a minimal event in the caller's existing business transaction."""
    if destination not in _DESTINATIONS:
        raise ValueError("未知的出站事件目标")
    _validate_payload(payload)
    now, event_id = _now(), f"IOE-{uuid4().hex[:16].upper()}"
    try:
        connection.execute(
            """INSERT INTO integration_outbox_events(
                id, destination, event_type, severity, payload_json, payload_hash, dedupe_key,
                status, attempt_count, available_at, created_at, delivered_at, last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, NULL, NULL)""",
            (event_id, destination, event_type, severity, _canonical_json(payload), _hash(payload), dedupe_key, now, now),
        )
    except sqlite3.IntegrityError:
        return None
    return get_event(event_id, connection=connection)


def get_event(event_id: str, *, connection: sqlite3.Connection | None = None) -> dict | None:
    if connection is not None:
        row = connection.execute("SELECT * FROM integration_outbox_events WHERE id = ?", (event_id,)).fetchone()
        return _event_from_row(row) if row else None
    with database_connection() as database:
        row = database.execute("SELECT * FROM integration_outbox_events WHERE id = ?", (event_id,)).fetchone()
    return _event_from_row(row) if row else None


def list_events(*, status: str | None = None, limit: int = 100) -> list[dict]:
    query, values = "SELECT * FROM integration_outbox_events", []
    if status:
        query += " WHERE status = ?"
        values.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    values.append(limit)
    with database_connection() as connection:
        rows = connection.execute(query, values).fetchall()
    return [_event_from_row(row) for row in rows]


def list_attempts(event_id: str) -> list[dict]:
    with database_connection() as connection:
        rows = connection.execute("SELECT * FROM integration_outbox_attempts WHERE event_id = ? ORDER BY id", (event_id,)).fetchall()
    return [{
        "id": row["id"], "event_id": row["event_id"], "attempt_number": row["attempt_number"],
        "attempted_at": row["attempted_at"], "outcome": row["outcome"], "response_status": row["response_status"],
        "response_hash": row["response_hash"], "error_message": row["error_message"],
    } for row in rows]


def _event_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "destination": row["destination"], "event_type": row["event_type"], "severity": row["severity"],
        "payload": json.loads(row["payload_json"]), "payload_hash": row["payload_hash"], "dedupe_key": row["dedupe_key"],
        "status": row["status"], "attempt_count": row["attempt_count"], "available_at": row["available_at"],
        "created_at": row["created_at"], "delivered_at": row["delivered_at"], "last_error": row["last_error"],
    }


def dispatch_pending(*, limit: int = 50) -> dict:
    settings = get_settings()
    if settings.integration_delivery_mode != "webhook":
        return {"delivery_mode": "disabled", "attempted": 0, "delivered": 0, "retryable": 0, "dead_letter": 0, "blocked": 0}
    now = _now()
    with database_connection() as connection:
        rows = connection.execute(
            """SELECT * FROM integration_outbox_events
               WHERE status IN ('pending', 'retryable') AND available_at <= ? ORDER BY created_at LIMIT ?""", (now, limit),
        ).fetchall()
    result = {"delivery_mode": "webhook", "attempted": len(rows), "delivered": 0, "retryable": 0, "dead_letter": 0, "blocked": 0}
    for row in rows:
        outcome = _dispatch_event(_event_from_row(row))
        result[outcome] += 1
    return result


def _dispatch_event(event: dict) -> str:
    url = _destination_url(event["destination"])
    if not url:
        return _record_failure(event, "blocked", "目标 Webhook 未配置")
    body = {
        "event_id": event["id"], "event_type": event["event_type"], "severity": event["severity"],
        "created_at": event["created_at"], "payload": event["payload"], "payload_hash": event["payload_hash"],
    }
    encoded = _canonical_json(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-FinCredit-Event-Id": event["id"]}
    secret = get_settings().integration_hmac_secret
    if secret:
        headers["X-FinCredit-Signature"] = hmac.new(secret.encode("utf-8"), encoded, hashlib.sha256).hexdigest()
    try:
        request = Request(url, data=encoded, headers=headers, method="POST")
        with urlopen(request, timeout=get_settings().integration_timeout_seconds) as response:  # noqa: S310 - explicitly configured webhook
            status = int(response.status)
            response_hash = hashlib.sha256(response.read(4096)).hexdigest()
        if not 200 <= status < 300:
            return _record_failure(event, "retryable", f"HTTP {status}", response_status=status, response_hash=response_hash)
    except HTTPError as error:
        return _record_failure(event, "retryable", f"HTTP {error.code}", response_status=error.code)
    except (URLError, OSError, TimeoutError) as error:
        return _record_failure(event, "retryable", f"网络投递失败：{type(error).__name__}")
    return _record_success(event, status, response_hash)


def _destination_url(destination: str) -> str:
    settings = get_settings()
    return settings.siem_webhook_url if destination == "siem" else settings.work_item_webhook_url


def _record_success(event: dict, response_status: int, response_hash: str) -> str:
    now, attempt = _now(), event["attempt_count"] + 1
    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE integration_outbox_events SET status = 'delivered', attempt_count = ?, delivered_at = ?, last_error = NULL WHERE id = ? AND status IN ('pending', 'retryable')", (attempt, now, event["id"]))
        connection.execute("INSERT INTO integration_outbox_attempts(event_id, attempt_number, attempted_at, outcome, response_status, response_hash, error_message) VALUES (?, ?, ?, 'delivered', ?, ?, NULL)", (event["id"], attempt, now, response_status, response_hash))
    return "delivered"


def _record_failure(event: dict, outcome: str, message: str, *, response_status: int | None = None, response_hash: str | None = None) -> str:
    now, attempt = _now(), event["attempt_count"] + 1
    settings = get_settings()
    final = "dead_letter" if outcome == "retryable" and attempt >= settings.integration_max_attempts else outcome
    available_at = (datetime.now(timezone.utc) + timedelta(seconds=min(3600, 15 * (2 ** max(0, attempt - 1))))).isoformat()
    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE integration_outbox_events SET status = ?, attempt_count = ?, available_at = ?, last_error = ? WHERE id = ? AND status IN ('pending', 'retryable')", (final, attempt, available_at, message[:500], event["id"]))
        connection.execute("INSERT INTO integration_outbox_attempts(event_id, attempt_number, attempted_at, outcome, response_status, response_hash, error_message) VALUES (?, ?, ?, ?, ?, ?, ?)", (event["id"], attempt, now, final, response_status, response_hash, message[:500]))
    return final


def healthcheck() -> dict:
    settings = get_settings()
    with database_connection() as connection:
        pending = connection.execute("SELECT COUNT(*) FROM integration_outbox_events WHERE status IN ('pending', 'retryable')").fetchone()[0]
        dead_letters = connection.execute("SELECT COUNT(*) FROM integration_outbox_events WHERE status = 'dead_letter'").fetchone()[0]
    return {"status": "ready", "delivery_mode": settings.integration_delivery_mode, "pending": pending, "dead_letter": dead_letters}
