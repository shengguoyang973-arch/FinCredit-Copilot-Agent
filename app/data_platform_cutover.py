"""Verified one-way cutover tooling for SQLite canonical data to PostgreSQL.

The dry-run manifest contains only row counts and hashes. Copying canonical
records requires the operator to supply the exact displayed fingerprint, which
prevents an accidental transfer from a stale or unintended source database.
"""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.config import get_settings
from app.database import connection as sqlite_connection
from app.data_platform import _canonical_json, _sha256
from app.migrations.postgres_data_platform import apply_migrations, quote_schema


_TABLES = (
    "data_contracts", "data_ingestion_batches", "data_quality_results", "data_records", "data_lineage_events",
)
_JSON_COLUMNS = {
    "data_contracts": {"schema_json", "allowed_sources_json"},
    "data_quality_results": {"detail_json"},
    "data_records": {"record_json"},
}
_BOOLEAN_COLUMNS = {
    "data_quality_results": {"passed"},
    "data_records": {"is_current"},
}


def build_source_snapshot() -> dict[str, list[dict[str, Any]]]:
    """Read a stable, ordered source snapshot without emitting raw payloads."""
    with sqlite_connection() as connection:
        connection.execute("BEGIN")
        snapshot = {
            table: [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()]
            for table in _TABLES
        }
        connection.commit()
    return snapshot


def snapshot_manifest(snapshot: dict[str, list[dict[str, Any]]], source_label: str = "sqlite") -> dict:
    table_hashes = {table: _sha256([_normalized_row(table, row) for row in rows]) for table, rows in snapshot.items()}
    manifest = {
        "source_label": source_label,
        "tables": {table: {"row_count": len(rows), "content_hash": table_hashes[table]} for table, rows in snapshot.items()},
    }
    return manifest | {"source_fingerprint": _sha256(manifest)}


def migrate_snapshot(
    snapshot: dict[str, list[dict[str, Any]]], *, destination_dsn: str, schema: str, source_label: str,
    source_fingerprint: str, actor_id: str,
) -> dict:
    """Copy an explicitly confirmed snapshot into an empty PostgreSQL platform schema."""
    manifest = snapshot_manifest(snapshot, source_label)
    if source_fingerprint != manifest["source_fingerprint"]:
        raise ValueError("源快照指纹不匹配；请先执行 dry-run 并确认当前指纹")
    quoted = quote_schema(schema)
    with psycopg.connect(destination_dsn, row_factory=dict_row) as connection:
        with connection.transaction():
            apply_migrations(connection, schema)
            receipt = connection.execute(
                f"SELECT source_fingerprint FROM {quoted}.cutover_receipts WHERE source_fingerprint = %s", (source_fingerprint,)
            ).fetchone()
            if receipt:
                return {"status": "already_migrated", "manifest": manifest}
            populated = connection.execute(
                f"SELECT (SELECT COUNT(*) FROM {quoted}.data_contracts) + (SELECT COUNT(*) FROM {quoted}.data_ingestion_batches) AS count"
            ).fetchone()["count"]
            if populated:
                raise ValueError("目标数据中台 schema 非空；拒绝覆盖或合并未知来源数据")
            _copy_rows(connection, quoted, snapshot)
            verification = verify_destination(connection, quoted, manifest)
            if not verification["valid"]:
                raise RuntimeError("目标数据校验失败，事务已回滚")
            connection.execute(
                f"INSERT INTO {quoted}.cutover_receipts(source_fingerprint, source_label, manifest_json, migrated_by) VALUES (%s, %s, %s::jsonb, %s)",
                (source_fingerprint, source_label, _canonical_json(manifest), actor_id),
            )
    return {"status": "migrated", "manifest": manifest, "verification": verification}


