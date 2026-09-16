"""Governed canonical-data layer for the FinCredit data platform.

The module intentionally stores only validated canonical records and cryptographic
fingerprints in lineage/audit data.  Raw source payloads are never duplicated in
batch metadata or audit events.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.database import connection as database_connection
from app.state_store import audit_in_transaction


CONTRACT_SEEDS: tuple[dict[str, Any], ...] = (
    {
        "id": "DC-CRM-CUSTOMER",
        "version": "1.0.0",
        "domain_name": "credit",
        "entity_type": "customer",
        "schema": {
            "business_key": "customer_id",
            "required_fields": ["customer_id", "name", "operating_years", "annual_revenue", "debt_ratio"],
            "field_types": {
                "customer_id": "string", "name": "string", "operating_years": "integer",
                "annual_revenue": "number", "debt_ratio": "number", "industry": "string",
            },
        },
        "classification": "confidential",
        "description": "客户主数据的标准化输入契约，供授信准入、风险分析和审计追溯使用。",
        "allowed_sources": ["crm"],
        "owner_id": "system",
    },
    {
        "id": "DC-CORE-APPLICATION",
        "version": "1.0.0",
        "domain_name": "credit",
        "entity_type": "loan_application",
        "schema": {
            "business_key": "application_id",
            "required_fields": ["application_id", "customer_id", "requested_amount", "term_months", "purpose"],
            "field_types": {
                "application_id": "string", "customer_id": "string", "requested_amount": "number",
                "term_months": "integer", "purpose": "string", "status": "string",
            },
        },
        "classification": "confidential",
        "description": "授信申请主数据的标准化输入契约，供审批协同、数据服务和历史回放使用。",
        "allowed_sources": ["core_credit"],
        "owner_id": "system",
    },
)


def _connection() -> sqlite3.Connection:
    return database_connection()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _contract_hash(contract: dict[str, Any]) -> str:
    return _sha256({
        "id": contract["id"], "version": contract["version"], "domain_name": contract["domain_name"],
        "entity_type": contract["entity_type"], "schema": contract["schema"],
        "classification": contract["classification"], "description": contract["description"],
        "allowed_sources": sorted(contract["allowed_sources"]),
    })


def initialize() -> None:
    """Install the minimum credit-domain catalog without mutating user contracts."""
    with _connection() as connection:
        if connection.execute("SELECT COUNT(*) FROM data_contracts").fetchone()[0]:
            return
        now = _utc_now()
        for seed in CONTRACT_SEEDS:
            _insert_contract(connection, seed, now)


def _insert_contract(connection: sqlite3.Connection, contract: dict[str, Any], created_at: str) -> None:
    contract_hash = _contract_hash(contract)
    connection.execute(
        """INSERT INTO data_contracts(
            id, version, domain_name, entity_type, schema_json, classification, description,
            allowed_sources_json, status, owner_id, contract_hash, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)""",
        (
            contract["id"], contract["version"], contract["domain_name"], contract["entity_type"],
            _canonical_json(contract["schema"]), contract["classification"], contract["description"],
            _canonical_json(sorted(contract["allowed_sources"])), contract["owner_id"], contract_hash, created_at,
        ),
    )


def save_data_contract(contract: dict[str, Any], actor_id: str) -> dict:
    """Publish one immutable contract version and retire the prior active version."""
    prepared = contract | {"allowed_sources": sorted(contract["allowed_sources"]), "owner_id": actor_id}
    now = _utc_now()
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT 1 FROM data_contracts WHERE id = ? AND version = ?", (prepared["id"], prepared["version"])
        ).fetchone()
        if existing:
            raise ValueError("数据契约版本已存在，契约版本不可覆盖")
        connection.execute("UPDATE data_contracts SET status = 'retired' WHERE id = ? AND status = 'active'", (prepared["id"],))
        _insert_contract(connection, prepared, now)
        audit_in_transaction(
            connection, "data_contract_published", actor_id, prepared["id"],
            version=prepared["version"], domain=prepared["domain_name"], entity_type=prepared["entity_type"],
            classification=prepared["classification"], contract_hash=_contract_hash(prepared),
        )
    return get_data_contract(prepared["id"], prepared["version"])  # type: ignore[return-value]


def list_data_contracts(*, include_retired: bool = False) -> list[dict]:
    query = "SELECT * FROM data_contracts"
    if not include_retired:
        query += " WHERE status = 'active'"
    query += " ORDER BY domain_name, entity_type, id, created_at DESC"
    with _connection() as connection:
        rows = connection.execute(query).fetchall()
    return [_contract_from_row(row) for row in rows]


def get_data_contract(contract_id: str, version: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute(
            "SELECT * FROM data_contracts WHERE id = ? AND version = ?", (contract_id, version)
        ).fetchone()
    return _contract_from_row(row) if row else None


def _active_contract(connection: sqlite3.Connection, contract_id: str) -> dict:
    row = connection.execute(
        "SELECT * FROM data_contracts WHERE id = ? AND status = 'active'", (contract_id,)
    ).fetchone()
    if not row:
        raise ValueError("未找到生效的数据契约")
    return _contract_from_row(row)


def _contract_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "version": row["version"], "domain_name": row["domain_name"],
        "entity_type": row["entity_type"], "schema": json.loads(row["schema_json"]),
        "classification": row["classification"], "description": row["description"],
        "allowed_sources": json.loads(row["allowed_sources_json"]), "status": row["status"],
        "owner_id": row["owner_id"], "contract_hash": row["contract_hash"], "created_at": row["created_at"],
    }


def ingest_records(
    *, source_system: str, contract_id: str, organization_id: str, records: list[dict[str, Any]], actor_id: str,
) -> dict:
    """Validate and atomically publish a canonical snapshot or persist a rejection receipt."""
    source_system = source_system.lower()
    now = _utc_now()
    payload_hash = _sha256(records)
    batch_id = f"DIB-{uuid4().hex[:16].upper()}"
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        contract = _active_contract(connection, contract_id)
        if source_system not in contract["allowed_sources"]:
            raise ValueError("来源系统未被当前数据契约授权")
        quality_results = evaluate_quality(contract["schema"], records)
        accepted = all(item["passed"] for item in quality_results)
        accepted_count = len(records) if accepted else 0
        rejected_count = 0 if accepted else len(records)
        batch_status = "accepted" if accepted else "rejected"
        connection.execute(
            """INSERT INTO data_ingestion_batches(
                id, source_system, contract_id, contract_version, organization_id, status, payload_hash,
                record_count, accepted_count, rejected_count, submitted_by, submitted_at, finalized_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                batch_id, source_system, contract["id"], contract["version"], organization_id, batch_status,
                payload_hash, len(records), accepted_count, rejected_count, actor_id, now, now,
            ),
        )
        _save_quality_results(connection, batch_id, quality_results, now)
        if accepted:
            _publish_canonical_records(connection, batch_id, organization_id, contract, records, now)
        _append_lineage_event(
            connection, batch_id=batch_id, event_type=f"batch_{batch_status}", source_system=source_system,
            target_dataset=f"canonical.{contract['domain_name']}.{contract['entity_type']}",
            contract_id=contract["id"], contract_version=contract["version"], payload_hash=payload_hash,
            record_count=len(records), actor_id=actor_id, occurred_at=now,
        )
        audit_in_transaction(
            connection, f"data_batch_{batch_status}", actor_id, batch_id,
            source_system=source_system, contract_id=contract["id"], contract_version=contract["version"],
            organization_id=organization_id, record_count=len(records), payload_hash=payload_hash,
            quality_passed=accepted,
        )
    return get_ingestion_batch(batch_id)  # type: ignore[return-value]


