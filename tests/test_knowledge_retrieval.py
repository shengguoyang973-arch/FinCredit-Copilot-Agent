from app.knowledge_retrieval import chunk_policy, retrieve_policy_hits
from app.knowledge_store import SEED_POLICIES


def test_policy_retrieval_ranks_title_and_keyword_matches() -> None:
    hits = retrieve_policy_hits("流动资金 额度", list(SEED_POLICIES))
    assert hits[0].policy.id == "POL-2.1"
    assert hits[0].score > hits[1].score if len(hits) > 1 else True
    assert hits[0].citation.startswith("POL-2.1")


def test_policy_chunks_keep_versioned_citations() -> None:
    chunks = chunk_policy(SEED_POLICIES[1], max_chars=20)
    assert chunks
    assert chunks[0]["id"].startswith("POL-2.1#chunk-")
    assert "版本 2026.01" in chunks[0]["citation"]
