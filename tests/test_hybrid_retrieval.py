from app.embedding import HashEmbeddingAdapter
from app.hybrid_retrieval import HybridPolicyRetriever
from app.knowledge_store import SEED_POLICIES
from app.vector_store import InMemoryVectorStore


def test_hybrid_retriever_combines_lexical_and_vector_scores() -> None:
    retriever = HybridPolicyRetriever(HashEmbeddingAdapter(64), InMemoryVectorStore())
    hits = retriever.search("流动资金贷款额度", list(SEED_POLICIES))
    assert hits
    assert hits[0].policy.id == "POL-2.1"
    assert hits[0].lexical_score > 0
    assert -1 <= hits[0].vector_score <= 1
    assert hits[0].rerank_score == hits[0].score


def test_index_has_versioned_chunk_citations() -> None:
    retriever = HybridPolicyRetriever(HashEmbeddingAdapter(32), InMemoryVectorStore())
    retriever.index([SEED_POLICIES[0]])
    assert retriever.store.count() >= 1
    hits = retriever.search("经营年限", [SEED_POLICIES[0]])
    assert hits[0].citation.startswith("POL-1.2")