def evaluate_quality(schema: dict[str, Any], records: list[dict[str, Any]]) -> list[dict]:
    """Run deterministic, explainable data-quality checks without retaining source values."""
    required_fields = schema["required_fields"]
    field_types = schema["field_types"]
    missing: list[dict[str, Any]] = []
    type_errors: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    duplicates: list[dict[str, Any]] = []
    business_key = schema["business_key"]
    for index, record in enumerate(records):
        missing_fields = [field for field in required_fields if field not in record or record[field] in (None, "")]
        if missing_fields:
            missing.append({"record_index": index, "fields": missing_fields})
        invalid_fields = [
            field for field, expected in field_types.items()
            if field in record and record[field] is not None and not _matches_type(record[field], expected)
        ]
        if invalid_fields:
            type_errors.append({"record_index": index, "fields": invalid_fields})
        if business_key in record and record[business_key] not in (None, ""):
            key = str(record[business_key])
            if key in seen_keys:
                duplicates.append({"record_index": index, "field": business_key})
            seen_keys.add(key)
    return [
        _quality_result("DQ_REQUIRED_FIELDS", "block", missing),
        _quality_result("DQ_TYPE_CONFORMANCE", "block", type_errors),
        _quality_result("DQ_DUPLICATE_BUSINESS_KEY", "block", duplicates),
    ]


