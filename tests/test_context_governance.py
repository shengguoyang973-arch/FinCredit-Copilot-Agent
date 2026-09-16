from app.context_governance import constrain_model_context


def test_model_context_is_hard_bounded_without_losing_evidence_ids(monkeypatch) -> None:
    monkeypatch.setenv("FINCREDIT_AGENT_CONTEXT_MAX_CHARS", "2000")
    evidence, tools, metadata = constrain_model_context(
        [
            {"id": "POL-1", "title": "条款一", "content": "甲" * 3_000},
            {"id": "POL-2", "title": "条款二", "content": "乙" * 3_000},
        ],
        [{"tool_name": "get_canonical_customer_snapshot", "status": "success", "result": {
            "available": True, "freshness": "fresh", "conflicting_fields": [], "classification": "internal",
        }}],
    )
    assert metadata["used_chars"] <= 2_000
    assert metadata["truncated_evidence_ids"] == ["POL-1", "POL-2"]
    assert [item["id"] for item in evidence] == ["POL-1", "POL-2"]
    assert tools[0]["tool_name"] == "get_canonical_customer_snapshot"
    assert metadata["canonical_data"]["freshness"] == "fresh"
