"""PostgreSQL adapter for governed canonical credit data.

Only the data-platform control/data plane moves to PostgreSQL in this phase;
the existing approval workflow remains separately governed while cutover is
verified. SQL values are always parameterized and the schema identifier is
validated by the migration module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from app import data_platform as sqlite_contracts
from app.config import get_settings
from app.migrations.postgres_data_platform import apply_migrations, quote_schema
from app.repository import audit


def _schema() -> str:
    return quote_schema(get_settings().data_platform_postgres_schema)


def _table(name: str) -> str:
    return f"{_schema()}.{name}"


def _connection():
    dsn = get_settings().data_platform_postgres_dsn
    if not dsn:
        raise RuntimeError("FINCREDIT_DATA_PLATFORM_POSTGRES_DSN 未配置")
    return psycopg.connect(dsn, row_factory=dict_row)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: object) -> str:
    return sqlite_contracts._canonical_json(value)


def _contract_from_row(row: dict) -> dict:
    return {
        "id": row["id"], "version": row["version"], "domain_name": row["domain_name"],
        "entity_type": row["entity_type"], "schema": row["schema_json"],
        "classification": row["classification"], "description": row["description"],
        "allowed_sources": row["allowed_sources_json"], "status": row["status"],
        "owner_id": row["owner_id"], "contract_hash": row["contract_hash"], "created_at": row["created_at"].isoformat(),
    }


def initialize() -> None:
    with _connection() as connection:
        apply_migrations(connection, get_settings().data_platform_postgres_schema)
        count = connection.execute(f"SELECT COUNT(*) AS count FROM {_table('data_contracts')}").fetchone()["count"]
        if count:
            return
        now = _now()
        for contract in sqlite_contracts.CONTRACT_SEEDS:
            _insert_contract(connection, contract, now)


def _insert_contract(connection, contract: dict[str, Any], created_at: str) -> None:
    prepared = contract | {"allowed_sources": sorted(contract["allowed_sources"])}
    connection.execute(
        f"""INSERT INTO {_table('data_contracts')}(
            id, version, domain_name, entity_type, schema_json, classification, description,
            allowed_sources_json, status, owner_id, contract_hash, created_at
        ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, 'active', %s, %s, %s)""",
        (
            prepared["id"], prepared["version"], prepared["domain_name"], prepared["entity_type"],
            _json(prepared["schema"]), prepared["classification"], prepared["description"],
            _json(prepared["allowed_sources"]), prepared["owner_id"], sqlite_contracts._contract_hash(prepared), created_at,
        ),
    )


def save_data_contract(contract: dict[str, Any], actor_id: str) -> dict:
    prepared = contract | {"allowed_sources": sorted(contract["allowed_sources"]), "owner_id": actor_id}
    now = _now()
    with _connection() as connection:
        with connection.transaction():
            if connection.execute(
                f"SELECT 1 FROM {_table('data_contracts')} WHERE id = %s AND version = %s", (prepared["id"], prepared["version"])
            ).fetchone():
                raise ValueError("数据契约版本已存在，契约版本不可覆盖")
            connection.execute(f"UPDATE {_table('data_contracts')} SET status = 'retired' WHERE id = %s AND status = 'active'", (prepared["id"],))
            _insert_contract(connection, prepared, now)
    audit("data_contract_published", actor_id, prepared["id"], version=prepared["version"], backend="postgres")
    return get_data_contract(prepared["id"], prepared["version"])  # type: ignore[return-value]


def list_data_contracts(*, include_retired: bool = False) -> list[dict]:
    query = f"SELECT * FROM {_table('data_contracts')}"
    if not include_retired:
        query += " WHERE status = 'active'"
    query += " ORDER BY domain_name, entity_type, id, created_at DESC"
    with _connection() as connection:
        rows = connection.execute(query).fetchall()
    return [_contract_from_row(row) for row in rows]


def get_data_contract(contract_id: str, version: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute(f"SELECT * FROM {_table('data_contracts')} WHERE id = %s AND version = %s", (contract_id, version)).fetchone()
    return _contract_from_row(row) if row else None


def _active_contract(connection, contract_id: str) -> dict:
    row = connection.execute(f"SELECT * FROM {_table('data_contracts')} WHERE id = %s AND status = 'active'", (contract_id,)).fetchone()
    if not row:
        raise ValueError("未找到生效的数据契约")
    return _contract_from_row(row)


def ingest_records(*, source_system: str, contract_id: str, organization_id: str, records: list[dict[str, Any]], actor_id: str) -> dict:
    source_system, now = source_system.lower(), _now()
    payload_hash, batch_id = sqlite_contracts._sha256(records), f"DIB-{uuid4().hex[:16].upper()}"
    with _connection() as connection:
        with connection.transaction():
            contract = _active_contract(connection, contract_id)
            if source_system not in contract["allowed_sources"]:
                raise ValueError("来源系统未被当前数据契约授权")
            quality_results = sqlite_contracts.evaluate_quality(contract["schema"], records)
            accepted = all(item["passed"] for item in quality_results)
            connection.execute(
                f"""INSERT INTO {_table('data_ingestion_batches')}(
                    id, source_system, contract_id, contract_version, organization_id, status, payload_hash,
                    record_count, accepted_count, rejected_count, submitted_by, submitted_at, finalized_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (batch_id, source_system, contract["id"], contract["version"], organization_id,
                 "accepted" if accepted else "rejected", payload_hash, len(records), len(records) if accepted else 0,
                 0 if accepted else len(records), actor_id, now, now),
            )
            _save_quality_results(connection, batch_id, quality_results, now)
            if accepted:
                _publish_records(connection, batch_id, organization_id, contract, records, now)
            _append_lineage(connection, batch_id, f"batch_{'accepted' if accepted else 'rejected'}", source_system, contract, payload_hash, len(records), actor_id, now)
    audit(f"data_batch_{'accepted' if accepted else 'rejected'}", actor_id, batch_id, contract_id=contract_id, backend="postgres", payload_hash=payload_hash)
    return get_ingestion_batch(batch_id)  # type: ignore[return-value]


