import pytest

from app.data_platform_cutover import build_source_snapshot, snapshot_manifest
from app.migrations.postgres_data_platform import quote_schema


def test_data_platform_cutover_manifest_is_hash_bound_and_payload_free() -> None:
    manifest = snapshot_manifest(build_source_snapshot(), "sqlite:test")
    assert manifest["source_fingerprint"]
    assert set(manifest["tables"]) == {
        "data_contracts", "data_ingestion_batches", "data_quality_results", "data_records", "data_lineage_events",
    }
    assert all(set(item) == {"row_count", "content_hash"} for item in manifest["tables"].values())


def test_postgres_cutover_schema_identifier_is_validated() -> None:
    assert quote_schema("fincredit_data") == '"fincredit_data"'
    with pytest.raises(ValueError, match="不安全"):
        quote_schema("public; DROP TABLE data_records")
