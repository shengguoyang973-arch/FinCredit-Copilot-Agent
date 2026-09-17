"""Backend selector for the governed data-platform plane.

SQLite remains the hermetic development/test adapter. PostgreSQL is selected
only by explicit configuration so a production deployment cannot silently use
the local canonical-data store.
"""

from __future__ import annotations

from app import data_platform as sqlite_adapter
from app.config import get_settings


def _adapter():
    if get_settings().data_platform_backend == "postgres":
        from app import data_platform_postgres
        return data_platform_postgres
    return sqlite_adapter


def initialize() -> None:
    _adapter().initialize()


def save_data_contract(contract: dict, actor_id: str) -> dict:
    return _adapter().save_data_contract(contract, actor_id)


def list_data_contracts(*, include_retired: bool = False) -> list[dict]:
    return _adapter().list_data_contracts(include_retired=include_retired)


def get_data_contract(contract_id: str, version: str) -> dict | None:
    return _adapter().get_data_contract(contract_id, version)


def ingest_records(*, source_system: str, contract_id: str, organization_id: str, records: list[dict], actor_id: str) -> dict:
    return _adapter().ingest_records(
        source_system=source_system, contract_id=contract_id, organization_id=organization_id, records=records, actor_id=actor_id,
    )


def list_ingestion_batches(*, limit: int = 100) -> list[dict]:
    return _adapter().list_ingestion_batches(limit=limit)


def get_ingestion_batch(batch_id: str) -> dict | None:
    return _adapter().get_ingestion_batch(batch_id)


def list_canonical_records(*, entity_type: str, organization_id: str | None, limit: int = 100) -> list[dict]:
    return _adapter().list_canonical_records(entity_type=entity_type, organization_id=organization_id, limit=limit)


def get_canonical_record(*, entity_type: str, organization_id: str, business_key: str) -> dict | None:
    return _adapter().get_canonical_record(entity_type=entity_type, organization_id=organization_id, business_key=business_key)


def list_lineage_events(*, limit: int = 100) -> list[dict]:
    return _adapter().list_lineage_events(limit=limit)


def verify_lineage_chain() -> dict:
    return _adapter().verify_lineage_chain()


def healthcheck() -> dict:
    result = _adapter().healthcheck()
    return result | {"backend": get_settings().data_platform_backend}