def _quality_result(rule_code: str, severity: str, errors: list[dict[str, Any]]) -> dict:
    return {
        "rule_code": rule_code, "severity": severity, "passed": not errors,
        "affected_records": len(errors), "detail": {"examples": errors[:5]},
    }


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return False


def _save_quality_results(
    connection: sqlite3.Connection, batch_id: str, results: list[dict], executed_at: str,
) -> None:
    connection.executemany(
        """INSERT INTO data_quality_results(
            batch_id, rule_code, severity, passed, affected_records, detail_json, executed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (batch_id, result["rule_code"], result["severity"], int(result["passed"]),
             result["affected_records"], _canonical_json(result["detail"]), executed_at)
            for result in results
        ],
    )


def _publish_canonical_records(
    connection: sqlite3.Connection, batch_id: str, organization_id: str, contract: dict, records: list[dict], now: str,
) -> None:
    business_key_name = contract["schema"]["business_key"]
    for record in records:
        business_key = str(record[business_key_name])
        connection.execute(
            """UPDATE data_records SET is_current = 0
               WHERE organization_id = ? AND entity_type = ? AND business_key = ? AND is_current = 1""",
            (organization_id, contract["entity_type"], business_key),
        )
        connection.execute(
            """INSERT INTO data_records(
                id, batch_id, organization_id, entity_type, business_key, record_json, record_hash,
                classification, is_current, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (
                f"DRE-{uuid4().hex[:16].upper()}", batch_id, organization_id, contract["entity_type"],
                business_key, _canonical_json(record), _sha256(record), contract["classification"], now,
            ),
        )


def _append_lineage_event(
    connection: sqlite3.Connection, *, batch_id: str, event_type: str, source_system: str, target_dataset: str,
    contract_id: str, contract_version: str, payload_hash: str, record_count: int, actor_id: str, occurred_at: str,
) -> None:
    previous = connection.execute("SELECT event_hash FROM data_lineage_events ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = str(previous["event_hash"]) if previous else ""
    event = {
        "prev_hash": prev_hash, "batch_id": batch_id, "event_type": event_type, "source_system": source_system,
        "target_dataset": target_dataset, "contract_id": contract_id, "contract_version": contract_version,
        "payload_hash": payload_hash, "record_count": record_count, "actor_id": actor_id, "occurred_at": occurred_at,
    }
    connection.execute(
        """INSERT INTO data_lineage_events(
            batch_id, event_type, source_system, target_dataset, contract_id, contract_version, payload_hash,
            record_count, actor_id, occurred_at, prev_hash, event_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            batch_id, event_type, source_system, target_dataset, contract_id, contract_version, payload_hash,
            record_count, actor_id, occurred_at, prev_hash, _sha256(event),
        ),
    )


def get_ingestion_batch(batch_id: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute("SELECT * FROM data_ingestion_batches WHERE id = ?", (batch_id,)).fetchone()
        if not row:
            return None
        quality = connection.execute(
            "SELECT * FROM data_quality_results WHERE batch_id = ? ORDER BY id", (batch_id,)
        ).fetchall()
    return _batch_from_row(row) | {"quality_results": [_quality_from_row(item) for item in quality]}


def list_ingestion_batches(*, limit: int = 100) -> list[dict]:
    with _connection() as connection:
        rows = connection.execute(
            "SELECT * FROM data_ingestion_batches ORDER BY submitted_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_batch_from_row(row) for row in rows]


def _batch_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "source_system": row["source_system"], "contract_id": row["contract_id"],
        "contract_version": row["contract_version"], "organization_id": row["organization_id"],
        "status": row["status"], "payload_hash": row["payload_hash"], "record_count": row["record_count"],
        "accepted_count": row["accepted_count"], "rejected_count": row["rejected_count"],
        "submitted_by": row["submitted_by"], "submitted_at": row["submitted_at"], "finalized_at": row["finalized_at"],
    }


def _quality_from_row(row: sqlite3.Row) -> dict:
    return {
        "rule_code": row["rule_code"], "severity": row["severity"], "passed": bool(row["passed"]),
        "affected_records": row["affected_records"], "detail": json.loads(row["detail_json"]),
        "executed_at": row["executed_at"],
    }


def list_canonical_records(*, entity_type: str, organization_id: str | None, limit: int = 100) -> list[dict]:
    clauses = ["entity_type = ?", "is_current = 1"]
    values: list[object] = [entity_type]
    if organization_id:
        clauses.append("organization_id = ?")
        values.append(organization_id)
    values.append(limit)
    with _connection() as connection:
        rows = connection.execute(
            f"SELECT * FROM data_records WHERE {' AND '.join(clauses)} ORDER BY ingested_at DESC LIMIT ?", values
        ).fetchall()
    return [_record_from_row(row) for row in rows]


def _record_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "batch_id": row["batch_id"], "organization_id": row["organization_id"],
        "entity_type": row["entity_type"], "business_key": row["business_key"],
        "record": json.loads(row["record_json"]), "record_hash": row["record_hash"],
        "classification": row["classification"], "ingested_at": row["ingested_at"],
    }


def list_lineage_events(*, limit: int = 100) -> list[dict]:
    with _connection() as connection:
        rows = connection.execute("SELECT * FROM data_lineage_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_lineage_from_row(row) for row in rows]


def _lineage_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "batch_id": row["batch_id"], "event_type": row["event_type"],
        "source_system": row["source_system"], "target_dataset": row["target_dataset"],
        "contract_id": row["contract_id"], "contract_version": row["contract_version"],
        "payload_hash": row["payload_hash"], "record_count": row["record_count"], "actor_id": row["actor_id"],
        "occurred_at": row["occurred_at"], "prev_hash": row["prev_hash"], "event_hash": row["event_hash"],
    }


def verify_lineage_chain() -> dict:
    with _connection() as connection:
        rows = connection.execute("SELECT * FROM data_lineage_events ORDER BY id").fetchall()
    previous_hash = ""
    for row in rows:
        event = _lineage_from_row(row) | {"prev_hash": previous_hash}
        event.pop("id")
        event.pop("event_hash")
        expected = _sha256(event)
        if row["prev_hash"] != previous_hash or row["event_hash"] != expected:
            return {"valid": False, "event_count": len(rows), "first_invalid_event_id": row["id"]}
        previous_hash = row["event_hash"]
    return {"valid": True, "event_count": len(rows), "first_invalid_event_id": None, "head_hash": previous_hash}


def healthcheck() -> dict:
    with _connection() as connection:
        contract_count = connection.execute("SELECT COUNT(*) FROM data_contracts WHERE status = 'active'").fetchone()[0]
        batch_count = connection.execute("SELECT COUNT(*) FROM data_ingestion_batches").fetchone()[0]
    return {"status": "ready", "active_contracts": contract_count, "batches": batch_count}
