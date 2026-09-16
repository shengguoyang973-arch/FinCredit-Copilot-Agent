from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
COMPLIANCE = {"X-User-Id": "compliance_001"}
RISK = {"X-User-Id": "rm_001"}


def valid_customer_record(customer_id: str = "C-DP-001") -> dict:
    return {
        "customer_id": customer_id,
        "name": "数据中台测试企业",
        "operating_years": 4,
        "annual_revenue": 8_500_000,
        "debt_ratio": 0.48,
        "industry": "设备制造",
    }


def test_catalog_exposes_seeded_credit_data_contracts() -> None:
    response = client.get("/v1/data-platform/catalog", headers=RISK)
    assert response.status_code == 200
    contracts = response.json()["items"]
    assert {item["id"] for item in contracts} == {"DC-CRM-CUSTOMER", "DC-CORE-APPLICATION"}
    assert contracts[0]["contract_hash"]


def test_contract_versions_are_immutable_and_retire_prior_version() -> None:
    payload = {
        "id": "DC-RISK-SIGNAL", "version": "1.0.0", "domain_name": "risk", "entity_type": "risk_signal",
        "schema": {
            "business_key": "signal_id", "required_fields": ["signal_id", "score"],
            "field_types": {"signal_id": "string", "score": "number"},
        },
        "classification": "restricted", "description": "风险信号数据契约，统一风险评分和来源追踪字段。", "allowed_sources": ["risk_engine"],
    }
    first = client.post("/v1/data-platform/contracts", headers=COMPLIANCE, json=payload)
    assert first.status_code == 201
    assert first.json()["contract"]["status"] == "active"

    duplicate = client.post("/v1/data-platform/contracts", headers=COMPLIANCE, json=payload)
    assert duplicate.status_code == 409

    next_version = payload | {"version": "1.1.0", "description": "风险信号数据契约，统一风险评分、来源追踪和版本化治理字段。"}
    second = client.post("/v1/data-platform/contracts", headers=COMPLIANCE, json=next_version)
    assert second.status_code == 201
    catalog = client.get("/v1/data-platform/catalog?include_retired=true", headers=COMPLIANCE).json()["items"]
    versions = [item for item in catalog if item["id"] == "DC-RISK-SIGNAL"]
    assert {item["status"] for item in versions} == {"active", "retired"}


def test_data_ingestion_publishes_canonical_records_after_quality_passes() -> None:
    response = client.post("/v1/data-platform/ingestion-batches", headers=COMPLIANCE, json={
        "source_system": "crm", "contract_id": "DC-CRM-CUSTOMER", "organization_id": "branch-shanghai",
        "records": [valid_customer_record()],
    })
    assert response.status_code == 201
    batch = response.json()["batch"]
    assert batch["status"] == "accepted"
    assert batch["accepted_count"] == 1
    assert all(result["passed"] for result in batch["quality_results"])

    records = client.get("/v1/data-platform/records/customer", headers=RISK)
    assert records.status_code == 200
    item = records.json()["items"][0]
    assert item["record"]["customer_id"] == "C-DP-001"
    assert item["classification"] == "confidential"


def test_bad_batch_is_receipted_but_does_not_publish_canonical_data() -> None:
    bad = valid_customer_record("C-DP-BAD") | {"operating_years": "four"}
    bad.pop("name")
    response = client.post("/v1/data-platform/ingestion-batches", headers=COMPLIANCE, json={
        "source_system": "crm", "contract_id": "DC-CRM-CUSTOMER", "organization_id": "branch-shanghai",
        "records": [bad],
    })
    assert response.status_code == 201
    batch = response.json()["batch"]
    assert batch["status"] == "rejected"
    assert batch["rejected_count"] == 1
    assert {result["rule_code"] for result in batch["quality_results"] if not result["passed"]} == {
        "DQ_REQUIRED_FIELDS", "DQ_TYPE_CONFORMANCE"
    }
    records = client.get("/v1/data-platform/records/customer", headers=RISK).json()["items"]
    assert all(item["record"]["customer_id"] != "C-DP-BAD" for item in records)


def test_data_platform_enforces_source_authorization_and_tenant_scope() -> None:
    unauthorized_source = client.post("/v1/data-platform/ingestion-batches", headers=COMPLIANCE, json={
        "source_system": "untrusted", "contract_id": "DC-CRM-CUSTOMER", "organization_id": "branch-shanghai",
        "records": [valid_customer_record("C-DP-SOURCE")],
    })
    assert unauthorized_source.status_code == 422
    cross_tenant = client.get(
        "/v1/data-platform/records/customer?organization_id=branch-beijing", headers=RISK,
    )
    assert cross_tenant.status_code == 403
    assert client.post("/v1/data-platform/contracts", headers=RISK, json={}).status_code == 403


def test_lineage_chain_can_be_verified_for_accepted_and_rejected_batches() -> None:
    accepted = client.post("/v1/data-platform/ingestion-batches", headers=COMPLIANCE, json={
        "source_system": "crm", "contract_id": "DC-CRM-CUSTOMER", "organization_id": "branch-shanghai",
        "records": [valid_customer_record("C-DP-LINEAGE")],
    })
    assert accepted.status_code == 201
    lineage = client.get("/v1/data-platform/lineage", headers=COMPLIANCE)
    assert lineage.status_code == 200
    assert lineage.json()["items"][0]["target_dataset"] == "canonical.credit.customer"
    integrity = client.get("/v1/data-platform/lineage/integrity", headers=COMPLIANCE)
    assert integrity.status_code == 200
    assert integrity.json()["valid"] is True
