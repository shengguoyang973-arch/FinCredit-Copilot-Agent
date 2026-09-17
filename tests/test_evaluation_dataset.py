import json

import pytest

from app.config import get_settings
from app.evaluation_dataset import load_evaluation_dataset, validate_evaluation_dataset


def test_default_evaluation_dataset_is_deidentified_and_loadable() -> None:
    manifest, cases = load_evaluation_dataset()
    assert manifest["classification"] == "deidentified"
    assert manifest["case_count"] == 3
    assert all(case.id.startswith("EVAL-") for case in cases)


def test_evaluation_dataset_rejects_direct_identifier_like_content() -> None:
    payload = {
        "dataset_id": "DEID-INVALID-001", "classification": "deidentified", "cases": [{
            "id": "EVAL-INVALID-01", "task": "generate_brief",
            "context": {
                "application_id": "EVAL-APPLICATION-A", "customer_name": "脱敏企业-A", "requested_amount": 100,
                "suggested_max_amount": 100, "conclusion": "人工复核", "findings": [], "evidence": [],
                "materials_complete": True, "missing_materials": [], "registration_hint": "91310000123456789X",
            }, "expected_terms": [], "expected_evidence_ids": [],
        }],
    }
    with pytest.raises(ValueError, match="直接标识"):
        validate_evaluation_dataset(payload)


def test_evaluation_dataset_hash_is_stable_for_same_payload() -> None:
    manifest, _ = load_evaluation_dataset()
    payload = json.loads(get_settings().evaluation_dataset_path.read_text(encoding="utf-8"))
    assert validate_evaluation_dataset(payload)["dataset_hash"] == manifest["dataset_hash"]