def _save_quality_results(connection, batch_id: str, results: list[dict], executed_at: str) -> None:
    connection.executemany(
        f"INSERT INTO {_table('data_quality_results')}(batch_id, rule_code, severity, passed, affected_records, detail_json, executed_at) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)",
        [(batch_id, item["rule_code"], item["severity"], item["passed"], item["affected_records"], _json(item["detail"]), executed_at) for item in results],
    )


def _publish_records(connection, batch_id: str, organization_id: str, contract: dict, records: list[dict], now: str) -> None:
    key_name = contract["schema"]["business_key"]
    for record in records:
        business_key = str(record[key_name])
        connection.execute(f"UPDATE {_table('data_records')} SET is_current = FALSE WHERE organization_id = %s AND entity_type = %s AND business_key = %s AND is_current = TRUE", (organization_id, contract["entity_type"], business_key))
        connection.execute(
            f"""INSERT INTO {_table('data_records')}(id, batch_id, organization_id, entity_type, business_key, record_json, record_hash, classification, is_current, ingested_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, TRUE, %s)""",
            (f"DRE-{uuid4().hex[:16].upper()}", batch_id, organization_id, contract["entity_type"], business_key,
             _json(record), sqlite_contracts._sha256(record), contract["classification"], now),
        )


def _append_lineage(connection, batch_id: str, event_type: str, source_system: str, contract: dict, payload_hash: str, record_count: int, actor_id: str, occurred_at: str) -> None:
    previous = connection.execute(f"SELECT event_hash FROM {_table('data_lineage_events')} ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = previous["event_hash"] if previous else ""
    event = {"prev_hash": prev_hash, "batch_id": batch_id, "event_type": event_type, "source_system": source_system, "target_dataset": f"canonical.{contract['domain_name']}.{contract['entity_type']}", "contract_id": contract["id"], "contract_version": contract["version"], "payload_hash": payload_hash, "record_count": record_count, "actor_id": actor_id, "occurred_at": occurred_at}
    connection.execute(
        f"""INSERT INTO {_table('data_lineage_events')}(batch_id, event_type, source_system, target_dataset, contract_id, contract_version, payload_hash, record_count, actor_id, occurred_at, prev_hash, event_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (batch_id, event_type, source_system, event["target_dataset"], contract["id"], contract["version"], payload_hash, record_count, actor_id, occurred_at, prev_hash, sqlite_contracts._sha256(event)),
    )


def _batch_from_row(row: dict) -> dict:
    return {key: (value.isoformat() if key in {"submitted_at", "finalized_at"} else value) for key, value in row.items()}


def get_ingestion_batch(batch_id: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute(f"SELECT * FROM {_table('data_ingestion_batches')} WHERE id = %s", (batch_id,)).fetchone()
        if not row:
            return None
        quality = connection.execute(f"SELECT * FROM {_table('data_quality_results')} WHERE batch_id = %s ORDER BY id", (batch_id,)).fetchall()
    return _batch_from_row(row) | {"quality_results": [{"rule_code": item["rule_code"], "severity": item["severity"], "passed": bool(item["passed"]), "affected_records": item["affected_records"], "detail": item["detail_json"], "executed_at": item["executed_at"].isoformat()} for item in quality]}


def list_ingestion_batches(*, limit: int = 100) -> list[dict]:
    with _connection() as connection:
        rows = connection.execute(f"SELECT * FROM {_table('data_ingestion_batches')} ORDER BY submitted_at DESC LIMIT %s", (limit,)).fetchall()
    return [_batch_from_row(row) for row in rows]


def _record(row: dict) -> dict:
    return {"id": row["id"], "batch_id": row["batch_id"], "organization_id": row["organization_id"], "entity_type": row["entity_type"], "business_key": row["business_key"], "record": row["record_json"], "record_hash": row["record_hash"], "classification": row["classification"], "ingested_at": row["ingested_at"].isoformat()}


def list_canonical_records(*, entity_type: str, organization_id: str | None, limit: int = 100) -> list[dict]:
    clauses, values = ["entity_type = %s", "is_current = TRUE"], [entity_type]
    if organization_id:
        clauses.append("organization_id = %s")
        values.append(organization_id)
    values.append(limit)
    with _connection() as connection:
        rows = connection.execute(f"SELECT * FROM {_table('data_records')} WHERE {' AND '.join(clauses)} ORDER BY ingested_at DESC LIMIT %s", values).fetchall()
    return [_record(row) for row in rows]


def get_canonical_record(*, entity_type: str, organization_id: str, business_key: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute(f"SELECT * FROM {_table('data_records')} WHERE entity_type = %s AND organization_id = %s AND business_key = %s AND is_current = TRUE", (entity_type, organization_id, business_key)).fetchone()
    return _record(row) if row else None


def _lineage(row: dict) -> dict:
    result = dict(row)
    result["occurred_at"] = result["occurred_at"].isoformat()
    return result


def list_lineage_events(*, limit: int = 100) -> list[dict]:
    with _connection() as connection:
        rows = connection.execute(f"SELECT * FROM {_table('data_lineage_events')} ORDER BY id DESC LIMIT %s", (limit,)).fetchall()
    return [_lineage(row) for row in rows]


def verify_lineage_chain() -> dict:
    with _connection() as connection:
        rows = connection.execute(f"SELECT * FROM {_table('data_lineage_events')} ORDER BY id").fetchall()
    previous_hash = ""
    for row in rows:
        item = _lineage(row)
        event = {key: item[key] for key in ("batch_id", "event_type", "source_system", "target_dataset", "contract_id", "contract_version", "payload_hash", "record_count", "actor_id", "occurred_at")}
        event["prev_hash"] = previous_hash
        if item["prev_hash"] != previous_hash or item["event_hash"] != sqlite_contracts._sha256(event):
            return {"valid": False, "event_count": len(rows), "first_invalid_event_id": item["id"]}
        previous_hash = item["event_hash"]
    return {"valid": True, "event_count": len(rows), "first_invalid_event_id": None, "head_hash": previous_hash}


def healthcheck() -> dict:
    with _connection() as connection:
        connection.execute("SELECT 1").fetchone()
        contracts = connection.execute(f"SELECT COUNT(*) AS count FROM {_table('data_contracts')} WHERE status = 'active'").fetchone()["count"]
        batches = connection.execute(f"SELECT COUNT(*) AS count FROM {_table('data_ingestion_batches')}").fetchone()["count"]
    return {"status": "ready", "backend": "postgres", "active_contracts": contracts, "batches": batches}
