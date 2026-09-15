from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from app.database import connection as database_connection
from app.domain import ApplicationStatus, AuditEvent, LoanApplication
from app.observability import current_request_id

CUSTOMER_SEEDS = (
    {"id": "C001", "name": "华辰设备制造有限公司", "industry": "通用设备制造", "operating_years": 6, "annual_revenue": 18_500_000, "debt_ratio": 0.52, "overdue_days_12m": 0, "credit_grade": "A", "masked_registration_no": "9131**********482X"},
    {"id": "C002", "name": "远山贸易有限公司", "industry": "批发零售", "operating_years": 1, "annual_revenue": 2_100_000, "debt_ratio": 0.81, "overdue_days_12m": 18, "credit_grade": "C", "masked_registration_no": "9131**********915K"},
)
APPLICATION_SEEDS = (
    LoanApplication("APP001", "C001", 3_000_000, 12, "补充采购原材料的流动资金", "sales_001"),
    LoanApplication("APP002", "C002", 1_500_000, 12, "补充日常经营流动资金", "sales_001"),
)


def _connection() -> sqlite3.Connection:
    return database_connection()


def initialize() -> None:
    with _connection() as connection:
        if connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
            for customer in CUSTOMER_SEEDS:
                connection.execute("INSERT INTO customers(id, customer_json) VALUES (?, ?)", (customer["id"], json.dumps(customer, ensure_ascii=False)))
        if connection.execute("SELECT COUNT(*) FROM loan_applications").fetchone()[0] == 0:
            for application in APPLICATION_SEEDS:
                connection.execute("INSERT INTO loan_applications VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (application.id, application.customer_id, application.requested_amount, application.term_months, application.purpose, application.created_by, application.status.value))
        _backfill_audit_hashes(connection)


def get_application(application_id: str) -> LoanApplication | None:
    with _connection() as connection:
        row = connection.execute("SELECT * FROM loan_applications WHERE id = ?", (application_id,)).fetchone()
    if not row:
        return None
    return LoanApplication(row["id"], row["customer_id"], row["requested_amount"], row["term_months"], row["purpose"], row["created_by"], ApplicationStatus(row["status"]))


def get_customer(customer_id: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute("SELECT customer_json FROM customers WHERE id = ?", (customer_id,)).fetchone()
    return json.loads(row["customer_json"]) if row else None


def audit(action: str, actor_id: str, resource_id: str, **detail: object) -> None:
    request_id = current_request_id()
    if request_id:
        detail = detail | {"request_id": request_id}
    detail_json = json.dumps(detail, ensure_ascii=False, default=str, sort_keys=True, separators=(",", ":"))
    timestamp = datetime.now(timezone.utc).isoformat()
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        previous = connection.execute("SELECT event_hash FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = str(previous["event_hash"]) if previous else ""
        event_hash = _audit_event_hash(prev_hash, action, actor_id, resource_id, detail_json, timestamp)
        connection.execute(
            """INSERT INTO audit_events(
                action, actor_id, resource_id, detail_json, timestamp, prev_hash, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (action, actor_id, resource_id, detail_json, timestamp, prev_hash, event_hash),
        )


def list_audit_events() -> list[AuditEvent]:
    with _connection() as connection:
        rows = connection.execute("SELECT * FROM audit_events ORDER BY id DESC").fetchall()
    return [AuditEvent(
        row["action"],
        row["actor_id"],
        row["resource_id"],
        json.loads(row["detail_json"]),
        datetime.fromisoformat(row["timestamp"]),
        row["id"],
        row["prev_hash"],
        row["event_hash"],
    ) for row in rows]


def verify_audit_chain() -> dict:
    with _connection() as connection:
        rows = connection.execute("SELECT * FROM audit_events ORDER BY id").fetchall()
    previous_hash = ""
    for row in rows:
        expected = _audit_event_hash(
            previous_hash,
            row["action"],
            row["actor_id"],
            row["resource_id"],
            row["detail_json"],
            row["timestamp"],
        )
        if row["prev_hash"] != previous_hash or row["event_hash"] != expected:
            return {"valid": False, "event_count": len(rows), "first_invalid_event_id": row["id"]}
        previous_hash = row["event_hash"]
    return {
        "valid": True,
        "event_count": len(rows),
        "first_invalid_event_id": None,
        "head_hash": previous_hash,
    }


def _backfill_audit_hashes(connection: sqlite3.Connection) -> None:
    previous_hash = ""
    rows = connection.execute("SELECT * FROM audit_events ORDER BY id").fetchall()
    for row in rows:
        if row["event_hash"]:
            previous_hash = row["event_hash"]
            continue
        event_hash = _audit_event_hash(
            previous_hash,
            row["action"],
            row["actor_id"],
            row["resource_id"],
            row["detail_json"],
            row["timestamp"],
        )
        connection.execute(
            "UPDATE audit_events SET prev_hash = ?, event_hash = ? WHERE id = ?",
            (previous_hash, event_hash, row["id"]),
        )
        previous_hash = event_hash


def _audit_event_hash(
    prev_hash: str,
    action: str,
    actor_id: str,
    resource_id: str,
    detail_json: str,
    timestamp: str,
) -> str:
    payload = json.dumps({
        "prev_hash": prev_hash,
        "action": action,
        "actor_id": actor_id,
        "resource_id": resource_id,
        "detail": json.loads(detail_json),
        "timestamp": timestamp,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