def _copy_rows(connection, quoted: str, snapshot: dict[str, list[dict[str, Any]]]) -> None:
    for row in snapshot["data_contracts"]:
        connection.execute(
            f"""INSERT INTO {quoted}.data_contracts(id, version, domain_name, entity_type, schema_json, classification, description, allowed_sources_json, status, owner_id, contract_hash, created_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s, %s, %s, %s)""",
            (row["id"], row["version"], row["domain_name"], row["entity_type"], row["schema_json"], row["classification"], row["description"], row["allowed_sources_json"], row["status"], row["owner_id"], row["contract_hash"], row["created_at"]),
        )
    for row in snapshot["data_ingestion_batches"]:
        connection.execute(
            f"""INSERT INTO {quoted}.data_ingestion_batches(id, source_system, contract_id, contract_version, organization_id, status, payload_hash, record_count, accepted_count, rejected_count, submitted_by, submitted_at, finalized_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            tuple(row[key] for key in ("id", "source_system", "contract_id", "contract_version", "organization_id", "status", "payload_hash", "record_count", "accepted_count", "rejected_count", "submitted_by", "submitted_at", "finalized_at")),
        )
    for row in snapshot["data_quality_results"]:
        connection.execute(
            f"INSERT INTO {quoted}.data_quality_results(id, batch_id, rule_code, severity, passed, affected_records, detail_json, executed_at) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
            (row["id"], row["batch_id"], row["rule_code"], row["severity"], bool(row["passed"]), row["affected_records"], row["detail_json"], row["executed_at"]),
        )
    for row in snapshot["data_records"]:
        connection.execute(
            f"""INSERT INTO {quoted}.data_records(id, batch_id, organization_id, entity_type, business_key, record_json, record_hash, classification, is_current, ingested_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)""",
            (row["id"], row["batch_id"], row["organization_id"], row["entity_type"], row["business_key"], row["record_json"], row["record_hash"], row["classification"], bool(row["is_current"]), row["ingested_at"]),
        )
    for row in snapshot["data_lineage_events"]:
        connection.execute(
            f"""INSERT INTO {quoted}.data_lineage_events(id, batch_id, event_type, source_system, target_dataset, contract_id, contract_version, payload_hash, record_count, actor_id, occurred_at, prev_hash, event_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            tuple(row[key] for key in ("id", "batch_id", "event_type", "source_system", "target_dataset", "contract_id", "contract_version", "payload_hash", "record_count", "actor_id", "occurred_at", "prev_hash", "event_hash")),
        )
    for table in ("data_quality_results", "data_lineage_events"):
        connection.execute(
            f"SELECT setval(pg_get_serial_sequence('{quoted}.{table}', 'id'), COALESCE((SELECT MAX(id) FROM {quoted}.{table}), 1), TRUE)"
        )


def verify_destination(connection, quoted_schema: str, manifest: dict) -> dict:
    destination = {
        table: [dict(row) for row in connection.execute(f"SELECT * FROM {quoted_schema}.{table} ORDER BY id").fetchall()]
        for table in _TABLES
    }
    destination_counts = {table: len(rows) for table, rows in destination.items()}
    expected_counts = {table: values["row_count"] for table, values in manifest["tables"].items()}
    destination_hashes = {
        table: _sha256([_normalized_row(table, row) for row in rows]) for table, rows in destination.items()
    }
    expected_hashes = {table: values["content_hash"] for table, values in manifest["tables"].items()}
    valid = destination_counts == expected_counts and destination_hashes == expected_hashes
    return {
        "valid": valid, "expected_counts": expected_counts, "destination_counts": destination_counts,
        "expected_content_hashes": expected_hashes, "destination_content_hashes": destination_hashes,
    }


def _normalized_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    for column in _JSON_COLUMNS.get(table, set()):
        if isinstance(normalized[column], str):
            normalized[column] = json.loads(normalized[column])
    for column in _BOOLEAN_COLUMNS.get(table, set()):
        normalized[column] = bool(normalized[column])
    for key, value in normalized.items():
        if isinstance(value, datetime):
            normalized[key] = value.isoformat()
    return normalized


def default_cutover_manifest() -> dict:
    snapshot = build_source_snapshot()
    return snapshot_manifest(snapshot, source_label=f"sqlite:{get_settings().database_path.name}")
