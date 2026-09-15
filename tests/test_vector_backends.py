from langchain_core.documents import Document
import pytest

from app.config import Settings, validate_settings
from app.embedding import HashEmbeddingAdapter, OpenAIEmbeddingAdapter, get_embedding_adapter
from app.vector_store import PGVectorStore, get_vector_store


def test_openai_embedding_adapter_passes_through_batch_and_query_vectors() -> None:
    class FakeEmbeddings:
        def embed_documents(self, texts):
            return [[float(index), 1.0] for index, _ in enumerate(texts)]

        def embed_query(self, text):
            return [2.0, float(len(text))]

    adapter = OpenAIEmbeddingAdapter("text-embedding-3-small", 2)
    adapter._client = FakeEmbeddings()
    assert adapter.embed_documents(["a", "b"]) == [[0.0, 1.0], [1.0, 1.0]]
    assert adapter.embed_query("abc") == [2.0, 3.0]


def test_pgvector_distance_is_normalized_to_cosine_similarity() -> None:
    class FakeStore:
        def similarity_search_with_score_by_vector(self, vector, k):
            assert vector == [1.0, 0.0]
            assert k == 2
            return [
                (Document(page_content="政策 A", metadata={"document_id": "A", "policy_id": "POL-1.2"}), 0.1),
                (Document(page_content="政策 B", metadata={"document_id": "B", "policy_id": "POL-2.1"}), 1.4),
            ]

    adapter = PGVectorStore.__new__(PGVectorStore)
    adapter._store = FakeStore()
    hits = adapter.search([1.0, 0.0], limit=2)
    assert [item.id for item, _ in hits] == ["A", "B"]
    assert [score for _, score in hits] == pytest.approx([0.9, -0.4])


def test_production_readiness_rejects_local_embedding_and_vector_store() -> None:
    errors = validate_settings(Settings(deployment_environment="production", identity_provider="demo-header"))
    assert "生产环境必须使用 openai Embedding Provider" in errors
    assert "生产环境必须使用 pgvector 向量数据库" in errors
    with pytest.raises(RuntimeError, match="Hash Embedding"):
        get_embedding_adapter(Settings(deployment_environment="production"))
    with pytest.raises(RuntimeError, match="内存向量库"):
        get_vector_store(HashEmbeddingAdapter(), Settings(deployment_environment="production"))


def test_invalid_policy_timezone_fails_readiness() -> None:
    errors = validate_settings(Settings(policy_timezone="Mars/Olympus"))
    assert "FINCREDIT_POLICY_TIMEZONE 不是有效的 IANA 时区" in errors
